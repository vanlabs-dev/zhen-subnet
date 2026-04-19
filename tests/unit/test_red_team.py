"""Tests derived from red team attack scenarios.

Each test encodes a specific attack the scoring and verification pipeline
must defeat: convergence gaming via fabricated simulations_used values,
non-finite metric injection, exceeding the self-reported budget, and
malformed response payloads.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest

from miner.calibration.engine import CalibrationEngine
from protocol.synapse import CalibrationSynapse
from scoring.engine import ScoringEngine, VerifiedResult
from validator.network.result_receiver import ResponseParser
from validator.registry.manifest import ManifestError, ManifestLoader
from validator.round.orchestrator import validate_config_bounds
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


def test_sybil_attack_neutralized() -> None:
    """Attack: 49 garbage miners + 1 legit miner. Legit must keep >90% of weight.

    Garbage miners have composites near zero (failing CVRMSE/NMBE thresholds, all
    weight from convergence). The relative score floor zeros them out and the
    power-law amplifies the legit miner's share.
    """
    engine = ScoringEngine()
    legit = VerifiedResult(cvrmse=0.05, nmbe=0.02, r_squared=0.95, simulations_used=150)  # ~0.844
    garbage = VerifiedResult(cvrmse=0.30, nmbe=0.10, r_squared=0.0, simulations_used=750)  # ~0.025

    verified: dict[int, VerifiedResult] = {0: legit}
    for uid in range(1, 50):
        verified[uid] = garbage

    weights = engine.compute(verified)
    assert weights[0] > 0.90
    assert math.isclose(sum(weights.values()), 1.0, abs_tol=1e-9)


def test_score_floor_zeros_garbage() -> None:
    """Miners scoring below SCORE_FLOOR_RATIO of the top scorer get zero weight.

    Under spec v6 rank-based CVRMSE scoring, rank 2 of 2 still earns ~33% of
    the CVRMSE weight pool, so a "bad but ranked" miner no longer falls below
    the 5% floor via rank alone. Use a ceiling-exceeded CVRMSE on the garbage
    miner so its CVRMSE component is zero and the remaining NMBE/R2/convergence
    contributions stay below the floor.
    """
    engine = ScoringEngine()
    verified = {
        0: VerifiedResult(cvrmse=0.05, nmbe=0.02, r_squared=0.95, simulations_used=150),
        1: VerifiedResult(cvrmse=15.0, nmbe=0.10, r_squared=0.0, simulations_used=750),
    }

    raw = engine.compute_raw(verified)
    weights = engine.compute(verified)

    # The garbage miner's raw composite (NMBE/R2/convergence only; CVRMSE ceiling-rejected)
    # is below the floor.
    assert raw[1] < raw[0] * engine.SCORE_FLOOR_RATIO
    # ...so it earns zero weight even though it had a positive raw composite.
    assert weights[1] == 0.0
    assert math.isclose(weights[0], 1.0, abs_tol=1e-9)


def test_power_law_does_not_starve_tied_miners() -> None:
    """Tied CVRMSE values rank by stable sort (UID order), so the leading miner
    gets a strictly larger share than the trailing miner. Neither should be
    zeroed out by the floor or power-law, and the pair must sum to 1.0.

    Under spec v6, rank-based CVRMSE means "identical metrics" no longer
    guarantees equal weight; the tiebreak is deterministic. What still must
    hold is that both tied miners remain in the weight vector.
    """
    engine = ScoringEngine()
    verified = {
        0: VerifiedResult(cvrmse=0.10, nmbe=0.02, r_squared=0.85, simulations_used=200),
        1: VerifiedResult(cvrmse=0.10, nmbe=0.02, r_squared=0.85, simulations_used=200),
    }
    weights = engine.compute(verified)
    assert weights[0] > weights[1] > 0
    assert math.isclose(sum(weights.values()), 1.0, abs_tol=1e-9)


def test_power_law_amplifies_quality() -> None:
    """Power-law normalization gives the better miner more share than linear would.

    Constructs two close-but-distinct miners (neither floored) and verifies that
    the better one's weight under compute() exceeds what plain score / sum(scores)
    would produce.
    """
    engine = ScoringEngine()
    a = VerifiedResult(cvrmse=0.10, nmbe=0.02, r_squared=0.90, simulations_used=200)
    b = VerifiedResult(cvrmse=0.15, nmbe=0.04, r_squared=0.80, simulations_used=300)

    raw = engine.compute_raw({0: a, 1: b})
    weights = engine.compute({0: a, 1: b})

    # Neither miner should be floored in this scenario.
    assert weights[0] > 0 and weights[1] > 0

    # What linear normalization would have produced.
    linear_total = raw[0] + raw[1]
    linear_weight_a = raw[0] / linear_total

    # Power-law gives the better miner a strictly larger share than linear.
    assert weights[0] > linear_weight_a


# ---------------------------------------------------------------------------
# Miner input validation
# ---------------------------------------------------------------------------


_VALID_BOUNDS: dict[str, list[float]] = {
    "wall_r_value": [0.5, 10.0],
    "roof_r_value": [0.5, 12.0],
    "zone_capacitance": [50000.0, 500000.0],
    "infiltration_ach": [0.1, 2.0],
    "hvac_cop": [1.5, 6.0],
    "solar_gain_factor": [0.0, 1.0],
}
_VALID_PARAM_NAMES: list[str] = list(_VALID_BOUNDS.keys())


def _miner_challenge(**overrides: Any) -> dict[str, Any]:
    """Build a baseline challenge dict for miner-side validation tests."""
    base: dict[str, Any] = {
        "test_case_id": "bestest_hydronic_heat_pump",
        "training_data": {"zone_air_temperature_C": [20.0, 21.0, 22.0]},
        "parameter_names": _VALID_PARAM_NAMES,
        "parameter_bounds": _VALID_BOUNDS,
        "simulation_budget": 100,
        "train_start_hour": 0,
        "train_end_hour": 24,
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_miner_rejects_nan_training_data() -> None:
    """Attack: send NaN values in training_data to poison the optimizer."""
    engine = CalibrationEngine(algorithm="bayesian", n_calls=10)
    challenge = _miner_challenge(training_data={"zone_air_temperature_C": [20.0, float("nan"), 22.0]})
    with pytest.raises(ValueError, match="non-finite"):
        await engine.calibrate(challenge)


@pytest.mark.asyncio
async def test_miner_rejects_empty_training_data() -> None:
    """Attack: send an empty training_data dict to crash the miner."""
    engine = CalibrationEngine(algorithm="bayesian", n_calls=10)
    with pytest.raises(ValueError, match="empty"):
        await engine.calibrate(_miner_challenge(training_data={}))


@pytest.mark.asyncio
async def test_miner_rejects_inverted_bounds() -> None:
    """Attack: send parameter bounds with lo >= hi to crash skopt's Real()."""
    engine = CalibrationEngine(algorithm="bayesian", n_calls=10)
    bad_bounds = dict(_VALID_BOUNDS)
    bad_bounds["wall_r_value"] = [10.0, 0.5]
    with pytest.raises(ValueError, match="Invalid bounds"):
        await engine.calibrate(_miner_challenge(parameter_bounds=bad_bounds))


@pytest.mark.asyncio
async def test_miner_rejects_unknown_test_case() -> None:
    """Attack: reference a test case the miner has never seen, which would crash with FileNotFoundError."""
    engine = CalibrationEngine(algorithm="bayesian", n_calls=10)
    with pytest.raises(ValueError, match="Unknown test_case_id"):
        await engine.calibrate(_miner_challenge(test_case_id="nonexistent_test_case_12345"))


# ---------------------------------------------------------------------------
# Validator config / manifest validation
# ---------------------------------------------------------------------------


def test_manifest_rejects_duplicate_ids(tmp_path: Path) -> None:
    """A manifest with duplicate test_case ids must fail to load."""
    bad_manifest = {
        "version": "v1.0.0",
        "test_cases": [
            {
                "id": "duplicate",
                "simplified_model_type": "rc_network",
                "parameter_count": 1,
                "scoring_outputs": ["x"],
            },
            {
                "id": "duplicate",
                "simplified_model_type": "rc_network",
                "parameter_count": 1,
                "scoring_outputs": ["x"],
            },
        ],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(bad_manifest), encoding="utf-8")

    loader = ManifestLoader()
    with pytest.raises(ManifestError, match="Duplicate"):
        loader.load(manifest_path)


def test_config_rejects_inverted_bounds() -> None:
    """validate_config_bounds rejects [hi, lo] entries."""
    bad_config = {"parameter_bounds": {"x": [10.0, 0.5]}}
    with pytest.raises(ValueError, match="Inverted bounds"):
        validate_config_bounds(bad_config)


def test_config_rejects_non_finite_bounds() -> None:
    """validate_config_bounds rejects NaN/Inf bounds."""
    with pytest.raises(ValueError, match="Non-finite"):
        validate_config_bounds({"parameter_bounds": {"x": [0.0, float("inf")]}})


def test_config_rejects_malformed_bounds() -> None:
    """validate_config_bounds rejects bounds that aren't a [lo, hi] pair."""
    with pytest.raises(ValueError, match="Invalid bounds"):
        validate_config_bounds({"parameter_bounds": {"x": [1.0]}})
    with pytest.raises(ValueError, match="Invalid bounds"):
        validate_config_bounds({"parameter_bounds": {"x": "not a list"}})
