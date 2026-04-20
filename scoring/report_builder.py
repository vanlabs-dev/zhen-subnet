"""CalibrationReport builder.

Single entry point that constructs a CalibrationReport from a
VerifiedResult, per-miner round context, and the predicted/measured
time-series used during verification. Read-only: does not persist,
log, or touch the DB.

Handles both clean and rejected submissions. For rejected submissions
(VerifiedResult.reason set), the builder still emits a report so
downstream readers can see WHY a calibration failed; metrics are
NaN and ASHRAE compliance flags are False.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

from scoring.ashrae import (
    hourly_cvrmse_passes,
    hourly_nmbe_passes,
    monthly_cvrmse_passes,
    monthly_nmbe_passes,
    overall_passes,
)
from scoring.engine import VerifiedResult
from scoring.metrics import (
    compute_cvrmse,
    compute_cvrmse_monthly,
    compute_nmbe,
    compute_nmbe_monthly,
    compute_r_squared,
)
from scoring.report import CalibrationReport


def _utc_now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string with millisecond precision."""
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _per_output_breakdown(
    predicted_values: dict[str, list[float]],
    measured_values: dict[str, list[float]],
) -> dict[str, dict[str, float]]:
    """Compute per-output hourly CVRMSE/NMBE/R-squared.

    Each output is scored in isolation by passing single-entry dicts to
    the shared metric functions. Outputs absent from measured_values are
    skipped.
    """
    per_output: dict[str, dict[str, float]] = {}
    for out_name, p_series in predicted_values.items():
        if out_name not in measured_values:
            continue
        single_pred = {out_name: p_series}
        single_meas = {out_name: measured_values[out_name]}
        per_output[out_name] = {
            "hourly_cvrmse": compute_cvrmse(single_pred, single_meas),
            "hourly_nmbe": compute_nmbe(single_pred, single_meas),
            "hourly_r_squared": compute_r_squared(single_pred, single_meas),
        }
    return per_output


def build_calibration_report(
    round_id: str,
    miner_uid: int,
    miner_hotkey: str,
    test_case_id: str,
    manifest_version: str,
    spec_version: int,
    training_period: tuple[int, int],
    test_period: tuple[int, int],
    verified_result: VerifiedResult,
    predicted_values: dict[str, list[float]] | None = None,
    measured_values: dict[str, list[float]] | None = None,
    output_aggregate_methods: dict[str, str] | None = None,
) -> CalibrationReport:
    """Build a CalibrationReport from a verified miner submission.

    For rejected submissions (verified_result.reason set), emits a
    report with identification plus calibrated_parameters populated
    and all metrics as NaN; the verification_reason carries the
    code. For clean submissions, computes monthly metrics and the
    per-output breakdown, then evaluates ASHRAE Guideline 14
    compliance on the four bands.

    Args:
        round_id: Validator round identifier.
        miner_uid: Miner's UID in the metagraph.
        miner_hotkey: Miner's SS58 hotkey.
        test_case_id: Test case identifier (e.g. "bestest_air").
        manifest_version: Active manifest version string.
        spec_version: Protocol spec_version the validator is running.
        training_period: (start_hour, end_hour) training window.
        test_period: (start_hour, end_hour) held-out window.
        verified_result: Output from VerificationEngine.verify_single.
        predicted_values: Per-output predicted time-series on the test
            period (optional for rejected submissions).
        measured_values: Per-output measured time-series on the test
            period (optional for rejected submissions).
        output_aggregate_methods: Per-output "mean" or "sum" method for
            monthly aggregation (optional for rejected submissions).

    Returns:
        Populated CalibrationReport. Caller handles serialization.
    """
    generated_at = _utc_now_iso()

    # Rejected submission: emit a minimal report with reason, no metrics.
    if verified_result.reason:
        return CalibrationReport(
            round_id=round_id,
            miner_uid=miner_uid,
            miner_hotkey=miner_hotkey,
            test_case_id=test_case_id,
            manifest_version=manifest_version,
            spec_version=spec_version,
            training_period_start_hour=training_period[0],
            training_period_end_hour=training_period[1],
            test_period_start_hour=test_period[0],
            test_period_end_hour=test_period[1],
            calibrated_parameters=dict(verified_result.calibrated_params),
            hourly_cvrmse=float("nan"),
            hourly_nmbe=float("nan"),
            hourly_r_squared=float("nan"),
            monthly_cvrmse=float("nan"),
            monthly_nmbe=float("nan"),
            per_output_metrics={},
            ashrae_hourly_cvrmse_pass=False,
            ashrae_hourly_nmbe_pass=False,
            ashrae_monthly_cvrmse_pass=False,
            ashrae_monthly_nmbe_pass=False,
            ashrae_overall_pass=False,
            simulations_used=verified_result.simulations_used,
            verification_reason=verified_result.reason,
            generated_at=generated_at,
        )

    # Clean submission: compute monthly metrics and ASHRAE compliance.
    predicted = predicted_values or {}
    measured = measured_values or {}
    methods = output_aggregate_methods or {}

    monthly_cvrmse = compute_cvrmse_monthly(predicted, measured, methods)
    monthly_nmbe = compute_nmbe_monthly(predicted, measured, methods)
    per_output = _per_output_breakdown(predicted, measured)

    hourly_cvrmse = verified_result.cvrmse
    hourly_nmbe = verified_result.nmbe
    hourly_r_squared = verified_result.r_squared

    hourly_cvrmse_pass = hourly_cvrmse_passes(hourly_cvrmse)
    hourly_nmbe_pass = hourly_nmbe_passes(hourly_nmbe)
    monthly_cvrmse_pass = monthly_cvrmse_passes(monthly_cvrmse)
    monthly_nmbe_pass = monthly_nmbe_passes(monthly_nmbe)
    ashrae_overall = overall_passes(hourly_cvrmse, hourly_nmbe, monthly_cvrmse, monthly_nmbe)

    # cvrmse_ceiling_exceeded is an on-chain scoring flag, not an ASHRAE
    # rejection. Surface it in verification_reason so the report reader
    # can see a miner was excluded from the CVRMSE component even if
    # the submission otherwise ran cleanly.
    verification_reason: str | None = None
    if verified_result.cvrmse_ceiling_exceeded:
        verification_reason = "CVRMSE_CEILING_EXCEEDED"
    elif not math.isfinite(hourly_cvrmse) or not math.isfinite(hourly_nmbe) or not math.isfinite(hourly_r_squared):
        verification_reason = "NON_FINITE_METRIC"

    return CalibrationReport(
        round_id=round_id,
        miner_uid=miner_uid,
        miner_hotkey=miner_hotkey,
        test_case_id=test_case_id,
        manifest_version=manifest_version,
        spec_version=spec_version,
        training_period_start_hour=training_period[0],
        training_period_end_hour=training_period[1],
        test_period_start_hour=test_period[0],
        test_period_end_hour=test_period[1],
        calibrated_parameters=dict(verified_result.calibrated_params),
        hourly_cvrmse=hourly_cvrmse,
        hourly_nmbe=hourly_nmbe,
        hourly_r_squared=hourly_r_squared,
        monthly_cvrmse=monthly_cvrmse,
        monthly_nmbe=monthly_nmbe,
        per_output_metrics=per_output,
        ashrae_hourly_cvrmse_pass=hourly_cvrmse_pass,
        ashrae_hourly_nmbe_pass=hourly_nmbe_pass,
        ashrae_monthly_cvrmse_pass=monthly_cvrmse_pass,
        ashrae_monthly_nmbe_pass=monthly_nmbe_pass,
        ashrae_overall_pass=ashrae_overall,
        simulations_used=verified_result.simulations_used,
        verification_reason=verification_reason,
        generated_at=generated_at,
    )
