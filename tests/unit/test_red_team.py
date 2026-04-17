"""Tests derived from red team attack scenarios.

Each test encodes a specific attack the scoring and verification pipeline
must defeat: convergence gaming via fabricated simulations_used values,
non-finite metric injection, exceeding the self-reported budget,
state-file tampering, and malformed response payloads.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pytest

from protocol.synapse import CalibrationSynapse
from scoring.engine import ScoringEngine, VerifiedResult
from validator.network.result_receiver import ResponseParser
from validator.state import load_state, save_state
from validator.verification.engine import VerificationEngine

TEST_CASE: dict[str, Any] = {
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

# 5% off defaults so the anti-default check lets verification proceed.
NEAR_DEFAULT_PARAMS = {
    "wall_r_value": 3.5 * 1.05,
    "roof_r_value": 5.0 * 1.05,
    "zone_capacitance": 200000.0 * 1.05,
    "infiltration_ach": 0.5 * 1.05,
    "hvac_cop": 3.5 * 1.05,
    "solar_gain_factor": 0.4 * 1.05,
}

TEST_PERIOD = (336, 504)


def _make_held_out_data() -> dict[str, list[float]]:
    """Generate ground truth from the RC model with default params."""
    import json
    from pathlib import Path

    from simulation.rc_network import RCNetworkBackend

    config_path = Path.home() / ".zhen" / "test_cases" / "bestest_hydronic_heat_pump" / "config.json"
    config = json.loads(config_path.read_text())
    rc = RCNetworkBackend(config, TEST_CASE["defaults"])
    result = rc.run(start_hour=TEST_PERIOD[0], end_hour=TEST_PERIOD[1])
    return result.get_outputs(TEST_CASE["scoring_outputs"])


@pytest.mark.asyncio
async def test_negative_simulations_clamped() -> None:
    """Attack: report simulations_used = -100 to inflate convergence score.

    Verification must clamp to 0 before the convergence component is computed.
    """
    engine = VerificationEngine()
    held_out = _make_held_out_data()

    submissions = {
        0: {"calibrated_params": NEAR_DEFAULT_PARAMS, "simulations_used": -100},
    }

    verified = await engine.verify_all(submissions, TEST_CASE, TEST_PERIOD, held_out)
    assert verified[0].reason == ""
    assert verified[0].simulations_used == 0


@pytest.mark.asyncio
async def test_simulations_used_capped_at_budget() -> None:
    """Attack: report simulations_used = 1e9 to corrupt downstream math.

    Verification must cap at simulation_budget so downstream normalization
    stays in [0, 1].
    """
    engine = VerificationEngine()
    held_out = _make_held_out_data()

    submissions = {
        0: {"calibrated_params": NEAR_DEFAULT_PARAMS, "simulations_used": 10**9},
    }

    verified = await engine.verify_all(submissions, TEST_CASE, TEST_PERIOD, held_out)
    assert verified[0].reason == ""
    assert verified[0].simulations_used == TEST_CASE["simulation_budget"]


def test_nan_metric_scores_zero() -> None:
    """Attack: a VerifiedResult with NaN CVRMSE must not earn weight from NMBE/R2/convergence."""
    engine = ScoringEngine()
    nan_result = VerifiedResult(
        cvrmse=float("nan"),
        nmbe=0.01,
        r_squared=0.9,
        simulations_used=200,
    )
    composite = engine._compute_composite(nan_result, sim_budget=1000)
    assert composite == 0.0


def test_inf_metric_scores_zero() -> None:
    """Attack: Inf in any metric must zero the composite."""
    engine = ScoringEngine()
    for bad in (
        VerifiedResult(cvrmse=float("inf"), nmbe=0.01, r_squared=0.9, simulations_used=200),
        VerifiedResult(cvrmse=0.1, nmbe=float("nan"), r_squared=0.9, simulations_used=200),
        VerifiedResult(cvrmse=0.1, nmbe=0.01, r_squared=float("-inf"), simulations_used=200),
    ):
        assert engine._compute_composite(bad, sim_budget=1000) == 0.0


def test_convergence_gaming_bounded() -> None:
    """Attack: lie about simulations_used to farm the convergence component.

    The convergence weight is 10%, so the maximum gain from reporting
    simulations_used = 0 vs any honest value is 0.10 of the raw composite.
    """
    engine = ScoringEngine()

    honest = VerifiedResult(cvrmse=0.1, nmbe=0.02, r_squared=0.9, simulations_used=500)
    liar = VerifiedResult(cvrmse=0.1, nmbe=0.02, r_squared=0.9, simulations_used=0)
    max_budget_user = VerifiedResult(cvrmse=0.1, nmbe=0.02, r_squared=0.9, simulations_used=1000)

    honest_score = engine._compute_composite(honest, sim_budget=1000)
    liar_score = engine._compute_composite(liar, sim_budget=1000)
    max_budget_score = engine._compute_composite(max_budget_user, sim_budget=1000)

    # The cheat cannot earn more than one convergence weight above honest play.
    assert liar_score - honest_score <= engine.WEIGHTS["convergence"] + 1e-9
    # And at most one convergence weight above a miner who burned the full budget.
    assert liar_score - max_budget_score <= engine.WEIGHTS["convergence"] + 1e-9
    # Sanity: liar strictly beats max-budget-user by the convergence spread.
    assert math.isclose(liar_score - max_budget_score, engine.WEIGHTS["convergence"], abs_tol=1e-9)


def test_state_rejects_inflated_ema(tmp_path: Path) -> None:
    """Attack: tamper with state file to inflate EMA score above 1.0.

    Normalized EMA scores live in [0, 1]; load_state must reject anything outside
    that range so a poisoned file cannot pre-load a miner with overweight history.
    """
    state_path = tmp_path / "state.json"
    save_state(round_count=1, ema_scores={1: 2.5}, round_id="round-0", state_path=state_path)
    assert load_state(state_path=state_path) is None


def test_state_rejects_negative_ema(tmp_path: Path) -> None:
    """Negative EMA scores are also out of range and must be refused on load."""
    state_path = tmp_path / "state.json"
    save_state(round_count=1, ema_scores={1: -0.1}, round_id="round-0", state_path=state_path)
    assert load_state(state_path=state_path) is None


def test_parser_rejects_list_params() -> None:
    """Attack: send calibrated_params as a list to crash the verification engine."""
    parser = ResponseParser()
    response = CalibrationSynapse()
    response.calibrated_params = [1.0, 2.0, 3.0]  # type: ignore[assignment]
    response.simulations_used = 100

    submissions = parser.parse_responses([response], uids=[7])
    assert 7 not in submissions


def test_parser_rejects_string_params() -> None:
    """Attack: send calibrated_params as a string to crash the verification engine."""
    parser = ResponseParser()
    response = CalibrationSynapse()
    response.calibrated_params = "not a dict"  # type: ignore[assignment]
    response.simulations_used = 100

    submissions = parser.parse_responses([response], uids=[7])
    assert 7 not in submissions
