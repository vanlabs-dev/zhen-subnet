"""Unit tests for the verification engine.

Tests parameter validation, scoring differentiation, and timeout handling.
"""

from __future__ import annotations

import asyncio
import math
from unittest.mock import patch

import pytest

from simulation.rc_network import SimulationResult
from validator.scoring.engine import VerifiedResult
from validator.verification.engine import VerificationEngine

TEST_CASE = {
    "id": "bestest_hydronic_heat_pump",
    "parameter_bounds": {
        "wall_r_value": [0.5, 10.0],
        "roof_r_value": [0.5, 12.0],
        "zone_capacitance": [50000.0, 500000.0],
        "infiltration_ach": [0.1, 2.0],
        "hvac_cop": [1.5, 6.0],
        "solar_gain_factor": [0.0, 1.0],
    },
    "scoring_outputs": ["zone_air_temperature_C", "total_heating_energy_kWh"],
    "simulation_budget": 1000,
    "defaults": {
        "wall_r_value": 3.5,
        "roof_r_value": 5.0,
        "zone_capacitance": 200000.0,
        "infiltration_ach": 0.5,
        "hvac_cop": 3.5,
        "solar_gain_factor": 0.4,
    },
}

DEFAULT_PARAMS = {
    "wall_r_value": 3.5,
    "roof_r_value": 5.0,
    "zone_capacitance": 200000.0,
    "infiltration_ach": 0.5,
    "hvac_cop": 3.5,
    "solar_gain_factor": 0.4,
}

TEST_PERIOD = (336, 504)  # 168 hours after training


def _make_held_out_data() -> dict[str, list[float]]:
    """Generate ground truth from RC model with default params."""
    import json
    from pathlib import Path

    from simulation.rc_network import RCNetworkBackend

    config_path = Path.home() / ".zhen" / "test_cases" / "bestest_hydronic_heat_pump" / "config.json"
    config = json.loads(config_path.read_text())
    rc = RCNetworkBackend(config, DEFAULT_PARAMS)
    result = rc.run(start_hour=TEST_PERIOD[0], end_hour=TEST_PERIOD[1])
    return result.get_outputs(["zone_air_temperature_C", "total_heating_energy_kWh"])


NEAR_DEFAULT_PARAMS = {
    "wall_r_value": 3.5 * 1.05,
    "roof_r_value": 5.0 * 1.05,
    "zone_capacitance": 200000.0 * 1.05,
    "infiltration_ach": 0.5 * 1.05,
    "hvac_cop": 3.5 * 1.05,
    "solar_gain_factor": 0.4 * 1.05,
}


@pytest.mark.asyncio
async def test_verify_valid_params() -> None:
    """Valid params within bounds should produce scores (not fail)."""
    engine = VerificationEngine()
    held_out = _make_held_out_data()

    submissions = {
        0: {"calibrated_params": NEAR_DEFAULT_PARAMS, "simulations_used": 100},
    }

    verified = await engine.verify_all(submissions, TEST_CASE, TEST_PERIOD, held_out)
    assert 0 in verified
    v = verified[0]
    assert v.reason == ""
    # Close to defaults should have low CVRMSE
    assert v.cvrmse < 0.5


@pytest.mark.asyncio
async def test_verify_out_of_bounds() -> None:
    """Params outside bounds should get INVALID_PARAMS."""
    engine = VerificationEngine()
    held_out = _make_held_out_data()

    bad_params = DEFAULT_PARAMS.copy()
    bad_params["wall_r_value"] = 999.0  # Way outside [0.5, 10.0]

    submissions = {
        0: {"calibrated_params": bad_params, "simulations_used": 50},
    }

    verified = await engine.verify_all(submissions, TEST_CASE, TEST_PERIOD, held_out)
    assert 0 in verified
    assert verified[0].reason == "INVALID_PARAMS"
    assert "wall_r_value" in verified[0].detail


@pytest.mark.asyncio
async def test_verify_multiple_miners() -> None:
    """Three miners with different params should get differentiated scores."""
    engine = VerificationEngine()
    held_out = _make_held_out_data()

    # Miner 0: near defaults (best, passes anti-gaming check at 5% off)
    # Miner 1: moderately off
    # Miner 2: far off but within bounds
    slightly_off = DEFAULT_PARAMS.copy()
    slightly_off["wall_r_value"] = 4.5
    slightly_off["hvac_cop"] = 4.0

    far_off = DEFAULT_PARAMS.copy()
    far_off["wall_r_value"] = 9.0
    far_off["zone_capacitance"] = 450000.0
    far_off["infiltration_ach"] = 1.8

    submissions = {
        0: {"calibrated_params": NEAR_DEFAULT_PARAMS, "simulations_used": 100},
        1: {"calibrated_params": slightly_off, "simulations_used": 200},
        2: {"calibrated_params": far_off, "simulations_used": 500},
    }

    verified = await engine.verify_all(submissions, TEST_CASE, TEST_PERIOD, held_out)
    assert len(verified) == 3

    # All should have passed verification (no DEFAULT_PARAMS rejection)
    for uid in [0, 1, 2]:
        assert verified[uid].reason == "", f"Miner {uid} rejected: {verified[uid].reason}"

    # Miner 0 should have best CVRMSE (lowest)
    assert verified[0].cvrmse < verified[1].cvrmse
    assert verified[1].cvrmse < verified[2].cvrmse


@pytest.mark.asyncio
async def test_rejects_exact_defaults() -> None:
    """Submitting exact default params should be rejected as DEFAULT_PARAMS."""
    engine = VerificationEngine()

    submissions = {
        0: {"calibrated_params": DEFAULT_PARAMS.copy(), "simulations_used": 100},
    }

    # held_out_data doesn't matter since rejection happens before simulation
    held_out: dict[str, list[float]] = {"zone_air_temperature_C": [], "total_heating_energy_kWh": []}
    verified = await engine.verify_all(submissions, TEST_CASE, TEST_PERIOD, held_out)
    assert 0 in verified
    assert verified[0].reason == "DEFAULT_PARAMS"


@pytest.mark.asyncio
async def test_rejects_near_defaults() -> None:
    """Params within 0.1% of defaults should be rejected."""
    engine = VerificationEngine()

    near_defaults = DEFAULT_PARAMS.copy()
    # Add tiny perturbation (0.01% = well within 0.1% threshold)
    near_defaults["wall_r_value"] = 3.5 * 1.0001
    near_defaults["hvac_cop"] = 3.5 * 0.9999

    submissions = {
        0: {"calibrated_params": near_defaults, "simulations_used": 50},
    }

    held_out: dict[str, list[float]] = {"zone_air_temperature_C": [], "total_heating_energy_kWh": []}
    verified = await engine.verify_all(submissions, TEST_CASE, TEST_PERIOD, held_out)
    assert 0 in verified
    assert verified[0].reason == "DEFAULT_PARAMS"


@pytest.mark.asyncio
async def test_accepts_different_params() -> None:
    """Params 5% different from defaults should be accepted (not rejected)."""
    engine = VerificationEngine()
    held_out = _make_held_out_data()

    different_params = DEFAULT_PARAMS.copy()
    different_params["wall_r_value"] = 3.5 * 1.05  # 5% higher
    different_params["hvac_cop"] = 3.5 * 0.95  # 5% lower

    submissions = {
        0: {"calibrated_params": different_params, "simulations_used": 100},
    }

    verified = await engine.verify_all(submissions, TEST_CASE, TEST_PERIOD, held_out)
    assert 0 in verified
    # Should NOT be rejected as DEFAULT_PARAMS
    assert verified[0].reason != "DEFAULT_PARAMS"


@pytest.mark.asyncio
async def test_accepts_when_no_defaults() -> None:
    """If test_case has no defaults key, skip the check."""
    engine = VerificationEngine()

    test_case_no_defaults = {
        "id": "bestest_hydronic_heat_pump",
        "parameter_bounds": TEST_CASE["parameter_bounds"],
        "scoring_outputs": TEST_CASE["scoring_outputs"],
        "simulation_budget": 1000,
        # No "defaults" key
    }

    held_out = _make_held_out_data()
    submissions = {
        0: {"calibrated_params": DEFAULT_PARAMS.copy(), "simulations_used": 100},
    }

    verified = await engine.verify_all(submissions, test_case_no_defaults, TEST_PERIOD, held_out)
    assert 0 in verified
    # Without defaults in test_case, should NOT be rejected as DEFAULT_PARAMS
    assert verified[0].reason != "DEFAULT_PARAMS"


@pytest.mark.asyncio
async def test_verify_timeout() -> None:
    """Slow simulation should trigger SIMULATION_TIMEOUT."""
    engine = VerificationEngine(timeout_seconds=1)

    # Monkey-patch _verify_single to sleep
    original = engine._verify_single

    async def slow_verify(*args: object, **kwargs: object) -> VerifiedResult:
        """Simulate a very slow verification."""
        await asyncio.sleep(10)
        return await original(*args, **kwargs)  # type: ignore[arg-type]

    engine._verify_single = slow_verify  # type: ignore[method-assign]

    held_out = _make_held_out_data()
    submissions = {
        0: {"calibrated_params": DEFAULT_PARAMS, "simulations_used": 100},
    }

    verified = await engine.verify_all(submissions, TEST_CASE, TEST_PERIOD, held_out)
    assert 0 in verified
    assert verified[0].reason == "SIMULATION_TIMEOUT"


@pytest.mark.asyncio
async def test_rejects_nan_simulation_output() -> None:
    """Submissions producing NaN/Inf in the RC model should be rejected."""
    engine = VerificationEngine()

    nan_result = SimulationResult(outputs={
        "zone_air_temperature_C": [20.0, float("nan"), 21.0],
        "total_heating_energy_kWh": [1.0, 2.0, 3.0],
    })

    submissions = {
        0: {"calibrated_params": NEAR_DEFAULT_PARAMS, "simulations_used": 100},
    }

    held_out: dict[str, list[float]] = {
        "zone_air_temperature_C": [20.0, 21.0, 22.0],
        "total_heating_energy_kWh": [1.0, 2.0, 3.0],
    }

    with patch.object(
        engine, "_load_config", return_value={}
    ), patch(
        "validator.verification.engine.RCNetworkBackend"
    ) as mock_rc_cls:
        mock_rc_cls.return_value.run.return_value = nan_result
        verified = await engine.verify_all(submissions, TEST_CASE, TEST_PERIOD, held_out)

    assert 0 in verified
    assert verified[0].reason == "SIMULATION_NAN"
    assert "zone_air_temperature_C" in verified[0].detail


@pytest.mark.asyncio
async def test_rejects_inf_simulation_output() -> None:
    """Submissions producing Inf in the RC model should be rejected."""
    engine = VerificationEngine()

    inf_result = SimulationResult(outputs={
        "zone_air_temperature_C": [20.0, 21.0, 22.0],
        "total_heating_energy_kWh": [1.0, math.inf, 3.0],
    })

    submissions = {
        0: {"calibrated_params": NEAR_DEFAULT_PARAMS, "simulations_used": 100},
    }

    held_out: dict[str, list[float]] = {
        "zone_air_temperature_C": [20.0, 21.0, 22.0],
        "total_heating_energy_kWh": [1.0, 2.0, 3.0],
    }

    with patch.object(
        engine, "_load_config", return_value={}
    ), patch(
        "validator.verification.engine.RCNetworkBackend"
    ) as mock_rc_cls:
        mock_rc_cls.return_value.run.return_value = inf_result
        verified = await engine.verify_all(submissions, TEST_CASE, TEST_PERIOD, held_out)

    assert 0 in verified
    assert verified[0].reason == "SIMULATION_NAN"
    assert "total_heating_energy_kWh" in verified[0].detail
