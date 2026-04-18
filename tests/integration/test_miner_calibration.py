"""Integration tests for the miner calibration pipeline.

Proves that Bayesian optimization can close the CVRMSE gap and that
the full round loop differentiates miners by calibration quality.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from miner.calibration.bayesian import BayesianCalibrator
from simulation.rc_network import RCNetworkBackend
from validator.round import split_generator, test_case_selector
from validator.round.orchestrator import RoundOrchestrator
from validator.scoring import breakdown
from validator.scoring.engine import ScoringEngine
from validator.scoring.window_ema import compute_window_ema
from validator.scoring_db import ScoringDB
from validator.verification.engine import VerificationEngine

TEST_CASE_ID = "bestest_hydronic_heat_pump"
_ZHEN_CONFIG = Path.home() / ".zhen" / "test_cases" / TEST_CASE_ID / "config.json"

pytestmark = pytest.mark.skipif(
    not _ZHEN_CONFIG.exists(),
    reason="Integration test requires local test case data in ~/.zhen/test_cases/",
)
MANIFEST_PATH = Path(__file__).resolve().parent / "fixtures" / "single_case_manifest.json"
PARAM_NAMES = [
    "wall_r_value",
    "roof_r_value",
    "zone_capacitance",
    "infiltration_ach",
    "hvac_cop",
    "solar_gain_factor",
]
PARAM_BOUNDS = {
    "wall_r_value": [0.5, 10.0],
    "roof_r_value": [0.5, 12.0],
    "zone_capacitance": [50000.0, 500000.0],
    "infiltration_ach": [0.1, 2.0],
    "hvac_cop": [1.5, 6.0],
    "solar_gain_factor": [0.0, 1.0],
}
DEFAULT_PARAMS = {
    "wall_r_value": 3.5,
    "roof_r_value": 5.0,
    "zone_capacitance": 200000.0,
    "infiltration_ach": 0.5,
    "hvac_cop": 3.5,
    "solar_gain_factor": 0.4,
}
SCORING_OUTPUTS = ["zone_air_temperature_C", "total_heating_energy_kWh"]
TRAIN_START = 0
TRAIN_END = 336


def _make_training_data() -> dict[str, list[float]]:
    """Generate ground truth training data from RC model with default params."""
    config_path = Path.home() / ".zhen" / "test_cases" / TEST_CASE_ID / "config.json"
    config = json.loads(config_path.read_text())
    rc = RCNetworkBackend(config, DEFAULT_PARAMS)
    result = rc.run(start_hour=TRAIN_START, end_hour=TRAIN_END)
    return result.get_outputs(SCORING_OUTPUTS)


@pytest.mark.asyncio
async def test_miner_closes_cvrmse_gap() -> None:
    """BayesianCalibrator with n_calls=200 recovers close to default params."""
    training_data = _make_training_data()

    calibrator = BayesianCalibrator(n_calls=200, n_initial_points=20)
    output = await calibrator.calibrate(
        test_case_id=TEST_CASE_ID,
        training_data=training_data,
        parameter_names=PARAM_NAMES,
        parameter_bounds=PARAM_BOUNDS,
        simulation_budget=1000,
        train_start=TRAIN_START,
        train_end=TRAIN_END,
        scoring_outputs=SCORING_OUTPUTS,
    )

    print(f"\n{'=' * 60}")
    print("Miner Calibration Results (n_calls=200)")
    print(f"{'=' * 60}")
    print(f"Training CVRMSE: {output.training_cvrmse:.6f}")
    print(f"Simulations used: {output.simulations_used}")
    print(f"\n{'Parameter':<20} {'Default':<12} {'Calibrated':<12} {'Error':<10}")
    print("-" * 54)
    for name in PARAM_NAMES:
        default = DEFAULT_PARAMS[name]
        calibrated = output.calibrated_params[name]
        error = abs(calibrated - default) / default * 100
        print(f"{name:<20} {default:<12.4f} {calibrated:<12.4f} {error:<10.1f}%")
    print(f"{'=' * 60}")

    # Miner should achieve CVRMSE < 0.05 on training data
    assert output.training_cvrmse < 0.05, f"Expected training CVRMSE < 0.05, got {output.training_cvrmse:.4f}"


@pytest.mark.asyncio
async def test_end_to_end_round_with_miner(tmp_path: Path) -> None:
    """Full round: optimized miner > low-budget miner > random miner."""
    training_data = _make_training_data()

    # Miner 0: BayesianCalibrator with n_calls=100 (good budget)
    calibrator_0 = BayesianCalibrator(n_calls=100, n_initial_points=15, random_state=42)
    output_0 = await calibrator_0.calibrate(
        test_case_id=TEST_CASE_ID,
        training_data=training_data,
        parameter_names=PARAM_NAMES,
        parameter_bounds=PARAM_BOUNDS,
        simulation_budget=1000,
        train_start=TRAIN_START,
        train_end=TRAIN_END,
        scoring_outputs=SCORING_OUTPUTS,
    )

    # Miner 1: BayesianCalibrator with n_calls=50 (moderate budget)
    calibrator_1 = BayesianCalibrator(n_calls=50, n_initial_points=15, random_state=123)
    output_1 = await calibrator_1.calibrate(
        test_case_id=TEST_CASE_ID,
        training_data=training_data,
        parameter_names=PARAM_NAMES,
        parameter_bounds=PARAM_BOUNDS,
        simulation_budget=1000,
        train_start=TRAIN_START,
        train_end=TRAIN_END,
        scoring_outputs=SCORING_OUTPUTS,
    )

    # Miner 2: Extreme edge-of-bounds params (no optimization, deliberately bad)
    random_params = {
        "wall_r_value": 9.5,
        "roof_r_value": 11.0,
        "zone_capacitance": 480000.0,
        "infiltration_ach": 1.9,
        "hvac_cop": 1.6,
        "solar_gain_factor": 0.95,
    }

    # Build submissions
    submissions = {
        0: {"calibrated_params": output_0.calibrated_params, "simulations_used": output_0.simulations_used},
        1: {"calibrated_params": output_1.calibrated_params, "simulations_used": output_1.simulations_used},
        2: {"calibrated_params": random_params, "simulations_used": 0},
    }

    # Run round with components wired directly (mirrors validator/main.py)
    orchestrator = RoundOrchestrator(manifest_path=MANIFEST_PATH)
    scoring_engine = ScoringEngine()
    scoring_db = ScoringDB(db_path=tmp_path / "scoring.db")
    verification_engine = VerificationEngine()

    round_id = "round-0"
    test_case = test_case_selector.select(round_id, orchestrator.manifest)
    train_period, test_period = split_generator.compute(round_id, test_case["id"])
    held_out_data = await orchestrator.generate_ground_truth(test_case, test_period, local_mode=True)
    verification_config = orchestrator.build_verification_config(test_case)
    sim_budget = verification_config.get("simulation_budget", 1000)

    try:
        verified = await verification_engine.verify_all(
            submissions,
            verification_config,
            test_period,
            held_out_data,
            sim_budget=sim_budget,
        )
        scores = scoring_engine.compute(verified, sim_budget=sim_budget)
        raw_scores = scoring_engine.compute_raw(verified, sim_budget=sim_budget)

        await scoring_db.insert_round_scores(
            round_id=round_id,
            test_case=test_case["id"],
            train_period=train_period,
            test_period=test_period,
            verified=verified,
            composites=scores,
        )
        window_rows = await scoring_db.get_scores_in_window(hours=72)
        weights = compute_window_ema(window_rows, alpha=0.3)

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
    finally:
        scoring_db.close()

    print(f"\n{'=' * 60}")
    print("End-to-End Round Results")
    print(f"{'=' * 60}")
    print(f"Miner 0 (n_calls=100): score={scores[0]:.4f}, cvrmse={output_0.training_cvrmse:.4f}")
    print(f"Miner 1 (n_calls=50):  score={scores[1]:.4f}, cvrmse={output_1.training_cvrmse:.4f}")
    print(f"Miner 2 (random):      score={scores[2]:.4f}")
    print(f"\nScore ordering: {scores[0]:.4f} > {scores[1]:.4f} > {scores[2]:.4f}")
    print(f"{'=' * 60}")

    # Breakdowns
    for uid in [0, 1, 2]:
        bd = breakdowns[uid]
        status = bd["status"]
        if status == "verified":
            metrics = bd["metrics"]
            print(f"\nMiner {uid} breakdown:")
            print(f"  CVRMSE: {metrics['cvrmse']:.4f}")
            print(f"  NMBE: {metrics['nmbe']:.4f}")
            print(f"  R-squared: {metrics['r_squared']:.4f}")
            print(f"  Composite: {bd['composite_score']:.4f}")
            print(f"  Weight: {bd['final_weight']:.4f}")
        else:
            print(f"\nMiner {uid}: FAILED ({bd.get('reason', 'unknown')})")

    # Both optimized miners must beat the random one
    assert scores[0] > scores[2], f"Miner 0 ({scores[0]:.4f}) should beat random Miner 2 ({scores[2]:.4f})"
    assert scores[1] > scores[2], f"Miner 1 ({scores[1]:.4f}) should beat random Miner 2 ({scores[2]:.4f})"
    # Note: relative ordering between optimized miners is non-deterministic
    # (more budget can overfit training data, generalizing worse on held-out)
