"""Tests for the weight-commit hang watchdog.

The watchdog monitors ``_weight_commit_started_at``. When a commit has been
in flight longer than ``WEIGHT_COMMIT_WATCHDOG_SECONDS``, it calls
``os._exit(1)``. Tests monkeypatch ``os._exit`` to raise a distinct
exception so we can assert on the exit code without killing the runner.

Also covers the second-SIGINT force-exit behaviour added alongside the
watchdog: the first signal requests graceful shutdown, repeated signals
within the grace window continue graceful shutdown, and a signal past the
grace window calls ``os._exit(0)``.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import time
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from validator.main import (
    SHUTDOWN_GRACE_SECONDS,
    WEIGHT_COMMIT_WATCHDOG_SECONDS,
    ZhenValidator,
)


class _ExitCalled(Exception):
    """Distinct exception so tests can confirm os._exit was invoked.

    Not a SystemExit subclass: Python 3.10's asyncio propagates
    BaseException subclasses out of wait_for in a way that escapes
    pytest.raises, so the sentinel stays a plain Exception.
    """

    def __init__(self, code: int) -> None:
        super().__init__(code)
        self.code = code


def _make_watchdog_validator(tmp_path: Path) -> ZhenValidator:
    """Build a minimal validator with only the watchdog-relevant fields set."""
    v = ZhenValidator.__new__(ZhenValidator)
    v._shutdown = asyncio.Event()
    v._subtensor_lock = asyncio.Lock()
    v._weight_commit_started_at = None
    v._first_shutdown_at = None
    v.netuid = 1
    v.my_uid = 0
    v.subtensor = MagicMock()
    return v


@pytest.fixture
def watchdog_validator(tmp_path: Path) -> Iterator[ZhenValidator]:
    """Provide a minimal validator for watchdog tests."""
    v = _make_watchdog_validator(tmp_path)
    yield v


async def test_watchdog_no_commit_in_flight_does_not_exit(
    watchdog_validator: ZhenValidator,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no commit in flight, the watchdog never calls os._exit even across many poll cycles."""
    exit_calls: list[int] = []
    monkeypatch.setattr("validator.main.os._exit", lambda code: exit_calls.append(code))
    monkeypatch.setattr("validator.main.WEIGHT_COMMIT_WATCHDOG_SECONDS", 0.05)

    async def fast_sleep(seconds: float) -> None:
        await asyncio.sleep(0.005)

    watchdog_validator._interruptible_sleep = fast_sleep  # type: ignore[method-assign]
    watchdog_validator._weight_commit_started_at = None

    task = asyncio.create_task(watchdog_validator._weight_commit_watchdog())
    await asyncio.sleep(0.1)
    watchdog_validator._shutdown.set()
    await asyncio.wait_for(task, timeout=2.0)

    assert exit_calls == [], f"Expected no exit calls, got {exit_calls}"


async def test_watchdog_fires_when_commit_exceeds_threshold(
    watchdog_validator: ZhenValidator,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A commit older than the threshold triggers os._exit(1)."""
    exit_calls: list[int] = []

    def fake_exit(code: int) -> None:
        exit_calls.append(code)
        raise _ExitCalled(code)

    monkeypatch.setattr("validator.main.os._exit", fake_exit)
    monkeypatch.setattr("validator.main.WEIGHT_COMMIT_WATCHDOG_SECONDS", 0.1)

    async def fast_sleep(seconds: float) -> None:
        await asyncio.sleep(0.005)

    watchdog_validator._interruptible_sleep = fast_sleep  # type: ignore[method-assign]
    watchdog_validator._weight_commit_started_at = time.monotonic() - 1.0

    with pytest.raises(_ExitCalled) as exc_info:
        await asyncio.wait_for(
            watchdog_validator._weight_commit_watchdog(),
            timeout=2.0,
        )

    assert exit_calls == [1]
    assert exc_info.value.code == 1


async def test_watchdog_does_not_fire_under_threshold(
    watchdog_validator: ZhenValidator,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A commit younger than the threshold does not trigger os._exit."""
    exit_calls: list[int] = []
    monkeypatch.setattr("validator.main.os._exit", lambda code: exit_calls.append(code))
    # Leave threshold at the real default (180s); 50s elapsed is well below.
    assert WEIGHT_COMMIT_WATCHDOG_SECONDS >= 120.0, (
        "Watchdog threshold must remain >= WeightSetter's own 120s timeout so this stays a backstop, not a duplicate"
    )

    async def fast_sleep(seconds: float) -> None:
        await asyncio.sleep(0.005)

    watchdog_validator._interruptible_sleep = fast_sleep  # type: ignore[method-assign]
    watchdog_validator._weight_commit_started_at = time.monotonic() - 50.0

    task = asyncio.create_task(watchdog_validator._weight_commit_watchdog())
    await asyncio.sleep(0.1)
    watchdog_validator._shutdown.set()
    await asyncio.wait_for(task, timeout=2.0)

    assert exit_calls == [], f"Expected no exit under threshold, got {exit_calls}"


async def test_watchdog_stops_on_shutdown_event(
    watchdog_validator: ZhenValidator,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Setting the shutdown event causes the watchdog to exit its loop cleanly."""
    caplog.set_level(logging.INFO, logger="validator.main")
    exit_calls: list[int] = []
    monkeypatch.setattr("validator.main.os._exit", lambda code: exit_calls.append(code))

    async def fast_sleep(seconds: float) -> None:
        await asyncio.sleep(0.005)

    watchdog_validator._interruptible_sleep = fast_sleep  # type: ignore[method-assign]

    task = asyncio.create_task(watchdog_validator._weight_commit_watchdog())
    await asyncio.sleep(0.02)
    watchdog_validator._shutdown.set()
    await asyncio.wait_for(task, timeout=2.0)

    assert task.done()
    assert exit_calls == []
    exit_logs = [r for r in caplog.records if "Weight-commit watchdog exiting" in r.message]
    assert len(exit_logs) == 1, f"Expected one exit log, got {[r.message for r in exit_logs]}"


def test_first_sigint_requests_graceful(
    watchdog_validator: ZhenValidator,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The first SIGINT sets the shutdown event and records the timestamp but does not exit."""
    exit_calls: list[int] = []
    monkeypatch.setattr("validator.main.os._exit", lambda code: exit_calls.append(code))

    watchdog_validator._handle_shutdown_signal(signal.SIGINT)

    assert watchdog_validator._shutdown.is_set()
    assert watchdog_validator._first_shutdown_at is not None
    assert exit_calls == []


def test_second_sigint_within_grace_window_does_not_force_exit(
    watchdog_validator: ZhenValidator,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Second SIGINT within grace does not exit; a signal past grace force-exits via os._exit(0)."""
    exit_calls: list[int] = []

    def fake_exit(code: int) -> None:
        exit_calls.append(code)
        raise _ExitCalled(code)

    monkeypatch.setattr("validator.main.os._exit", fake_exit)

    # First SIGINT records the shutdown timestamp.
    watchdog_validator._handle_shutdown_signal(signal.SIGINT)
    assert exit_calls == []
    first_at = watchdog_validator._first_shutdown_at
    assert first_at is not None

    # Second SIGINT within the grace window must NOT force-exit.
    watchdog_validator._handle_shutdown_signal(signal.SIGINT)
    assert exit_calls == [], "Within grace window, should not force exit"

    # Advance simulated clock past the grace window; next signal force-exits.
    future = first_at + SHUTDOWN_GRACE_SECONDS + 1.0
    fake_time = MagicMock()
    fake_time.monotonic.return_value = future
    monkeypatch.setattr("validator.main.time", fake_time)

    with pytest.raises(_ExitCalled) as exc_info:
        watchdog_validator._handle_shutdown_signal(signal.SIGINT)

    assert exit_calls == [0]
    assert exc_info.value.code == 0
