"""End-to-end report pipeline tests (build, persist, retrieve, attach).

Exercises the Phase 2a part 2 wiring without requiring bittensor or chain
access: construct a VerifiedResult with predicted/measured series, build
a CalibrationReport via the shared builder, persist it to an in-memory
ScoringDB, and assert round-trip fidelity plus backward-compat of the
synapse attachment path.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

import protocol
from scoring.engine import VerifiedResult
from scoring.report import CalibrationReport
from scoring.report_builder import build_calibration_report
from validator.round.orchestrator import derive_aggregate_methods
from validator.scoring_db import ScoringDB


def _clean_verified_result() -> VerifiedResult:
    """VerifiedResult with predicted/measured populated so monthly metrics are finite."""
    predicted = {
        "zone_air_temperature_C": [20.5] * 168,
        "total_heating_thermal_kWh": [1.025] * 168,
        "total_cooling_energy_kWh": [0.0] * 168,
    }
    measured = {
        "zone_air_temperature_C": [20.0] * 168,
        "total_heating_thermal_kWh": [1.0] * 168,
        "total_cooling_energy_kWh": [0.0] * 168,
    }
    return VerifiedResult(
        cvrmse=0.025,
        nmbe=0.025,
        r_squared=0.95,
        simulations_used=150,
        calibrated_params={"wall_r_value": 3.5, "hvac_cop": 3.2},
        predicted_values=predicted,
        measured_values=measured,
    )


def test_spec_version_is_current() -> None:
    """Guard against accidental spec bumps. Update this assertion when
    intentionally bumping the spec so the bump shows up in code review.
    """
    assert protocol.__spec_version__ == 7


def test_derive_aggregate_methods_extracts_mean_and_sum() -> None:
    """derive_aggregate_methods reads resample_method for each scoring output."""
    config = {
        "scoring_outputs": [
            "zone_air_temperature_C",
            "total_heating_thermal_kWh",
            "total_cooling_energy_kWh",
        ],
        "boptest_output_mapping": {
            "zone_air_temperature_C": {"resample_method": "mean"},
            "total_heating_thermal_kWh": {"resample_method": "sum"},
            "total_cooling_energy_kWh": {"resample_method": "sum"},
        },
    }

    methods = derive_aggregate_methods(config)
    assert methods == {
        "zone_air_temperature_C": "mean",
        "total_heating_thermal_kWh": "sum",
        "total_cooling_energy_kWh": "sum",
    }


def test_derive_aggregate_methods_defaults_to_mean() -> None:
    """Outputs without resample_method fall back to mean."""
    config = {
        "scoring_outputs": ["a", "b"],
        "boptest_output_mapping": {
            "a": {},
            "b": {"resample_method": "weird_mode"},
        },
    }

    methods = derive_aggregate_methods(config)
    assert methods == {"a": "mean", "b": "mean"}


def test_derive_aggregate_methods_skips_missing_mapping() -> None:
    """Scoring outputs not present in boptest_output_mapping are skipped."""
    config = {
        "scoring_outputs": ["a", "b"],
        "boptest_output_mapping": {
            "a": {"resample_method": "mean"},
        },
    }

    methods = derive_aggregate_methods(config)
    assert methods == {"a": "mean"}


async def test_pipeline_clean_submission_persists_and_roundtrips(tmp_path: Path) -> None:
    """Build, persist, retrieve a report for a clean submission."""
    db = ScoringDB(db_path=tmp_path / "scoring.db")
    try:
        verified = _clean_verified_result()
        report = build_calibration_report(
            round_id="round-3",
            miner_uid=5,
            miner_hotkey="5PipelineHk",
            test_case_id="bestest_air",
            manifest_version="v2.0.0",
            spec_version=protocol.__spec_version__,
            training_period=(0, 336),
            test_period=(336, 504),
            verified_result=verified,
            predicted_values=verified.predicted_values,
            measured_values=verified.measured_values,
            output_aggregate_methods={
                "zone_air_temperature_C": "mean",
                "total_heating_thermal_kWh": "sum",
                "total_cooling_energy_kWh": "sum",
            },
        )

        await db.persist_report(report)

        restored = await db.get_report("round-3", 5)
        assert restored is not None
        assert restored.round_id == "round-3"
        assert restored.miner_uid == 5
        assert restored.miner_hotkey == "5PipelineHk"
        assert restored.hourly_cvrmse == pytest.approx(0.025)
        assert restored.hourly_r_squared == pytest.approx(0.95)
        assert math.isfinite(restored.monthly_cvrmse)
        assert math.isfinite(restored.monthly_nmbe)
        assert restored.ashrae_overall_pass is True
        assert "zone_air_temperature_C" in restored.per_output_metrics
    finally:
        db.close()


async def test_pipeline_rejected_submission_persists(tmp_path: Path) -> None:
    """Rejected submissions also persist (with NaN metrics and reason set)."""
    db = ScoringDB(db_path=tmp_path / "scoring.db")
    try:
        verified = VerifiedResult(
            reason="DEFAULT_PARAMS",
            detail="Submitted parameters within 0.1% of config defaults.",
            calibrated_params={"wall_r_value": 3.5},
        )
        report = build_calibration_report(
            round_id="round-4",
            miner_uid=6,
            miner_hotkey="5Rejected",
            test_case_id="bestest_air",
            manifest_version="v2.0.0",
            spec_version=protocol.__spec_version__,
            training_period=(0, 336),
            test_period=(336, 504),
            verified_result=verified,
        )

        await db.persist_report(report)

        restored = await db.get_report("round-4", 6)
        assert restored is not None
        assert restored.verification_reason == "DEFAULT_PARAMS"
        assert math.isnan(restored.hourly_cvrmse)
        assert restored.ashrae_overall_pass is False
        assert restored.calibrated_parameters == {"wall_r_value": 3.5}
    finally:
        db.close()


def test_synapse_attachment_has_report_dict() -> None:
    """Attaching a report to a synapse stub carries the full dict through."""
    # Use the stub dataclass when bittensor is not installed; either path
    # must support setting calibration_report to a plain dict.
    from protocol.synapse import CalibrationSynapse

    verified = _clean_verified_result()
    report = build_calibration_report(
        round_id="r",
        miner_uid=1,
        miner_hotkey="5A",
        test_case_id="bestest_air",
        manifest_version="v2.0.0",
        spec_version=protocol.__spec_version__,
        training_period=(0, 336),
        test_period=(336, 504),
        verified_result=verified,
        predicted_values=verified.predicted_values,
        measured_values=verified.measured_values,
        output_aggregate_methods={
            "zone_air_temperature_C": "mean",
            "total_heating_thermal_kWh": "sum",
            "total_cooling_energy_kWh": "sum",
        },
    )

    synapse = CalibrationSynapse()
    assert synapse.calibration_report is None
    synapse.calibration_report = report.to_dict()
    assert synapse.calibration_report is not None
    assert synapse.calibration_report["round_id"] == "r"
    assert synapse.calibration_report["miner_uid"] == 1

    rebuilt = CalibrationReport.from_dict(synapse.calibration_report)
    assert rebuilt.round_id == "r"
    assert rebuilt.miner_uid == 1
