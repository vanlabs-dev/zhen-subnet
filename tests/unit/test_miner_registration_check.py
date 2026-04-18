"""Test that an unregistered miner fails fast on startup.

An unregistered hotkey used to silently start the axon and sit idle
forever, giving the operator no signal that the misconfiguration was
the problem. The registration check in ZhenMiner._init_bittensor now
raises RuntimeError with a `btcli subnet register` hint instead.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from miner import main as miner_main


def _fake_bt_with_metagraph_hotkeys(hotkeys: list[str], self_hotkey: str) -> MagicMock:
    """Build a fake `bt` module whose Subtensor().metagraph().hotkeys == hotkeys
    and whose Wallet().hotkey.ss58_address == self_hotkey."""
    fake_bt = MagicMock()

    wallet_instance = MagicMock()
    wallet_instance.hotkey.ss58_address = self_hotkey
    fake_bt.Wallet = MagicMock(return_value=wallet_instance)

    metagraph_instance = MagicMock()
    metagraph_instance.hotkeys = hotkeys
    metagraph_instance.neurons = [MagicMock() for _ in hotkeys]

    subtensor_instance = MagicMock()
    subtensor_instance.metagraph = MagicMock(return_value=metagraph_instance)
    fake_bt.Subtensor = MagicMock(return_value=subtensor_instance)

    fake_bt.Axon = MagicMock()

    return fake_bt


def test_unregistered_miner_raises() -> None:
    """Miner hotkey not in metagraph.hotkeys must raise RuntimeError."""
    fake_bt = _fake_bt_with_metagraph_hotkeys(
        hotkeys=["5SomeoneElse", "5AnotherValidator"],
        self_hotkey="5UnregisteredMiner",
    )
    with patch.object(miner_main, "bt", fake_bt), pytest.raises(RuntimeError) as exc_info:
        miner_main.ZhenMiner(
            netuid=999,
            network="test",
            wallet_name="zhen-miner",
            wallet_hotkey="default",
            n_calls=1,
        )

    msg = str(exc_info.value)
    assert "5UnregisteredMiner" in msg
    assert "btcli subnet register" in msg
    assert "netuid 999" in msg
    # Axon must NOT be constructed if the registration check fails.
    assert fake_bt.Axon.call_count == 0


def test_registered_miner_does_not_raise() -> None:
    """A hotkey that is present in metagraph.hotkeys must pass the check."""
    self_hotkey = "5RegisteredMiner"
    fake_bt = _fake_bt_with_metagraph_hotkeys(
        hotkeys=["5Other", self_hotkey, "5Third"],
        self_hotkey=self_hotkey,
    )
    with patch.object(miner_main, "bt", fake_bt):
        miner = miner_main.ZhenMiner(
            netuid=456,
            network="test",
            wallet_name="zhen-miner",
            wallet_hotkey="default",
            n_calls=1,
        )

    assert miner is not None
    # Axon IS constructed when registration passes.
    assert fake_bt.Axon.call_count == 1
