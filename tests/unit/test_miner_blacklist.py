"""Tests for miner blacklist gates.

Three gates in order: registration, validator_permit, stake threshold.
Each gate must independently block non-conforming senders; all three
must pass for acceptance.
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


def _fake_metagraph(hotkeys: list[str], permits: list[bool], stakes: list[float]) -> MagicMock:
    """Build a fake metagraph with just the fields blacklist_fn reads."""
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
    """Gate 2: a registered hotkey without validator_permit is rejected."""
    mg = _fake_metagraph(["5Registered"], [False], [10_000.0])
    with patch.object(miner_main, "_metagraph", mg):
        rejected, reason = miner_main.blacklist_fn(_synapse_from("5Registered"))
    assert rejected is True
    assert "validator_permit" in reason


def test_blacklist_rejects_low_stake() -> None:
    """Gate 3: a permitted hotkey below MIN_VALIDATOR_STAKE_TAO is rejected."""
    mg = _fake_metagraph(["5Permitted"], [True], [50.0])
    with patch.object(miner_main, "_metagraph", mg):
        rejected, reason = miner_main.blacklist_fn(_synapse_from("5Permitted"))
    assert rejected is True
    assert "stake" in reason.lower()


def test_blacklist_accepts_registered_permitted_high_stake() -> None:
    """All three gates passed: sender is accepted."""
    mg = _fake_metagraph(["5Good"], [True], [5000.0])
    with patch.object(miner_main, "_metagraph", mg):
        rejected, reason = miner_main.blacklist_fn(_synapse_from("5Good"))
    assert rejected is False
    assert reason == ""


def test_blacklist_no_metagraph_accepts_all() -> None:
    """Startup before metagraph is populated: accept all (legacy behavior)."""
    with patch.object(miner_main, "_metagraph", None):
        rejected, _ = miner_main.blacklist_fn(_synapse_from("5Any"))
    assert rejected is False


def test_blacklist_handles_malformed_stake() -> None:
    """Non-numeric stake entry should not crash; treat as zero and reject."""
    mg = _fake_metagraph(["5Malformed"], [True], ["not_a_number"])
    with patch.object(miner_main, "_metagraph", mg):
        rejected, reason = miner_main.blacklist_fn(_synapse_from("5Malformed"))
    assert rejected is True
    assert "stake" in reason.lower()
