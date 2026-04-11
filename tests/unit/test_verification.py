"""Unit tests for the verification engine.

Tests parameter validation, scoring differentiation, and timeout handling.
"""

from __future__ import annotations

import asyncio

import pytest

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


@pytest.mark.asyncio
async def test_verify_valid_params() -> None:
    """Valid params within bounds should produce scores (not fail)."""
    engine = VerificationEngine()
    held_out = _make_held_out_data()

    submissions = {
        0: {"calibrated_params": DEFAULT_PARAMS, "simulations_used": 100},
    }

    verified = await engine.verify_all(submissions, TEST_CASE, TEST_PERIOD, held_out)
    assert 0 in verified
    v = verified[0]
    assert v.reason == ""
    # Perfect match should have low CVRMSE and high R-squared
    assert v.cvrmse < 0.01
    assert v.r_squared > 0.99


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

    # Miner 0: exact defaults (best)
    # Miner 1: slightly off
    # Miner 2: far off but within bounds
    slightly_off = DEFAULT_PARAMS.copy()
    slightly_off["wall_r_value"] = 4.5
    slightly_off["hvac_cop"] = 4.0

    far_off = DEFAULT_PARAMS.copy()
    far_off["wall_r_value"] = 9.0
    far_off["zone_capacitance"] = 450000.0
    far_off["infiltration_ach"] = 1.8

    submissions = {
        0: {"calibrated_params": DEFAULT_PARAMS, "simulations_used": 100},
        1: {"calibrated_params": slightly_off, "simulations_used": 200},
        2: {"calibrated_params": far_off, "simulations_used": 500},
    }

    verified = await engine.verify_all(submissions, TEST_CASE, TEST_PERIOD, held_out)
    assert len(verified) == 3

    # Miner 0 should have best CVRMSE (lowest)
    assert verified[0].cvrmse < verified[1].cvrmse
    assert verified[1].cvrmse < verified[2].cvrmse


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
