"""Unit tests for the three decoupled validator loops and their coordination."""

from __future__ import annotations

import asyncio
import signal
import time
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from validator.main import (
    DEFAULT_CHALLENGE_INTERVAL_SECONDS,
    DEFAULT_CLEANUP_INTERVAL_SECONDS,
    DEFAULT_CLEANUP_RETENTION_HOURS,
    DEFAULT_WEIGHT_CHECK_INTERVAL_SECONDS,
    ZhenValidator,
)
from validator.scoring_db import ScoringDB


def _make_loop_validator(tmp_path: Path) -> ZhenValidator:
    """Construct a ZhenValidator wired only for loop tests.

    Bypasses ``__init__`` to avoid needing manifest files, BOPTEST or the
    Bittensor SDK. Populates only the attributes the loop methods touch.
    """
    v = ZhenValidator.__new__(ZhenValidator)
    v._shutdown = asyncio.Event()
    v._subtensor_lock = asyncio.Lock()
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
    return v


@pytest.fixture
def loop_validator(tmp_path: Path) -> Iterator[ZhenValidator]:
    """Provide a minimal validator instance and clean up its DB after."""
    v = _make_loop_validator(tmp_path)
    yield v
    v.scoring_db.close()


async def test_interruptible_sleep_wakes_on_shutdown(loop_validator: ZhenValidator) -> None:
    """A long interruptible sleep returns as soon as the shutdown event fires."""

    async def trigger() -> None:
        await asyncio.sleep(0.05)
        loop_validator._shutdown.set()

    start = time.monotonic()
    await asyncio.gather(loop_validator._interruptible_sleep(100.0), trigger())
    elapsed = time.monotonic() - start
    assert elapsed < 0.5, f"Expected early wake, took {elapsed:.2f}s"


async def test_interruptible_sleep_completes_normally(loop_validator: ZhenValidator) -> None:
    """With no shutdown, interruptible sleep waits the full duration."""
    start = time.monotonic()
    await loop_validator._interruptible_sleep(0.1)
    elapsed = time.monotonic() - start
    assert 0.08 <= elapsed < 0.5, f"Expected ~0.1s, took {elapsed:.2f}s"


def test_signal_handler_sets_shutdown(loop_validator: ZhenValidator) -> None:
    """Calling the signal handler flips the shutdown event."""
    assert not loop_validator._shutdown.is_set()
    loop_validator._handle_shutdown_signal(signal.SIGTERM)
    assert loop_validator._shutdown.is_set()


async def test_challenge_loop_continues_on_exception(loop_validator: ZhenValidator) -> None:
    """An exception inside _run_challenge_round does not kill the loop."""
    loop_validator.challenge_interval_seconds = 0.01
    call_count = 0

    async def boom() -> None:
        nonlocal call_count
        call_count += 1
        raise ValueError("simulated round failure")

    loop_validator._run_challenge_round = boom  # type: ignore[method-assign]

    task = asyncio.create_task(loop_validator._challenge_loop())
    await asyncio.sleep(0.1)
    loop_validator._shutdown.set()
    await asyncio.wait_for(task, timeout=2.0)

    assert call_count >= 2, f"Loop ran only {call_count} time(s); should survive exceptions"


async def test_weight_loop_skips_commit_when_not_eligible(loop_validator: ZhenValidator) -> None:
    """While blocks_remaining > 0 the loop must never call _compute_and_commit_weights."""
    loop_validator.weight_check_interval_seconds = 0.01

    not_eligible = AsyncMock(return_value=50)
    commit = AsyncMock(return_value=True)
    loop_validator._blocks_until_weight_eligible = not_eligible  # type: ignore[method-assign]
    loop_validator._compute_and_commit_weights = commit  # type: ignore[method-assign]

    task = asyncio.create_task(loop_validator._weight_loop())
    await asyncio.sleep(0.1)
    loop_validator._shutdown.set()
    await asyncio.wait_for(task, timeout=2.0)

    assert not_eligible.await_count >= 1
    assert commit.await_count == 0


async def test_weight_loop_commits_when_eligible(loop_validator: ZhenValidator) -> None:
    """With blocks_remaining == 0 the loop commits weights at least once."""
    loop_validator.weight_check_interval_seconds = 0.01

    loop_validator._blocks_until_weight_eligible = AsyncMock(return_value=0)  # type: ignore[method-assign]
    commit = AsyncMock(return_value=True)
    loop_validator._compute_and_commit_weights = commit  # type: ignore[method-assign]

    task = asyncio.create_task(loop_validator._weight_loop())
    await asyncio.sleep(0.1)
    loop_validator._shutdown.set()
    await asyncio.wait_for(task, timeout=2.0)

    assert commit.await_count >= 1


async def test_cleanup_loop_calls_scoring_db_with_retention(loop_validator: ZhenValidator) -> None:
    """Each iteration calls scoring_db.cleanup_older_than(hours=cleanup_retention_hours)."""
    loop_validator.cleanup_interval_seconds = 0.01
    loop_validator.cleanup_retention_hours = 168

    cleanup = AsyncMock(return_value=0)
    loop_validator.scoring_db.cleanup_older_than = cleanup  # type: ignore[method-assign]

    task = asyncio.create_task(loop_validator._cleanup_loop())
    await asyncio.sleep(0.1)
    loop_validator._shutdown.set()
    await asyncio.wait_for(task, timeout=2.0)

    assert cleanup.await_count >= 2
    for call in cleanup.await_args_list:
        assert call.kwargs == {"hours": 168}


async def test_shutdown_event_stops_all_three_loops(loop_validator: ZhenValidator) -> None:
    """Setting the shutdown event causes all three loops to exit promptly."""
    loop_validator.challenge_interval_seconds = 0.01
    loop_validator.weight_check_interval_seconds = 0.01
    loop_validator.cleanup_interval_seconds = 0.01

    loop_validator._run_challenge_round = AsyncMock(return_value=None)  # type: ignore[method-assign]
    loop_validator._blocks_until_weight_eligible = AsyncMock(return_value=0)  # type: ignore[method-assign]
    loop_validator._compute_and_commit_weights = AsyncMock(return_value=True)  # type: ignore[method-assign]
    loop_validator.scoring_db.cleanup_older_than = AsyncMock(return_value=0)  # type: ignore[method-assign]

    tasks = [
        asyncio.create_task(loop_validator._challenge_loop()),
        asyncio.create_task(loop_validator._weight_loop()),
        asyncio.create_task(loop_validator._cleanup_loop()),
    ]
    await asyncio.sleep(0.05)
    loop_validator._shutdown.set()

    done, pending = await asyncio.wait(tasks, timeout=2.0)
    assert pending == set(), f"Some loops did not exit within 2s: {pending}"
    for t in done:
        assert t.exception() is None, f"Loop raised: {t.exception()}"
