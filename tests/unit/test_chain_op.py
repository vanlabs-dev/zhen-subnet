"""Tests for the ``_chain_op`` helper.

The helper is the single point through which all chain RPCs flow. Its job
is to serialize access (one websocket, one recv at a time), wrap in a
timeout, and bridge the sync SDK to asyncio via to_thread.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from validator.main import ZhenValidator
from validator.scoring_db import ScoringDB


def _make_chain_op_validator(tmp_path: Path) -> ZhenValidator:
    """Build a minimal ZhenValidator with only the attrs _chain_op needs."""
    v = ZhenValidator.__new__(ZhenValidator)
    v._shutdown = asyncio.Event()
    v._subtensor_lock = asyncio.Lock()
    v.netuid = 1
    v.my_uid = 0
    v.scoring_db = ScoringDB(db_path=tmp_path / "scoring.db")
    v.subtensor = MagicMock()
    return v


@pytest.fixture
def chain_op_validator(tmp_path: Path) -> Iterator[ZhenValidator]:
    """Provide a minimal validator and clean up its DB afterwards."""
    v = _make_chain_op_validator(tmp_path)
    yield v
    v.scoring_db.close()


class FakeSharedWebsocket:
    """Simulates ``websockets.sync.connection.Connection.recv`` semantics.

    Raises ``RuntimeError`` when two threads are concurrently inside
    ``recv()``. This mimics the real ``ConcurrencyError`` we hit live.
    """

    def __init__(self, work_seconds: float = 0.01) -> None:
        self._in_use = False
        self._guard = threading.Lock()
        self._work = work_seconds
        self.max_concurrent = 0
        self._current = 0

    def recv(self) -> str:
        """Blocking receive; raises if another thread is already inside."""
        with self._guard:
            if self._in_use:
                raise RuntimeError("SimulatedConcurrencyError: two threads in recv")
            self._in_use = True
            self._current += 1
            self.max_concurrent = max(self.max_concurrent, self._current)
        try:
            time.sleep(self._work)
            return "ok"
        finally:
            with self._guard:
                self._in_use = False
                self._current -= 1


async def test_chain_op_returns_result(chain_op_validator: ZhenValidator) -> None:
    """Helper returns whatever the op returns."""
    result = await chain_op_validator._chain_op(lambda: 42)
    assert result == 42


async def test_chain_op_passes_args_and_kwargs(chain_op_validator: ZhenValidator) -> None:
    """Positional and keyword args reach the op verbatim."""
    op = MagicMock(return_value="done")
    result = await chain_op_validator._chain_op(op, 7, netuid=1, uid=2)
    assert result == "done"
    op.assert_called_once_with(7, netuid=1, uid=2)


async def test_chain_op_times_out_on_slow_op(chain_op_validator: ZhenValidator) -> None:
    """A blocking op exceeding the timeout raises asyncio.TimeoutError."""

    def slow() -> str:
        time.sleep(0.5)
        return "never"

    with pytest.raises(asyncio.TimeoutError):
        await chain_op_validator._chain_op(slow, timeout=0.1)


async def test_chain_op_serializes_concurrent_callers(chain_op_validator: ZhenValidator) -> None:
    """10 concurrent _chain_op calls against a shared websocket never race."""
    fake_ws = FakeSharedWebsocket(work_seconds=0.02)

    async def call_once() -> str:
        result: str = await chain_op_validator._chain_op(fake_ws.recv)
        return result

    results = await asyncio.gather(*(call_once() for _ in range(10)))
    assert results == ["ok"] * 10
    assert fake_ws.max_concurrent == 1, (
        f"Expected strict serialization; max concurrent observed = {fake_ws.max_concurrent}"
    )


async def test_chain_op_without_lock_would_race() -> None:
    """Sanity check: without the async lock, ``asyncio.to_thread`` races the fake websocket.

    If this test ever stops raising, the serialization test above would
    become a tautology. Keep both together.
    """
    fake_ws = FakeSharedWebsocket(work_seconds=0.05)

    results = await asyncio.gather(
        *(asyncio.to_thread(fake_ws.recv) for _ in range(10)),
        return_exceptions=True,
    )
    concurrency_errors = [r for r in results if isinstance(r, RuntimeError)]
    assert concurrency_errors, "Expected at least one simulated ConcurrencyError without the lock"


async def test_chain_op_propagates_exceptions(chain_op_validator: ZhenValidator) -> None:
    """A raising op propagates the exception and releases the lock."""

    def boom() -> None:
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        await chain_op_validator._chain_op(boom)

    # Subsequent call must proceed (lock released after exception).
    assert await chain_op_validator._chain_op(lambda: "released") == "released"


async def test_chain_op_releases_lock_after_timeout(chain_op_validator: ZhenValidator) -> None:
    """After a TimeoutError, the lock is released and the next call acquires it."""

    def slow() -> str:
        time.sleep(0.5)
        return "never"

    with pytest.raises(asyncio.TimeoutError):
        await chain_op_validator._chain_op(slow, timeout=0.05)

    assert not chain_op_validator._subtensor_lock.locked()
    assert await chain_op_validator._chain_op(lambda: "post-timeout") == "post-timeout"
