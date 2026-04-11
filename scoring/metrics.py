"""ASHRAE-standard metric implementations (shared).

CVRMSE, NMBE, and R-squared computed over predicted vs. measured
time-series data. All computations use float64. Guards against division
by zero, NaN/Inf, and empty inputs.
"""

from __future__ import annotations

import numpy as np


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
        if mean_m == 0 or not np.isfinite(mean_m):
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
        if mean_m == 0 or not np.isfinite(mean_m):
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
