"""Integration tests for the full round loop.

Tests the complete validator round pipeline without BOPTEST or chain.
Uses the RC model with default params as ground truth.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from validator.round import split_generator, test_case_selector
from validator.round.orchestrator import RoundOrchestrator
from validator.scoring import breakdown
from validator.scoring.ema import EMATracker
from validator.scoring.engine import ScoringEngine
from validator.verification.engine import VerificationEngine

MANIFEST_PATH = Path(__file__).resolve().parent / "fixtures" / "single_case_manifest.json"
TEST_CASE_ID = "bestest_hydronic_heat_pump"
_ZHEN_CONFIG = Path.home() / ".zhen" / "test_cases" / TEST_CASE_ID / "config.json"

pytestmark = pytest.mark.skipif(
    not _ZHEN_CONFIG.exists(),
    reason="Integration test requires local test case data in ~/.zhen/test_cases/",
)

DEFAULT_PARAMS = {
    "wall_r_value": 3.5,
    "roof_r_value": 5.0,
    "zone_capacitance": 200000.0,
    "infiltration_ach": 0.5,
    "hvac_cop": 3.5,
    "solar_gain_factor": 0.4,
}

# Near-optimal params that pass the anti-gaming default check (>0.1% deviation)
# while still producing near-perfect scores against default ground truth.
NEAR_OPTIMAL_PARAMS = {
    "wall_r_value": 3.52,
    "roof_r_value": 5.02,
    "zone_capacitance": 200400.0,
    "infiltration_ach": 0.502,
    "hvac_cop": 3.52,
    "solar_gain_factor": 0.402,
}


async def _run_round(
    orchestrator: RoundOrchestrator,
    scoring_engine: ScoringEngine,
    ema: EMATracker,
    verification_engine: VerificationEngine,
    miner_submissions: dict[int, dict[str, Any]],
    round_id: str,
) -> dict[str, Any]:
    """Run a single calibration round by wiring components directly.

    Mirrors the pipeline in validator/main.py for integration testing.
    """
    test_case = test_case_selector.select(round_id, orchestrator.manifest)
    _train_period, test_period = split_generator.compute(round_id, test_case["id"])
    held_out_data = await orchestrator.generate_ground_truth(test_case, test_period, local_mode=True)
    verification_config = orchestrator.build_verification_config(test_case)
    sim_budget = verification_config.get("simulation_budget", 1000)

    verified = await verification_engine.verify_all(
        miner_submissions,
        verification_config,
        test_period,
        held_out_data,
        sim_budget=sim_budget,
    )

    scores = scoring_engine.compute(verified, sim_budget=sim_budget)
    raw_scores = scoring_engine.compute_raw(verified, sim_budget=sim_budget)

    ema.update(scores)
    weights = ema.get_weights()

    breakdowns: dict[int, dict[str, Any]] = {}
    for uid, v in verified.items():
        breakdowns[uid] = breakdown.generate(
            uid=uid,
            verified=v,
            composite=raw_scores.get(uid, 0.0),
            weights=weights,
            round_id=round_id,
            sim_budget=sim_budget,
        )

    return {
        "round_id": round_id,
        "test_case_id": test_case["id"],
        "scores": scores,
        "raw_scores": raw_scores,
        "weights": weights,
        "breakdowns": breakdowns,
        "verified": verified,
    }


@pytest.mark.asyncio
async def test_full_round_local() -> None:
    """Full round: Miner 0 (exact) > Miner 1 (close) > Miner 2 (far off)."""
    orchestrator = RoundOrchestrator(manifest_path=MANIFEST_PATH)
    scoring_engine = ScoringEngine()
    ema = EMATracker(alpha=0.3)
    verification_engine = VerificationEngine()

    exact_params = NEAR_OPTIMAL_PARAMS.copy()

    slightly_off = DEFAULT_PARAMS.copy()
    slightly_off["wall_r_value"] = 4.5
    slightly_off["hvac_cop"] = 4.0

    far_off = DEFAULT_PARAMS.copy()
    far_off["wall_r_value"] = 9.0
    far_off["zone_capacitance"] = 450000.0
    far_off["infiltration_ach"] = 1.8

    submissions = {
        0: {"calibrated_params": exact_params, "simulations_used": 100},
        1: {"calibrated_params": slightly_off, "simulations_used": 200},
        2: {"calibrated_params": far_off, "simulations_used": 500},
    }

    result = await _run_round(orchestrator, scoring_engine, ema, verification_engine, submissions, "round-0")

    scores = result["scores"]
    assert scores[0] > scores[1], f"Miner 0 ({scores[0]:.4f}) should beat Miner 1 ({scores[1]:.4f})"
    assert scores[1] > scores[2], f"Miner 1 ({scores[1]:.4f}) should beat Miner 2 ({scores[2]:.4f})"
    assert set(scores.keys()) == {0, 1, 2}


@pytest.mark.asyncio
async def test_two_rounds_ema() -> None:
    """EMA smoothing changes weights between rounds."""
    orchestrator = RoundOrchestrator(manifest_path=MANIFEST_PATH)
    scoring_engine = ScoringEngine()
    ema = EMATracker(alpha=0.3)
    verification_engine = VerificationEngine()

    miner1_params = DEFAULT_PARAMS.copy()
    miner1_params["wall_r_value"] = 4.0

    submissions = {
        0: {"calibrated_params": NEAR_OPTIMAL_PARAMS, "simulations_used": 100},
        1: {"calibrated_params": miner1_params, "simulations_used": 100},
    }

    result1 = await _run_round(orchestrator, scoring_engine, ema, verification_engine, submissions, "round-0")
    weights_after_r1 = result1["weights"].copy()

    result2 = await _run_round(orchestrator, scoring_engine, ema, verification_engine, submissions, "round-1")
    weights_after_r2 = result2["weights"].copy()

    assert 0 in weights_after_r1 and 1 in weights_after_r1
    assert 0 in weights_after_r2 and 1 in weights_after_r2

    total_r2 = sum(weights_after_r2.values())
    assert abs(total_r2 - 1.0) < 1e-9, f"Weights should sum to 1.0, got {total_r2}"


@pytest.mark.asyncio
async def test_breakdown_format() -> None:
    """Score breakdown JSON has all expected fields."""
    orchestrator = RoundOrchestrator(manifest_path=MANIFEST_PATH)
    scoring_engine = ScoringEngine()
    ema = EMATracker(alpha=0.3)
    verification_engine = VerificationEngine()

    submissions = {
        0: {"calibrated_params": NEAR_OPTIMAL_PARAMS, "simulations_used": 150},
    }

    result = await _run_round(orchestrator, scoring_engine, ema, verification_engine, submissions, "round-0")
    breakdowns = result["breakdowns"]

    assert 0 in breakdowns
    bd = breakdowns[0]

    assert "round_id" in bd
    assert "miner_uid" in bd
    assert bd["miner_uid"] == 0
    assert "status" in bd
    assert bd["status"] == "verified"
    assert "metrics" in bd
    assert "cvrmse" in bd["metrics"]
    assert "nmbe" in bd["metrics"]
    assert "r_squared" in bd["metrics"]
    assert "component_scores" in bd
    assert "cvrmse" in bd["component_scores"]
    assert "nmbe" in bd["component_scores"]
    assert "r_squared" in bd["component_scores"]
    assert "convergence" in bd["component_scores"]
    assert "composite_score" in bd
    assert "final_weight" in bd
    assert "calibrated_params" in bd

    cvrmse_component = bd["component_scores"]["cvrmse"]
    assert "raw" in cvrmse_component
    assert "threshold" in cvrmse_component
    assert "normalized" in cvrmse_component
    assert "weight" in cvrmse_component
    assert "contribution" in cvrmse_component
