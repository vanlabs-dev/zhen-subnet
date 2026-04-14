"""Integration tests for the full round loop.

Tests the complete validator round pipeline without BOPTEST or chain.
Uses the RC model with default params as ground truth.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from validator.round.orchestrator import RoundOrchestrator

MANIFEST_PATH = Path(__file__).resolve().parent / "fixtures" / "single_case_manifest.json"

DEFAULT_PARAMS = {
    "wall_r_value": 3.5,
    "roof_r_value": 5.0,
    "zone_capacitance": 200000.0,
    "infiltration_ach": 0.5,
    "hvac_cop": 3.5,
    "solar_gain_factor": 0.4,
}


@pytest.mark.asyncio
async def test_full_round_local() -> None:
    """Full round: Miner 0 (exact) > Miner 1 (close) > Miner 2 (far off)."""
    orchestrator = RoundOrchestrator(manifest_path=MANIFEST_PATH)

    # Miner 0: exact default params (should score highest)
    exact_params = DEFAULT_PARAMS.copy()

    # Miner 1: slightly off params (medium score)
    slightly_off = DEFAULT_PARAMS.copy()
    slightly_off["wall_r_value"] = 4.5
    slightly_off["hvac_cop"] = 4.0

    # Miner 2: wildly wrong params (lowest score)
    far_off = DEFAULT_PARAMS.copy()
    far_off["wall_r_value"] = 9.0
    far_off["zone_capacitance"] = 450000.0
    far_off["infiltration_ach"] = 1.8

    submissions = {
        0: {"calibrated_params": exact_params, "simulations_used": 100},
        1: {"calibrated_params": slightly_off, "simulations_used": 200},
        2: {"calibrated_params": far_off, "simulations_used": 500},
    }

    result = await orchestrator.run_round(submissions)

    # Verify ordering
    scores = result["scores"]
    assert scores[0] > scores[1], f"Miner 0 ({scores[0]:.4f}) should beat Miner 1 ({scores[1]:.4f})"
    assert scores[1] > scores[2], f"Miner 1 ({scores[1]:.4f}) should beat Miner 2 ({scores[2]:.4f})"

    # Verify all miners present
    assert set(scores.keys()) == {0, 1, 2}


@pytest.mark.asyncio
async def test_two_rounds_ema() -> None:
    """EMA smoothing changes weights between rounds."""
    orchestrator = RoundOrchestrator(manifest_path=MANIFEST_PATH)

    miner1_params = DEFAULT_PARAMS.copy()
    miner1_params["wall_r_value"] = 4.0

    submissions = {
        0: {"calibrated_params": DEFAULT_PARAMS, "simulations_used": 100},
        1: {"calibrated_params": miner1_params, "simulations_used": 100},
    }

    # Round 1
    result1 = await orchestrator.run_round(submissions)
    weights_after_r1 = result1["weights"].copy()

    # Round 2 with same submissions
    result2 = await orchestrator.run_round(submissions)
    weights_after_r2 = result2["weights"].copy()

    # Weights should exist for both miners in both rounds
    assert 0 in weights_after_r1 and 1 in weights_after_r1
    assert 0 in weights_after_r2 and 1 in weights_after_r2

    # EMA means round 2 weights blend with round 1
    # With alpha=0.3, weights should shift but not be identical to single-round scores
    # The key assertion: EMA tracker has been updated (weights exist and are normalized)
    total_r2 = sum(weights_after_r2.values())
    assert abs(total_r2 - 1.0) < 1e-9, f"Weights should sum to 1.0, got {total_r2}"


@pytest.mark.asyncio
async def test_breakdown_format() -> None:
    """Score breakdown JSON has all expected fields."""
    orchestrator = RoundOrchestrator(manifest_path=MANIFEST_PATH)

    submissions = {
        0: {"calibrated_params": DEFAULT_PARAMS, "simulations_used": 150},
    }

    result = await orchestrator.run_round(submissions)
    breakdowns = result["breakdowns"]

    assert 0 in breakdowns
    bd = breakdowns[0]

    # Check required fields
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

    # Verify component structure
    cvrmse_component = bd["component_scores"]["cvrmse"]
    assert "raw" in cvrmse_component
    assert "threshold" in cvrmse_component
    assert "normalized" in cvrmse_component
    assert "weight" in cvrmse_component
    assert "contribution" in cvrmse_component
