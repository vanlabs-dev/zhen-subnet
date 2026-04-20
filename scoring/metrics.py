"""ASHRAE-standard metric implementations (shared).

CVRMSE, NMBE, and R-squared computed over predicted vs. measured
time-series data. All computations use float64. Guards against division
by zero, NaN/Inf, and empty inputs.

Hourly variants (compute_cvrmse, compute_nmbe, compute_r_squared) drive
on-chain scoring. Monthly variants (compute_cvrmse_monthly,
compute_nmbe_monthly) alongside aggregate_to_monthly provide ASHRAE
Guideline 14 monthly-resolution metrics for the calibration report
consumer; they do not influence on-chain weights.
"""

from __future__ import annotations

from typing import Literal

import numpy as np
import numpy.typing as npt

AggregateMethod = Literal["mean", "sum"]


def compute_cvrmse(predicted: dict[str, list[float]], measured: dict[str, list[float]]) -> float:
    """Compute CVRMSE averaged across all scoring outputs.

    CVRMSE = sqrt(mean((p - m)^2)) / mean(m)

    Skips outputs where mean(measured) is zero or non-finite.
    Returns 1.0 (worst plausible) if no valid outputs remain.
    """
    cvrmse_values: list[float] = []
    for key in predicted:
        if key not in measured:
            continue
        p = np.array(predicted[key], dtype=np.float64)
        m = np.array(measured[key], dtype=np.float64)
        if len(m) == 0:
            continue
        mean_m = np.mean(m)
        if abs(mean_m) < 1e-6 or not np.isfinite(mean_m):
            continue
        rmse = np.sqrt(np.mean((p - m) ** 2))
        value = float(rmse / mean_m)
        if np.isfinite(value):
            cvrmse_values.append(value)
    return float(np.mean(cvrmse_values)) if cvrmse_values else 1.0


def compute_nmbe(predicted: dict[str, list[float]], measured: dict[str, list[float]]) -> float:
    """Compute NMBE averaged across all scoring outputs.

    NMBE = sum(p - m) / (n * mean(m))

    Captures systematic over/under-prediction. Skips outputs where
    mean(measured) is zero, non-finite, or array is empty.
    Returns 1.0 (worst plausible) if no valid outputs remain.
    """
    nmbe_values: list[float] = []
    for key in predicted:
        if key not in measured:
            continue
        p = np.array(predicted[key], dtype=np.float64)
        m = np.array(measured[key], dtype=np.float64)
        n = len(m)
        if n == 0:
            continue
        mean_m = np.mean(m)
        if abs(mean_m) < 1e-6 or not np.isfinite(mean_m):
            continue
        value = float(np.sum(p - m) / (n * mean_m))
        if np.isfinite(value):
            nmbe_values.append(value)
    return float(np.mean(nmbe_values)) if nmbe_values else 1.0


def compute_r_squared(predicted: dict[str, list[float]], measured: dict[str, list[float]]) -> float:
    """Compute R-squared averaged across all scoring outputs.

    R^2 = 1 - SS_res / SS_tot

    Skips outputs where SS_tot is zero (constant measured values).
    Returns 0.0 (no explanatory power) if no valid outputs remain.
    """
    r2_values: list[float] = []
    for key in predicted:
        if key not in measured:
            continue
        p = np.array(predicted[key], dtype=np.float64)
        m = np.array(measured[key], dtype=np.float64)
        if len(m) == 0:
            continue
        ss_res = float(np.sum((m - p) ** 2))
        ss_tot = float(np.sum((m - np.mean(m)) ** 2))
        if ss_tot == 0:
            continue
        value = 1.0 - (ss_res / ss_tot)
        if np.isfinite(value):
            r2_values.append(value)
    return float(np.mean(r2_values)) if r2_values else 0.0


def aggregate_to_monthly(
    hourly_values: list[float],
    aggregate_method: AggregateMethod = "mean",
    hours_per_month: int = 720,
) -> list[float]:
    """Aggregate hourly values into monthly-resolution chunks.

    For input shorter than or equal to hours_per_month, returns a
    single-element list containing the aggregate of all values. For
    longer input, chunks into hours_per_month buckets and aggregates
    each; a trailing partial chunk is aggregated rather than discarded
    so no input is silently dropped.

    Args:
        hourly_values: hourly-resolution input data.
        aggregate_method: "mean" for intensive quantities (temperature),
            "sum" for extensive quantities (energy).
        hours_per_month: hours per month (default 720 = 30 * 24).

    Returns:
        List of monthly aggregates in chronological order.

    Raises:
        ValueError: if hourly_values is empty, contains non-finite
            entries, aggregate_method is unknown, or hours_per_month
            is not positive.
    """
    if not hourly_values:
        raise ValueError("aggregate_to_monthly: hourly_values is empty")
    if hours_per_month <= 0:
        raise ValueError(f"aggregate_to_monthly: hours_per_month must be positive, got {hours_per_month}")
    if aggregate_method not in ("mean", "sum"):
        raise ValueError(f"aggregate_to_monthly: unknown aggregate_method {aggregate_method!r}")

    arr = np.array(hourly_values, dtype=np.float64)
    if not bool(np.all(np.isfinite(arr))):
        raise ValueError("aggregate_to_monthly: hourly_values contains non-finite entries")

    n = len(arr)
    aggregates: list[float] = []
    start = 0
    while start < n:
        end = min(start + hours_per_month, n)
        chunk = arr[start:end]
        if aggregate_method == "mean":
            aggregates.append(float(np.mean(chunk)))
        else:
            aggregates.append(float(np.sum(chunk)))
        start = end
    return aggregates


def _monthly_aggregates_for_pair(
    predicted: list[float],
    measured: list[float],
    method: AggregateMethod,
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]] | None:
    """Return aligned monthly aggregates for a predicted/measured pair.

    Returns None if either input is empty, contains non-finite values,
    or the aggregate lengths disagree (which can happen only if callers
    pass mismatched inputs).
    """
    if not predicted or not measured:
        return None
    p_arr = np.array(predicted, dtype=np.float64)
    m_arr = np.array(measured, dtype=np.float64)
    if not (bool(np.all(np.isfinite(p_arr))) and bool(np.all(np.isfinite(m_arr)))):
        return None
    p_monthly = aggregate_to_monthly(predicted, aggregate_method=method)
    m_monthly = aggregate_to_monthly(measured, aggregate_method=method)
    if len(p_monthly) != len(m_monthly):
        return None
    return np.array(p_monthly, dtype=np.float64), np.array(m_monthly, dtype=np.float64)


def compute_cvrmse_monthly(
    predicted: dict[str, list[float]],
    measured: dict[str, list[float]],
    output_aggregate_methods: dict[str, str],
) -> float:
    """Compute CVRMSE averaged across scoring outputs at monthly resolution.

    Aggregates each output's hourly series into monthly buckets using the
    per-output method in output_aggregate_methods ("mean" or "sum"), then
    computes CVRMSE on the monthly-resolution data. Skips outputs where
    monthly mean(measured) is zero or non-finite, mirroring the hourly
    variant's guard.

    Returns:
        Mean monthly CVRMSE across all valid outputs. 1.0 (worst
        plausible) if no outputs are valid.
    """
    cvrmse_values: list[float] = []
    for key in predicted:
        if key not in measured:
            continue
        method_str = output_aggregate_methods.get(key, "mean")
        if method_str not in ("mean", "sum"):
            continue
        method: AggregateMethod = "mean" if method_str == "mean" else "sum"
        pair = _monthly_aggregates_for_pair(predicted[key], measured[key], method)
        if pair is None:
            continue
        p_monthly, m_monthly = pair
        mean_m = float(np.mean(m_monthly))
        if abs(mean_m) < 1e-6 or not np.isfinite(mean_m):
            continue
        rmse = float(np.sqrt(np.mean((p_monthly - m_monthly) ** 2)))
        value = rmse / mean_m
        if np.isfinite(value):
            cvrmse_values.append(value)
    return float(np.mean(cvrmse_values)) if cvrmse_values else 1.0


def compute_nmbe_monthly(
    predicted: dict[str, list[float]],
    measured: dict[str, list[float]],
    output_aggregate_methods: dict[str, str],
) -> float:
    """Compute NMBE averaged across scoring outputs at monthly resolution.

    Aggregates each output's hourly series into monthly buckets using the
    per-output method in output_aggregate_methods ("mean" or "sum"), then
    computes NMBE on the monthly-resolution data. Skips outputs where
    monthly mean(measured) is zero or non-finite.

    Returns:
        Mean monthly NMBE across all valid outputs. 1.0 (worst
        plausible) if no outputs are valid.
    """
    nmbe_values: list[float] = []
    for key in predicted:
        if key not in measured:
            continue
        method_str = output_aggregate_methods.get(key, "mean")
        if method_str not in ("mean", "sum"):
            continue
        method: AggregateMethod = "mean" if method_str == "mean" else "sum"
        pair = _monthly_aggregates_for_pair(predicted[key], measured[key], method)
        if pair is None:
            continue
        p_monthly, m_monthly = pair
        n = len(m_monthly)
        mean_m = float(np.mean(m_monthly))
        if abs(mean_m) < 1e-6 or not np.isfinite(mean_m) or n == 0:
            continue
        value = float(np.sum(p_monthly - m_monthly) / (n * mean_m))
        if np.isfinite(value):
            nmbe_values.append(value)
    return float(np.mean(nmbe_values)) if nmbe_values else 1.0
