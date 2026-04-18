"""Tests for miner blacklist gates.

Three gates: registration (always active), validator_permit (production
only), stake threshold (production only). On non-production networks
the permit and stake gates are bypassed because testnets are trusted
and requiring permit creates a chicken-and-egg bootstrap problem.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from miner import main as miner_main
from protocol.synapse import CalibrationSynapse


def _synapse_from(hotkey: str) -> CalibrationSynapse:
    """Build a minimal synapse with a dendrite hotkey set."""
    s = CalibrationSynapse()
    s.dendrite = SimpleNamespace(hotkey=hotkey)
    return s


def _fake_metagraph(
    hotkeys: list[str],
    permits: list[bool],
    stakes: list[float | str],
) -> MagicMock:
    """Build a fake metagraph with just the fields blacklist_fn reads.

    ``stakes`` accepts ``str`` so tests can feed malformed entries through
    to the blacklist's ``ValueError`` guard.
    """
    mg = MagicMock()
    mg.hotkeys = hotkeys
    mg.validator_permit = permits
    mg.stake = stakes
    return mg


def test_blacklist_rejects_unregistered_hotkey() -> None:
    """Gate 1: a hotkey absent from metagraph.hotkeys is rejected."""
    with patch.object(miner_main, "_metagraph", _fake_metagraph([], [], [])):
        rejected, reason = miner_main.blacklist_fn(_synapse_from("5Unknown"))
    assert rejected is True
    assert "not registered" in reason


def test_blacklist_rejects_no_permit() -> None:
    """Gate 2: on production, a registered hotkey without validator_permit is rejected."""
    mg = _fake_metagraph(["5Registered"], [False], [10_000.0])
    with (
        patch.object(miner_main, "_metagraph", mg),
        patch.object(miner_main, "_network", "finney"),
    ):
        rejected, reason = miner_main.blacklist_fn(_synapse_from("5Registered"))
    assert rejected is True
    assert "validator_permit" in reason


def test_blacklist_rejects_low_stake() -> None:
    """Gate 3: on production, a permitted hotkey below MIN_VALIDATOR_STAKE_TAO is rejected."""
    mg = _fake_metagraph(["5Permitted"], [True], [50.0])
    with (
        patch.object(miner_main, "_metagraph", mg),
        patch.object(miner_main, "_network", "finney"),
    ):
        rejected, reason = miner_main.blacklist_fn(_synapse_from("5Permitted"))
    assert rejected is True
    assert "stake" in reason.lower()


def test_blacklist_accepts_registered_permitted_high_stake() -> None:
    """All three gates passed on production: sender is accepted."""
    mg = _fake_metagraph(["5Good"], [True], [5000.0])
    with (
        patch.object(miner_main, "_metagraph", mg),
        patch.object(miner_main, "_network", "finney"),
    ):
        rejected, reason = miner_main.blacklist_fn(_synapse_from("5Good"))
    assert rejected is False
    assert reason == ""


def test_blacklist_no_metagraph_accepts_all() -> None:
    """Startup before metagraph is populated: accept all (legacy behavior)."""
    with patch.object(miner_main, "_metagraph", None):
        rejected, _ = miner_main.blacklist_fn(_synapse_from("5Any"))
    assert rejected is False


def test_blacklist_handles_malformed_stake() -> None:
    """Non-numeric stake entry should not crash; treat as zero and reject on production."""
    mg = _fake_metagraph(["5Malformed"], [True], ["not_a_number"])
    with (
        patch.object(miner_main, "_metagraph", mg),
        patch.object(miner_main, "_network", "finney"),
    ):
        rejected, reason = miner_main.blacklist_fn(_synapse_from("5Malformed"))
    assert rejected is True
    assert "stake" in reason.lower()


def test_blacklist_testnet_accepts_unpermitted() -> None:
    """On testnet the permit check is skipped."""
    mg = _fake_metagraph(["5Registered"], [False], [0.0])
    with (
        patch.object(miner_main, "_metagraph", mg),
        patch.object(miner_main, "_network", "test"),
    ):
        rejected, reason = miner_main.blacklist_fn(_synapse_from("5Registered"))
    assert rejected is False, f"Expected testnet accept, got rejection: {reason}"


def test_blacklist_testnet_accepts_low_stake() -> None:
    """On testnet the stake threshold is skipped."""
    mg = _fake_metagraph(["5Low"], [True], [5.0])
    with (
        patch.object(miner_main, "_metagraph", mg),
        patch.object(miner_main, "_network", "test"),
    ):
        rejected, _ = miner_main.blacklist_fn(_synapse_from("5Low"))
    assert rejected is False


def test_blacklist_testnet_still_rejects_unregistered() -> None:
    """Registration gate is always active regardless of network."""
    mg = _fake_metagraph(["5Registered"], [True], [1000.0])
    with (
        patch.object(miner_main, "_metagraph", mg),
        patch.object(miner_main, "_network", "test"),
    ):
        rejected, reason = miner_main.blacklist_fn(_synapse_from("5DefinitelyNot"))
    assert rejected is True
    assert "not registered" in reason
