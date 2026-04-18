"""Composition test: _compute_and_commit_weights + WeightSetter + _chain_op.

The Prompt C/D deadlock slipped through because every existing test that
touched _compute_and_commit_weights mocked either WeightSetter.set_weights
or _compute_and_commit_weights itself. No test exercised the real
composition. This test does.

If this test hangs (times out at asyncio.wait_for), the lock-reentrancy
deadlock has regressed. The timeout is intentional: a hanging commit
means the bug is back.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scoring.engine import VerifiedResult
from validator.main import ZhenValidator
from validator.scoring_db import ScoringDB
from validator.weights.setter import WeightSetter


async def test_compute_and_commit_weights_does_not_deadlock(tmp_path: Path) -> None:
    """The real composition must not deadlock on _subtensor_lock."""
    v = ZhenValidator.__new__(ZhenValidator)
    v._shutdown = asyncio.Event()
    v._subtensor_lock = asyncio.Lock()
    v._last_gated_log_time = 0.0
    v._weight_commit_started_at = None
    v.netuid = 1
    v.my_uid = 0
    v.scoring_db = ScoringDB(db_path=tmp_path / "scoring.db")
    v.scoring_window_hours = 72
    v.ema_alpha = 0.3
    v.round_count = 0
    v.alerter = MagicMock()
    v.alerter.send = MagicMock(return_value=asyncio.sleep(0))

    fake_subtensor = MagicMock()
    fake_response = MagicMock()
    fake_response.success = True
    fake_response.block_hash = "fake_hash"
    fake_subtensor.set_weights = MagicMock(return_value=fake_response)

    fake_wallet = MagicMock()
    fake_metagraph = MagicMock()

    v.subtensor = fake_subtensor
    v.wallet = fake_wallet
    v.metagraph = fake_metagraph

    v.weight_setter = WeightSetter(
        subtensor=fake_subtensor,
        wallet=fake_wallet,
        netuid=1,
        metagraph=fake_metagraph,
        chain_op=v._chain_op,
    )

    await v.scoring_db.insert_round_scores(
        round_id="round-test",
        test_case="bestest_hydronic",
        train_period=(0, 336),
        test_period=(336, 504),
        verified={
            1: VerifiedResult(
                cvrmse=0.1,
                nmbe=0.05,
                r_squared=0.9,
                simulations_used=100,
            )
        },
        composites={1: 1.0},
    )

    try:
        result = await asyncio.wait_for(v._compute_and_commit_weights(), timeout=5.0)
    except asyncio.TimeoutError:
        pytest.fail("_compute_and_commit_weights hung past 5s; _subtensor_lock reentrancy deadlock has regressed")

    assert result is True, "Expected successful commit"
    fake_subtensor.set_weights.assert_called_once()

    v.scoring_db.close()
