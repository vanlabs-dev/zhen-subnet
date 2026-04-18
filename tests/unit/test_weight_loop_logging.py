"""Unit tests for the weight loop's gating-log rate limiter."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from validator.main import (
    DEFAULT_CHALLENGE_INTERVAL_SECONDS,
    DEFAULT_CLEANUP_INTERVAL_SECONDS,
    DEFAULT_CLEANUP_RETENTION_HOURS,
    DEFAULT_WEIGHT_CHECK_INTERVAL_SECONDS,
    ZhenValidator,
)
from validator.scoring_db import RoundScoreRow, ScoringDB


def _make_logging_validator(tmp_path: Path) -> ZhenValidator:
    """Construct a minimal validator with weight-loop wiring only."""
    v = ZhenValidator.__new__(ZhenValidator)
    v._shutdown = asyncio.Event()
    v._subtensor_lock = asyncio.Lock()
    v._last_gated_log_time = 0.0
    v.challenge_interval_seconds = DEFAULT_CHALLENGE_INTERVAL_SECONDS
    v.weight_check_interval_seconds = DEFAULT_WEIGHT_CHECK_INTERVAL_SECONDS
    v.cleanup_interval_seconds = DEFAULT_CLEANUP_INTERVAL_SECONDS
    v.cleanup_retention_hours = DEFAULT_CLEANUP_RETENTION_HOURS
    v.scoring_window_hours = 72
    v.ema_alpha = 0.3
    v.round_count = 0
    v.netuid = 1
    v.my_uid = 0
    v.scoring_db = ScoringDB(db_path=tmp_path / "scoring.db")
    v.subtensor = MagicMock()
    v.subtensor.weights_rate_limit = MagicMock(return_value=100)
    v.weight_setter = MagicMock()
    v.weight_setter.set_weights = AsyncMock(return_value=True)
    v.weight_setter.copy_weights_from_chain = AsyncMock(return_value={})
    v.alerter = MagicMock()
    v.alerter.send = AsyncMock()
    return v


@pytest.fixture
def logging_validator(tmp_path: Path) -> Iterator[ZhenValidator]:
    """Provide a validator wired for weight-loop logging tests."""
    v = _make_logging_validator(tmp_path)
    yield v
    v.scoring_db.close()


async def test_gating_logs_first_iteration_at_info(
    logging_validator: ZhenValidator, caplog: pytest.LogCaptureFixture
) -> None:
    """The first gated iteration emits an INFO log containing the gating message."""
    caplog.set_level(logging.INFO, logger="validator.main")
    logging_validator.weight_check_interval_seconds = 0.01
    logging_validator._blocks_until_weight_eligible = AsyncMock(return_value=50)  # type: ignore[method-assign]

    task = asyncio.create_task(logging_validator._weight_loop())
    await asyncio.sleep(0.05)
    logging_validator._shutdown.set()
    await asyncio.wait_for(task, timeout=2.0)

    gating = [r for r in caplog.records if r.levelname == "INFO" and "Weights not yet eligible" in r.message]
    assert len(gating) >= 1


async def test_gating_suppresses_subsequent_logs_within_5min(
    logging_validator: ZhenValidator, caplog: pytest.LogCaptureFixture
) -> None:
    """Many iterations within 5min of the first log produce only one INFO log."""
    caplog.set_level(logging.INFO, logger="validator.main")
    logging_validator.weight_check_interval_seconds = 0.005
    logging_validator._blocks_until_weight_eligible = AsyncMock(return_value=50)  # type: ignore[method-assign]

    task = asyncio.create_task(logging_validator._weight_loop())
    await asyncio.sleep(0.15)  # many iterations, all within real-time sub-second window
    logging_validator._shutdown.set()
    await asyncio.wait_for(task, timeout=2.0)

    gating = [r for r in caplog.records if r.levelname == "INFO" and "Weights not yet eligible" in r.message]
    assert len(gating) == 1, f"Expected exactly one gating log, got {len(gating)}: {[r.message for r in gating]}"


async def test_gating_logs_again_after_5min(
    logging_validator: ZhenValidator,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A simulated 301s gap between iterations produces a second INFO log."""
    caplog.set_level(logging.INFO, logger="validator.main")
    logging_validator.weight_check_interval_seconds = 0.01
    logging_validator._blocks_until_weight_eligible = AsyncMock(return_value=50)  # type: ignore[method-assign]

    # Advance simulated monotonic clock by 301s between calls so the rate
    # limiter sees a gap larger than 5 minutes.
    fake_clock = iter([float(i * 301) for i in range(200)])
    fake_time = MagicMock()
    fake_time.monotonic.side_effect = lambda: next(fake_clock)
    monkeypatch.setattr("validator.main.time", fake_time)

    task = asyncio.create_task(logging_validator._weight_loop())
    await asyncio.sleep(0.05)
    logging_validator._shutdown.set()
    await asyncio.wait_for(task, timeout=2.0)

    gating = [r for r in caplog.records if r.levelname == "INFO" and "Weights not yet eligible" in r.message]
    assert len(gating) >= 2, f"Expected >=2 gating logs across simulated gaps, got {len(gating)}"


async def test_successful_commit_resets_gating_log_timer(logging_validator: ZhenValidator) -> None:
    """A successful weight commit resets _last_gated_log_time so the next gate logs."""
    logging_validator._last_gated_log_time = 1234.5
    logging_validator.scoring_db.get_scores_in_window = AsyncMock(  # type: ignore[method-assign]
        return_value=[
            RoundScoreRow(
                id=1,
                round_id="r1",
                uid=0,
                test_case="tc",
                train_period_start=0,
                train_period_end=48,
                test_period_start=48,
                test_period_end=72,
                cvrmse=0.1,
                nmbe=0.01,
                r_squared=0.9,
                sims_used=100,
                composite=0.5,
                reason="",
                received_at="2026-04-18T00:00:00.000Z",
            )
        ]
    )

    result = await logging_validator._compute_and_commit_weights()
    assert result is True
    assert logging_validator._last_gated_log_time == 0.0
