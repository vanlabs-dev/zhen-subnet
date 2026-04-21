"""Unit tests for CalibrationSynapse.

Tests synapse creation, defaults, result fields, and serialization.
Skipped if bittensor is not installed.
"""

from __future__ import annotations

import pytest

try:
    import bittensor  # noqa: F401

    HAS_BITTENSOR = True
except ImportError:
    HAS_BITTENSOR = False

pytestmark = pytest.mark.skipif(not HAS_BITTENSOR, reason="bittensor not installed")


def test_synapse_creation() -> None:
    """Create CalibrationSynapse with challenge fields, verify fields set."""
    from protocol.synapse import CalibrationSynapse

    synapse = CalibrationSynapse(
        test_case_id="bestest_hydronic_heat_pump",
        manifest_version="v1.0.0",
        training_data={"zone_air_temperature_C": [20.0, 21.0, 20.5]},
        parameter_names=["wall_r_value", "roof_r_value"],
        parameter_bounds={"wall_r_value": [0.5, 10.0], "roof_r_value": [0.5, 12.0]},
        simulation_budget=500,
        round_id="round-42",
        train_start_hour=0,
        train_end_hour=336,
    )
    assert synapse.test_case_id == "bestest_hydronic_heat_pump"
    assert synapse.manifest_version == "v1.0.0"
    assert synapse.simulation_budget == 500
    assert synapse.round_id == "round-42"
    assert len(synapse.parameter_names) == 2


def test_synapse_defaults() -> None:
    """Create empty synapse, verify all defaults."""
    from protocol.synapse import CalibrationSynapse

    synapse = CalibrationSynapse()
    assert synapse.test_case_id == ""
    assert synapse.manifest_version == ""
    assert synapse.training_data == {}
    assert synapse.parameter_names == []
    assert synapse.parameter_bounds == {}
    assert synapse.simulation_budget == 1000
    assert synapse.round_id == ""
    assert synapse.train_start_hour == 0
    assert synapse.train_end_hour == 0


def test_synapse_result_fields() -> None:
    """Set result fields, verify they serialize."""
    from protocol.synapse import CalibrationSynapse

    synapse = CalibrationSynapse()
    synapse.calibrated_params = {"wall_r_value": 3.5, "roof_r_value": 5.0}
    synapse.simulations_used = 200
    synapse.training_cvrmse = 0.032
    synapse.metadata = {"algorithm": "bayesian"}

    assert synapse.calibrated_params["wall_r_value"] == 3.5
    assert synapse.simulations_used == 200
    assert synapse.training_cvrmse == 0.032


def test_synapse_roundtrip() -> None:
    """Create synapse, serialize to dict, deserialize back, verify fields."""
    from protocol.synapse import CalibrationSynapse

    original = CalibrationSynapse(
        test_case_id="test_case_1",
        round_id="round-7",
        simulation_budget=800,
        parameter_names=["param_a"],
        parameter_bounds={"param_a": [1.0, 10.0]},
    )
    original.calibrated_params = {"param_a": 5.5}
    original.simulations_used = 150

    # Serialize via Pydantic
    data = original.model_dump()
    restored = CalibrationSynapse(**data)

    assert restored.test_case_id == "test_case_1"
    assert restored.round_id == "round-7"
    assert restored.simulation_budget == 800
    assert restored.calibrated_params == {"param_a": 5.5}
    assert restored.simulations_used == 150


def test_synapse_optional_results() -> None:
    """Result fields should be None by default."""
    from protocol.synapse import CalibrationSynapse

    synapse = CalibrationSynapse()
    assert synapse.calibrated_params is None
    assert synapse.simulations_used is None
    assert synapse.training_cvrmse is None
    assert synapse.metadata is None
    assert synapse.calibration_report is None


def test_synapse_calibration_report_roundtrip() -> None:
    """calibration_report carries a CalibrationReport dict through Pydantic."""
    from protocol.synapse import CalibrationSynapse
    from scoring.report import CalibrationReport

    report = CalibrationReport(
        round_id="round-7",
        miner_uid=2,
        miner_hotkey="5Test",
        test_case_id="bestest_air",
        manifest_version="v2.0.0",
        spec_version=7,
        training_period_start_hour=0,
        training_period_end_hour=336,
        test_period_start_hour=336,
        test_period_end_hour=504,
        calibrated_parameters={"wall_r_value": 3.5},
        hourly_cvrmse=0.12,
        hourly_nmbe=-0.02,
        hourly_r_squared=0.88,
        monthly_cvrmse=0.06,
        monthly_nmbe=0.01,
        per_output_metrics={},
        ashrae_hourly_cvrmse_pass=True,
        ashrae_hourly_nmbe_pass=True,
        ashrae_monthly_cvrmse_pass=True,
        ashrae_monthly_nmbe_pass=True,
        ashrae_overall_pass=True,
        simulations_used=150,
        verification_reason=None,
        generated_at="2026-04-21T12:00:00.000000Z",
    )

    synapse = CalibrationSynapse()
    synapse.calibration_report = report.to_dict()

    # Pydantic round-trip must preserve the report payload.
    data = synapse.model_dump()
    restored = CalibrationSynapse(**data)

    assert restored.calibration_report is not None
    assert restored.calibration_report["round_id"] == "round-7"
    assert restored.calibration_report["miner_uid"] == 2
    assert restored.calibration_report["ashrae_overall_pass"] is True

    # And the validator-side helper can rebuild the typed report from it.
    rebuilt = CalibrationReport.from_dict(restored.calibration_report)
    assert rebuilt.round_id == "round-7"
    assert rebuilt.miner_uid == 2
    assert rebuilt.hourly_cvrmse == 0.12


def test_calibration_report_not_in_required_hash_fields() -> None:
    """The report is validator-populated post-submission; it must not be
    part of the hash-protected set or cross-validator consensus will
    diverge on the same miner response.
    """
    from protocol.synapse import CalibrationSynapse

    synapse = CalibrationSynapse()
    assert "calibration_report" not in synapse.required_hash_fields


def test_required_hash_fields_includes_payload() -> None:
    """The hash-protected set must include the fields that determine
    what computation the miner runs. Without this, a MITM can tamper
    with training_data or parameter_bounds and the signature still
    validates.
    """
    from protocol.synapse import CalibrationSynapse

    s = CalibrationSynapse()
    expected = {
        "test_case_id",
        "round_id",
        "train_start_hour",
        "train_end_hour",
        "training_data",
        "parameter_bounds",
        "simulation_budget",
        "manifest_version",
    }
    assert set(s.required_hash_fields) >= expected
