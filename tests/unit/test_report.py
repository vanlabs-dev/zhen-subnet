"""Unit tests for CalibrationReport and build_calibration_report."""

from __future__ import annotations

import json
import math

from scoring.engine import VerifiedResult
from scoring.report import CalibrationReport
from scoring.report_builder import build_calibration_report


def _base_report_kwargs() -> dict[str, object]:
    """Return kwargs for a minimal CalibrationReport for roundtrip tests."""
    return {
        "round_id": "round-42",
        "miner_uid": 7,
        "miner_hotkey": "5Abc123",
        "test_case_id": "bestest_air",
        "manifest_version": "v2.0.0",
        "spec_version": 6,
        "training_period_start_hour": 0,
        "training_period_end_hour": 336,
        "test_period_start_hour": 336,
        "test_period_end_hour": 504,
        "calibrated_parameters": {"wall_r_value": 3.5, "hvac_cop": 3.2},
        "hourly_cvrmse": 0.12,
        "hourly_nmbe": -0.02,
        "hourly_r_squared": 0.88,
        "monthly_cvrmse": 0.06,
        "monthly_nmbe": 0.01,
        "per_output_metrics": {
            "zone_air_temperature_C": {
                "hourly_cvrmse": 0.05,
                "hourly_nmbe": -0.01,
                "hourly_r_squared": 0.92,
            },
        },
        "ashrae_hourly_cvrmse_pass": True,
        "ashrae_hourly_nmbe_pass": True,
        "ashrae_monthly_cvrmse_pass": True,
        "ashrae_monthly_nmbe_pass": True,
        "ashrae_overall_pass": True,
        "simulations_used": 200,
        "verification_reason": None,
        "generated_at": "2026-04-21T12:00:00.000000Z",
    }


class TestCalibrationReportSerialization:
    """Tests for CalibrationReport to_dict / to_json / from_dict."""

    def test_roundtrip(self) -> None:
        """Construct, serialize to dict, reconstruct, assert equality."""
        original = CalibrationReport(**_base_report_kwargs())  # type: ignore[arg-type]
        as_dict = original.to_dict()
        restored = CalibrationReport.from_dict(as_dict)
        assert restored == original

    def test_json_serialization_valid(self) -> None:
        """to_json returns valid JSON string that round-trips."""
        report = CalibrationReport(**_base_report_kwargs())  # type: ignore[arg-type]
        text = report.to_json()
        parsed = json.loads(text)
        assert parsed["round_id"] == "round-42"
        assert parsed["ashrae_overall_pass"] is True

    def test_json_serialization_indent(self) -> None:
        """to_json with indent produces human-readable output."""
        report = CalibrationReport(**_base_report_kwargs())  # type: ignore[arg-type]
        text = report.to_json(indent=2)
        assert "\n" in text

    def test_nan_metrics_survive_roundtrip(self) -> None:
        """NaN metric fields serialize to None and restore to NaN."""
        kwargs = _base_report_kwargs()
        kwargs["hourly_cvrmse"] = float("nan")
        kwargs["monthly_nmbe"] = float("nan")
        kwargs["per_output_metrics"] = {
            "zone_air_temperature_C": {
                "hourly_cvrmse": float("nan"),
                "hourly_nmbe": 0.02,
                "hourly_r_squared": 0.5,
            }
        }
        original = CalibrationReport(**kwargs)  # type: ignore[arg-type]
        as_dict = original.to_dict()
        assert as_dict["hourly_cvrmse"] is None
        assert as_dict["monthly_nmbe"] is None
        assert as_dict["per_output_metrics"]["zone_air_temperature_C"]["hourly_cvrmse"] is None

        restored = CalibrationReport.from_dict(as_dict)
        assert math.isnan(restored.hourly_cvrmse)
        assert math.isnan(restored.monthly_nmbe)
        assert math.isnan(restored.per_output_metrics["zone_air_temperature_C"]["hourly_cvrmse"])

    def test_json_with_nan_is_parseable(self) -> None:
        """NaN-containing report serializes to strict JSON (no NaN literal)."""
        kwargs = _base_report_kwargs()
        kwargs["hourly_cvrmse"] = float("nan")
        report = CalibrationReport(**kwargs)  # type: ignore[arg-type]
        text = report.to_json()
        # json.loads with default settings rejects 'NaN'; passing through dict roundtrip
        # ensures the JSON contains null, not NaN.
        parsed = json.loads(text)
        assert parsed["hourly_cvrmse"] is None


class TestBuildReportCleanSubmission:
    """Tests for build_calibration_report on clean submissions."""

    def _predicted_measured(self) -> tuple[dict[str, list[float]], dict[str, list[float]]]:
        # Offsets chosen so monthly NMBE stays within the ASHRAE 5% band:
        # temp offset 0.5/20 = 2.5%, heating offset 0.025/1.0 = 2.5%.
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
        return predicted, measured

    def test_clean_report_populated(self) -> None:
        """Report carries all identification, metrics, ASHRAE flags, and per-output."""
        predicted, measured = self._predicted_measured()
        verified = VerifiedResult(
            cvrmse=0.025,
            nmbe=0.025,
            r_squared=0.95,
            simulations_used=150,
            calibrated_params={"wall_r_value": 3.5},
            predicted_values=predicted,
            measured_values=measured,
        )
        report = build_calibration_report(
            round_id="round-10",
            miner_uid=3,
            miner_hotkey="5Xyz",
            test_case_id="bestest_air",
            manifest_version="v2.0.0",
            spec_version=6,
            training_period=(0, 336),
            test_period=(336, 504),
            verified_result=verified,
            predicted_values=predicted,
            measured_values=measured,
            output_aggregate_methods={
                "zone_air_temperature_C": "mean",
                "total_heating_thermal_kWh": "sum",
                "total_cooling_energy_kWh": "sum",
            },
        )
        assert report.round_id == "round-10"
        assert report.miner_uid == 3
        assert report.calibrated_parameters == {"wall_r_value": 3.5}
        assert report.hourly_cvrmse == 0.025
        assert report.hourly_nmbe == 0.025
        assert report.hourly_r_squared == 0.95
        assert math.isfinite(report.monthly_cvrmse)
        assert math.isfinite(report.monthly_nmbe)
        assert report.simulations_used == 150
        assert report.verification_reason is None
        assert report.generated_at != ""

    def test_per_output_metrics_populated(self) -> None:
        """per_output_metrics has an entry per scoring output."""
        predicted, measured = self._predicted_measured()
        verified = VerifiedResult(
            cvrmse=0.025,
            nmbe=0.025,
            r_squared=0.95,
            simulations_used=150,
            calibrated_params={},
            predicted_values=predicted,
            measured_values=measured,
        )
        report = build_calibration_report(
            round_id="r",
            miner_uid=0,
            miner_hotkey="h",
            test_case_id="bestest_air",
            manifest_version="v2.0.0",
            spec_version=6,
            training_period=(0, 336),
            test_period=(336, 504),
            verified_result=verified,
            predicted_values=predicted,
            measured_values=measured,
            output_aggregate_methods={
                "zone_air_temperature_C": "mean",
                "total_heating_thermal_kWh": "sum",
                "total_cooling_energy_kWh": "sum",
            },
        )
        assert "zone_air_temperature_C" in report.per_output_metrics
        assert "total_heating_thermal_kWh" in report.per_output_metrics
        for key in report.per_output_metrics:
            assert "hourly_cvrmse" in report.per_output_metrics[key]
            assert "hourly_nmbe" in report.per_output_metrics[key]
            assert "hourly_r_squared" in report.per_output_metrics[key]

    def test_ashrae_flags_reflect_thresholds(self) -> None:
        """All four ASHRAE flags plus overall are evaluated against the thresholds."""
        predicted, measured = self._predicted_measured()
        verified = VerifiedResult(
            cvrmse=0.025,
            nmbe=0.025,
            r_squared=0.95,
            simulations_used=150,
            calibrated_params={},
            predicted_values=predicted,
            measured_values=measured,
        )
        report = build_calibration_report(
            round_id="r",
            miner_uid=0,
            miner_hotkey="h",
            test_case_id="bestest_air",
            manifest_version="v2.0.0",
            spec_version=6,
            training_period=(0, 336),
            test_period=(336, 504),
            verified_result=verified,
            predicted_values=predicted,
            measured_values=measured,
            output_aggregate_methods={
                "zone_air_temperature_C": "mean",
                "total_heating_thermal_kWh": "sum",
                "total_cooling_energy_kWh": "sum",
            },
        )
        assert report.ashrae_hourly_cvrmse_pass is True
        assert report.ashrae_hourly_nmbe_pass is True
        assert report.ashrae_monthly_cvrmse_pass is True
        # 0.025 NMBE hourly passes (<= 0.10); monthly NMBE band is tighter but 0.025 still passes (<= 0.05)
        assert report.ashrae_monthly_nmbe_pass is True
        assert report.ashrae_overall_pass is True


class TestBuildReportThresholdBoundaries:
    """Tests for build_calibration_report at ASHRAE threshold boundaries."""

    def test_hourly_cvrmse_above_threshold_flags_fail(self) -> None:
        """Hourly CVRMSE at 0.31 (just over 0.30) fails the hourly flag and overall."""
        predicted = {"temp": [20.5] * 168}
        measured = {"temp": [20.0] * 168}
        verified = VerifiedResult(
            cvrmse=0.31,
            nmbe=0.0,
            r_squared=0.9,
            simulations_used=100,
            calibrated_params={},
            predicted_values=predicted,
            measured_values=measured,
        )
        report = build_calibration_report(
            round_id="r",
            miner_uid=0,
            miner_hotkey="h",
            test_case_id="bestest_air",
            manifest_version="v2.0.0",
            spec_version=6,
            training_period=(0, 336),
            test_period=(336, 504),
            verified_result=verified,
            predicted_values=predicted,
            measured_values=measured,
            output_aggregate_methods={"temp": "mean"},
        )
        assert report.ashrae_hourly_cvrmse_pass is False
        assert report.ashrae_overall_pass is False

    def test_hourly_cvrmse_at_threshold_passes(self) -> None:
        """Hourly CVRMSE exactly at 0.30 passes the hourly flag."""
        predicted = {"temp": [20.0] * 168}
        measured = {"temp": [20.0] * 168}
        verified = VerifiedResult(
            cvrmse=0.30,
            nmbe=0.0,
            r_squared=0.9,
            simulations_used=100,
            calibrated_params={},
            predicted_values=predicted,
            measured_values=measured,
        )
        report = build_calibration_report(
            round_id="r",
            miner_uid=0,
            miner_hotkey="h",
            test_case_id="bestest_air",
            manifest_version="v2.0.0",
            spec_version=6,
            training_period=(0, 336),
            test_period=(336, 504),
            verified_result=verified,
            predicted_values=predicted,
            measured_values=measured,
            output_aggregate_methods={"temp": "mean"},
        )
        assert report.ashrae_hourly_cvrmse_pass is True


class TestBuildReportRejectedSubmission:
    """Tests for build_calibration_report on rejected submissions."""

    def test_rejected_default_params(self) -> None:
        """DEFAULT_PARAMS rejection produces a report with NaN metrics and the reason set."""
        verified = VerifiedResult(
            reason="DEFAULT_PARAMS",
            detail="Submitted parameters within 0.1% of config defaults.",
            calibrated_params={"wall_r_value": 3.5},
        )
        report = build_calibration_report(
            round_id="r",
            miner_uid=9,
            miner_hotkey="h",
            test_case_id="bestest_air",
            manifest_version="v2.0.0",
            spec_version=6,
            training_period=(0, 336),
            test_period=(336, 504),
            verified_result=verified,
            predicted_values=None,
            measured_values=None,
            output_aggregate_methods=None,
        )
        assert report.verification_reason == "DEFAULT_PARAMS"
        assert math.isnan(report.hourly_cvrmse)
        assert math.isnan(report.hourly_nmbe)
        assert math.isnan(report.monthly_cvrmse)
        assert math.isnan(report.monthly_nmbe)
        assert report.ashrae_overall_pass is False
        assert report.ashrae_hourly_cvrmse_pass is False
        assert report.calibrated_parameters == {"wall_r_value": 3.5}
        assert report.per_output_metrics == {}

    def test_rejected_simulation_nan(self) -> None:
        """SIMULATION_NAN rejection produces a clean rejected-report shape."""
        verified = VerifiedResult(
            reason="SIMULATION_NAN",
            detail="RC model produced non-finite values in zone_air_temperature_C",
            calibrated_params={},
        )
        report = build_calibration_report(
            round_id="r",
            miner_uid=9,
            miner_hotkey="h",
            test_case_id="bestest_air",
            manifest_version="v2.0.0",
            spec_version=6,
            training_period=(0, 336),
            test_period=(336, 504),
            verified_result=verified,
        )
        assert report.verification_reason == "SIMULATION_NAN"
        assert math.isnan(report.hourly_cvrmse)
        assert report.ashrae_overall_pass is False

    def test_ceiling_exceeded_surfaces_reason(self) -> None:
        """Clean submission with cvrmse_ceiling_exceeded flag surfaces the code via verification_reason."""
        predicted = {"temp": [20.0] * 168}
        measured = {"temp": [20.0] * 168}
        verified = VerifiedResult(
            cvrmse=15.0,
            nmbe=0.0,
            r_squared=0.5,
            simulations_used=100,
            calibrated_params={},
            cvrmse_ceiling_exceeded=True,
            predicted_values=predicted,
            measured_values=measured,
        )
        report = build_calibration_report(
            round_id="r",
            miner_uid=0,
            miner_hotkey="h",
            test_case_id="bestest_air",
            manifest_version="v2.0.0",
            spec_version=6,
            training_period=(0, 336),
            test_period=(336, 504),
            verified_result=verified,
            predicted_values=predicted,
            measured_values=measured,
            output_aggregate_methods={"temp": "mean"},
        )
        assert report.verification_reason == "CVRMSE_CEILING_EXCEEDED"
        # CVRMSE=15 fails the ASHRAE hourly band
        assert report.ashrae_hourly_cvrmse_pass is False
        assert report.ashrae_overall_pass is False
