"""Unit tests for the miner calibration components.

Tests the objective function, Bayesian calibrator, and calibration engine.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from miner.calibration import CalibrationOutput
from miner.calibration.bayesian import BayesianCalibrator
from miner.calibration.engine import CalibrationEngine
from miner.calibration.objective import CalibrationObjective
from simulation.rc_network import RCNetworkBackend

TEST_CASE_ID = "bestest_hydronic_heat_pump"
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
TRAIN_START = 0
TRAIN_END = 336
SCORING_OUTPUTS = ["zone_air_temperature_C", "total_heating_energy_kWh"]


def _make_training_data() -> dict[str, list[float]]:
    """Generate training data from RC model with default params."""
    config_path = Path.home() / ".zhen" / "test_cases" / TEST_CASE_ID / "config.json"
    config = json.loads(config_path.read_text())
    rc = RCNetworkBackend(config, DEFAULT_PARAMS)
    result = rc.run(start_hour=TRAIN_START, end_hour=TRAIN_END)
    return result.get_outputs(SCORING_OUTPUTS)


def test_objective_function() -> None:
    """Objective returns a float CVRMSE value."""
    training_data = _make_training_data()
    objective = CalibrationObjective(
        test_case_id=TEST_CASE_ID,
        train_start=TRAIN_START,
        train_end=TRAIN_END,
        training_data=training_data,
        scoring_outputs=SCORING_OUTPUTS,
    )
    # Evaluate with default params (should give ~0.0 CVRMSE)
    values = [DEFAULT_PARAMS[name] for name in PARAM_NAMES]
    cvrmse = objective(values, PARAM_NAMES)
    assert isinstance(cvrmse, float)
    assert cvrmse < 0.01  # Near-perfect match


def test_objective_crash_handling() -> None:
    """Params that cause simulation issues return a value, never crash."""
    training_data = _make_training_data()
    objective = CalibrationObjective(
        test_case_id=TEST_CASE_ID,
        train_start=TRAIN_START,
        train_end=TRAIN_END,
        training_data=training_data,
        scoring_outputs=SCORING_OUTPUTS,
    )
    # Extreme values that stress the model
    bad_values = [0.5, 0.5, 50000.0, 2.0, 1.5, 1.0]
    result = objective(bad_values, PARAM_NAMES)
    # Must return a finite float, never crash
    assert isinstance(result, float)
    assert result >= 0.0
    # Bad params should produce worse CVRMSE than defaults
    good_values = [DEFAULT_PARAMS[name] for name in PARAM_NAMES]
    good_result = objective(good_values, PARAM_NAMES)
    assert result > good_result


def test_objective_sim_count() -> None:
    """Sim count increments with each call."""
    training_data = _make_training_data()
    objective = CalibrationObjective(
        test_case_id=TEST_CASE_ID,
        train_start=TRAIN_START,
        train_end=TRAIN_END,
        training_data=training_data,
        scoring_outputs=SCORING_OUTPUTS,
    )
    values = [DEFAULT_PARAMS[name] for name in PARAM_NAMES]
    for _ in range(5):
        objective(values, PARAM_NAMES)
    assert objective.sim_count == 5


def test_bayesian_calibrator_runs() -> None:
    """BayesianCalibrator with n_calls=10 returns valid CalibrationOutput."""
    training_data = _make_training_data()
    calibrator = BayesianCalibrator(n_calls=10, n_initial_points=5, random_state=42)
    output = calibrator.calibrate(
        test_case_id=TEST_CASE_ID,
        training_data=training_data,
        parameter_names=PARAM_NAMES,
        parameter_bounds=PARAM_BOUNDS,
        simulation_budget=1000,
        train_start=TRAIN_START,
        train_end=TRAIN_END,
        scoring_outputs=SCORING_OUTPUTS,
    )
    assert isinstance(output, CalibrationOutput)
    assert len(output.calibrated_params) == 6
    assert output.simulations_used >= 10
    assert output.training_cvrmse >= 0.0
    assert "algorithm" in output.metadata


def test_bayesian_calibrator_improves() -> None:
    """With n_calls=50, calibrator achieves better CVRMSE than random."""
    training_data = _make_training_data()

    # Get a random guess CVRMSE (midpoint of bounds)
    objective = CalibrationObjective(
        test_case_id=TEST_CASE_ID,
        train_start=TRAIN_START,
        train_end=TRAIN_END,
        training_data=training_data,
        scoring_outputs=SCORING_OUTPUTS,
    )
    midpoint_values = [(PARAM_BOUNDS[n][0] + PARAM_BOUNDS[n][1]) / 2 for n in PARAM_NAMES]
    random_cvrmse = objective(midpoint_values, PARAM_NAMES)

    # Run calibrator
    calibrator = BayesianCalibrator(n_calls=50, n_initial_points=10, random_state=42)
    output = calibrator.calibrate(
        test_case_id=TEST_CASE_ID,
        training_data=training_data,
        parameter_names=PARAM_NAMES,
        parameter_bounds=PARAM_BOUNDS,
        simulation_budget=1000,
        train_start=TRAIN_START,
        train_end=TRAIN_END,
        scoring_outputs=SCORING_OUTPUTS,
    )
    assert output.training_cvrmse < random_cvrmse


@pytest.mark.asyncio
async def test_calibration_engine_dispatch() -> None:
    """CalibrationEngine dispatches to BayesianCalibrator and returns output."""
    training_data = _make_training_data()
    engine = CalibrationEngine(algorithm="bayesian", random_state=42)

    challenge = {
        "test_case_id": TEST_CASE_ID,
        "training_data": training_data,
        "parameter_names": PARAM_NAMES,
        "parameter_bounds": PARAM_BOUNDS,
        "simulation_budget": 15,
        "train_start_hour": TRAIN_START,
        "train_end_hour": TRAIN_END,
    }

    output = await engine.calibrate(challenge)
    assert isinstance(output, CalibrationOutput)
    assert len(output.calibrated_params) == 6
    assert output.simulations_used > 0
