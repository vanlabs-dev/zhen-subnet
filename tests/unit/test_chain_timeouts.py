"""Unit tests for per-call chain RPC timeouts and retry interaction."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from tenacity import wait_fixed

from validator.main import ZhenValidator
from validator.scoring_db import ScoringDB
from validator.weights.setter import WeightSetter


def _make_timeout_validator(tmp_path: Path) -> ZhenValidator:
    """Build a ZhenValidator wired for chain-timeout tests."""
    v = ZhenValidator.__new__(ZhenValidator)
    v._shutdown = asyncio.Event()
    v._subtensor_lock = asyncio.Lock()
    v._last_gated_log_time = 0.0
    v.challenge_interval_seconds = 900
    v.weight_check_interval_seconds = 60
    v.cleanup_interval_seconds = 86400
    v.cleanup_retention_hours = 168
    v.scoring_window_hours = 72
    v.ema_alpha = 0.3
    v.round_count = 0
    v.netuid = 1
    v.my_uid = 0
    v.scoring_db = ScoringDB(db_path=tmp_path / "scoring.db")
    v.subtensor = MagicMock()
    return v


@pytest.fixture
def timeout_validator(tmp_path: Path) -> Iterator[ZhenValidator]:
    """Provide a minimal validator with cleanup of its DB after the test."""
    v = _make_timeout_validator(tmp_path)
    yield v
    v.scoring_db.close()


@pytest.fixture(autouse=True)
def _fast_chain_timeouts(monkeypatch: pytest.MonkeyPatch) -> None:
    """Collapse 30s chain-read timeout and tenacity backoff so tests run quickly."""
    monkeypatch.setattr("validator.main.CHAIN_READ_TIMEOUT_SECONDS", 0.1)
    monkeypatch.setattr("validator.main.wait_fixed", lambda _seconds: wait_fixed(0))


async def test_blocks_until_eligible_times_out_on_slow_weights_rate_limit(
    timeout_validator: ZhenValidator,
) -> None:
    """A slow weights_rate_limit call times out and the retry eventually reraises."""

    def slow(**_kwargs: object) -> int:
        time.sleep(0.5)
        return 100

    timeout_validator.subtensor.weights_rate_limit = MagicMock(side_effect=slow)
    timeout_validator.subtensor.blocks_since_last_update = MagicMock(return_value=50)

    with pytest.raises(asyncio.TimeoutError):
        await timeout_validator._blocks_until_weight_eligible()

    assert timeout_validator.subtensor.weights_rate_limit.call_count == 3


async def test_blocks_until_eligible_times_out_on_slow_blocks_since(
    timeout_validator: ZhenValidator,
) -> None:
    """A slow blocks_since_last_update call also triggers timeout + retry + reraise."""
    timeout_validator.subtensor.weights_rate_limit = MagicMock(return_value=100)

    def slow(**_kwargs: object) -> int:
        time.sleep(0.5)
        return 50

    timeout_validator.subtensor.blocks_since_last_update = MagicMock(side_effect=slow)

    with pytest.raises(asyncio.TimeoutError):
        await timeout_validator._blocks_until_weight_eligible()

    assert timeout_validator.subtensor.blocks_since_last_update.call_count == 3


async def test_tenacity_retries_on_timeout_error(timeout_validator: ZhenValidator) -> None:
    """asyncio.TimeoutError raised inside the attempt is retried; final call succeeds."""
    timeout_validator.subtensor.weights_rate_limit = MagicMock(
        side_effect=[asyncio.TimeoutError(), asyncio.TimeoutError(), 100]
    )
    timeout_validator.subtensor.blocks_since_last_update = MagicMock(return_value=50)

    result = await timeout_validator._blocks_until_weight_eligible()
    assert result == 50
    assert timeout_validator.subtensor.weights_rate_limit.call_count == 3
    assert timeout_validator.subtensor.blocks_since_last_update.call_count == 1


async def test_metagraph_sync_times_out_in_copy_weights(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A hung metagraph.sync in copy_weights_from_chain returns {} and logs a traceback."""
    monkeypatch.setattr("validator.weights.setter.METAGRAPH_SYNC_TIMEOUT_SECONDS", 0.1)

    caplog.set_level(logging.INFO, logger="validator.weights.setter")

    metagraph = MagicMock()

    def slow_sync(**_kwargs: object) -> None:
        time.sleep(0.5)

    metagraph.sync = MagicMock(side_effect=slow_sync)
    subtensor = MagicMock()
    wallet = MagicMock()
    setter = WeightSetter(subtensor=subtensor, wallet=wallet, netuid=1, metagraph=metagraph)

    result = await setter.copy_weights_from_chain()
    assert result == {}

    errors = [r for r in caplog.records if r.levelname == "ERROR"]
    assert any("Chain-copy fallback raised unexpectedly" in r.message for r in errors)


async def test_weight_loop_continues_after_gate_read_timeout(
    timeout_validator: ZhenValidator, caplog: pytest.LogCaptureFixture
) -> None:
    """When _blocks_until_weight_eligible keeps raising TimeoutError the loop keeps iterating."""
    caplog.set_level(logging.ERROR, logger="validator.main")
    timeout_validator.weight_check_interval_seconds = 0.01

    probe = AsyncMock(side_effect=asyncio.TimeoutError())
    timeout_validator._blocks_until_weight_eligible = probe  # type: ignore[method-assign]

    task = asyncio.create_task(timeout_validator._weight_loop())
    await asyncio.sleep(0.1)
    timeout_validator._shutdown.set()
    await asyncio.wait_for(task, timeout=2.0)

    assert probe.await_count >= 2, f"Loop stopped iterating after first TimeoutError (awaits={probe.await_count})"
    errors = [r for r in caplog.records if r.levelname == "ERROR"]
    assert any("Weight loop iteration failed" in r.message for r in errors)
