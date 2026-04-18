"""Unit tests for WeightSetter error messaging and chain-copy fallback edge cases."""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock

import numpy as np
import pytest

from validator.weights.setter import WeightSetter


def _make_setter(metagraph: Any = None) -> WeightSetter:
    """Build a WeightSetter with mocked subtensor + wallet."""
    subtensor = MagicMock()
    wallet = MagicMock()
    return WeightSetter(subtensor=subtensor, wallet=wallet, netuid=1, metagraph=metagraph)


def test_failure_response_logs_error_message_field(caplog: pytest.LogCaptureFixture) -> None:
    """When response has success=False and error_message, the log includes it and the type name."""
    caplog.set_level(logging.ERROR, logger="validator.weights.setter")

    class FakeResponse:
        success = False
        error_message = "insufficient balance"

    setter = _make_setter()
    setter.subtensor.set_weights.return_value = FakeResponse()

    uids = np.array([1], dtype=np.int64)
    weights = np.array([1.0], dtype=np.float32)
    ok = setter._set_weights_sync(uids, weights)
    assert ok is False

    errors = [r for r in caplog.records if r.levelname == "ERROR"]
    assert any("insufficient balance" in r.message for r in errors)
    assert any("FakeResponse" in r.message for r in errors)


def test_failure_response_falls_back_to_repr_when_no_field(caplog: pytest.LogCaptureFixture) -> None:
    """When response has no known error attribute, the log falls back to repr."""
    caplog.set_level(logging.ERROR, logger="validator.weights.setter")

    class NoFieldResponse:
        success = False

        def __repr__(self) -> str:
            return "NoFieldResponse(opaque=True)"

    setter = _make_setter()
    setter.subtensor.set_weights.return_value = NoFieldResponse()

    uids = np.array([1], dtype=np.int64)
    weights = np.array([1.0], dtype=np.float32)
    ok = setter._set_weights_sync(uids, weights)
    assert ok is False

    errors = [r for r in caplog.records if r.levelname == "ERROR"]
    assert any("repr=" in r.message for r in errors)
    assert any("NoFieldResponse(opaque=True)" in r.message for r in errors)


async def test_copy_weights_returns_empty_on_fresh_chain(caplog: pytest.LogCaptureFixture) -> None:
    """Empty metagraph.weights yields {} with an INFO log explaining the fresh-subnet state."""
    caplog.set_level(logging.INFO, logger="validator.weights.setter")

    metagraph = MagicMock()
    metagraph.weights = np.array([])
    metagraph.validator_permit = np.array([True])
    metagraph.sync = MagicMock()

    setter = _make_setter(metagraph=metagraph)
    result = await setter.copy_weights_from_chain()
    assert result == {}

    infos = [r for r in caplog.records if r.levelname == "INFO"]
    assert any("no prior weights" in r.message for r in infos)


async def test_copy_weights_returns_empty_on_no_permit(caplog: pytest.LogCaptureFixture) -> None:
    """All-False validator_permit yields {} with an INFO log (not an error)."""
    caplog.set_level(logging.INFO, logger="validator.weights.setter")

    metagraph = MagicMock()
    metagraph.weights = np.array([[0.1, 0.2], [0.3, 0.4]])
    metagraph.validator_permit = np.array([False, False])
    metagraph.stake = np.array([100.0, 200.0])
    metagraph.uids = np.array([0, 1])
    metagraph.sync = MagicMock()

    setter = _make_setter(metagraph=metagraph)
    result = await setter.copy_weights_from_chain()
    assert result == {}

    infos = [r for r in caplog.records if r.levelname == "INFO"]
    assert any("No validators with permit" in r.message for r in infos)


async def test_copy_weights_returns_empty_on_zero_total_stake(caplog: pytest.LogCaptureFixture) -> None:
    """Valid permit but zero total stake yields {} with an INFO log."""
    caplog.set_level(logging.INFO, logger="validator.weights.setter")

    metagraph = MagicMock()
    metagraph.weights = np.array([[0.1, 0.2], [0.3, 0.4]])
    metagraph.validator_permit = np.array([True, True])
    metagraph.stake = np.array([0.0, 0.0])
    metagraph.uids = np.array([0, 1])
    metagraph.sync = MagicMock()

    setter = _make_setter(metagraph=metagraph)
    result = await setter.copy_weights_from_chain()
    assert result == {}

    infos = [r for r in caplog.records if r.levelname == "INFO"]
    assert any("Total validator stake is zero" in r.message for r in infos)
