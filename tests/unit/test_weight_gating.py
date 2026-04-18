"""Unit tests for ``_blocks_until_weight_eligible``."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from tenacity import wait_fixed

from validator.main import ZhenValidator
from validator.scoring_db import ScoringDB


def _make_gating_validator(tmp_path: Path) -> ZhenValidator:
    """Build a ZhenValidator wired only for weight-gating queries."""
    v = ZhenValidator.__new__(ZhenValidator)
    v._shutdown = asyncio.Event()
    v._subtensor_lock = asyncio.Lock()
    v.netuid = 1
    v.my_uid = 0
    v.scoring_db = ScoringDB(db_path=tmp_path / "scoring.db")
    v.subtensor = MagicMock()
    return v


@pytest.fixture(autouse=True)
def _fast_tenacity_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    """Collapse tenacity's 10s backoff so retry tests run instantly."""
    monkeypatch.setattr("validator.main.wait_fixed", lambda _seconds: wait_fixed(0))


async def test_blocks_until_eligible_zero_when_long_since_last_update(tmp_path: Path) -> None:
    """rate_limit=100, blocks_since=150 means we're eligible; return 0."""
    v = _make_gating_validator(tmp_path)
    try:
        v.subtensor.weights_rate_limit = MagicMock(return_value=100)
        v.subtensor.blocks_since_last_update = MagicMock(return_value=150)
        assert await v._blocks_until_weight_eligible() == 0
    finally:
        v.scoring_db.close()


async def test_blocks_until_eligible_positive_when_recent(tmp_path: Path) -> None:
    """rate_limit=100, blocks_since=20 means 80 blocks to wait."""
    v = _make_gating_validator(tmp_path)
    try:
        v.subtensor.weights_rate_limit = MagicMock(return_value=100)
        v.subtensor.blocks_since_last_update = MagicMock(return_value=20)
        assert await v._blocks_until_weight_eligible() == 80
    finally:
        v.scoring_db.close()


async def test_blocks_until_eligible_clamps_to_zero_never_negative(tmp_path: Path) -> None:
    """Even if blocks_since exceeds rate_limit by a lot, we never return a negative."""
    v = _make_gating_validator(tmp_path)
    try:
        v.subtensor.weights_rate_limit = MagicMock(return_value=100)
        v.subtensor.blocks_since_last_update = MagicMock(return_value=5000)
        assert await v._blocks_until_weight_eligible() == 0
    finally:
        v.scoring_db.close()


async def test_blocks_until_eligible_retries_on_transient_error(tmp_path: Path) -> None:
    """Two ConnectionErrors followed by success yields the right answer after 3 attempts."""
    v = _make_gating_validator(tmp_path)
    try:
        v.subtensor.weights_rate_limit = MagicMock(
            side_effect=[ConnectionError("boom1"), ConnectionError("boom2"), 100]
        )
        v.subtensor.blocks_since_last_update = MagicMock(return_value=50)

        result = await v._blocks_until_weight_eligible()
        assert result == 50
        assert v.subtensor.weights_rate_limit.call_count == 3
        assert v.subtensor.blocks_since_last_update.call_count == 1
    finally:
        v.scoring_db.close()


async def test_blocks_until_eligible_raises_after_three_failures(tmp_path: Path) -> None:
    """Three consecutive ConnectionErrors propagate out (reraise=True)."""
    v = _make_gating_validator(tmp_path)
    try:
        v.subtensor.weights_rate_limit = MagicMock(side_effect=ConnectionError("always broken"))
        v.subtensor.blocks_since_last_update = MagicMock(return_value=50)

        with pytest.raises(ConnectionError, match="always broken"):
            await v._blocks_until_weight_eligible()
        assert v.subtensor.weights_rate_limit.call_count == 3
    finally:
        v.scoring_db.close()
