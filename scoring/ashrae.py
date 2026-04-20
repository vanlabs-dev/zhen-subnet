"""ASHRAE Guideline 14 compliance thresholds and predicates.

Pure boolean checks for the four compliance bands: hourly CVRMSE,
hourly NMBE, monthly CVRMSE, monthly NMBE. No side effects, no I/O.
Used by the CalibrationReport builder to populate the ashrae_*_pass
flags that the Market 2 report consumer reads.
"""

from __future__ import annotations

import math

ASHRAE_HOURLY_CVRMSE_THRESHOLD: float = 0.30
"""ASHRAE Guideline 14 hourly CVRMSE compliance ceiling (30%)."""

ASHRAE_HOURLY_NMBE_THRESHOLD: float = 0.10
"""ASHRAE Guideline 14 hourly |NMBE| compliance band (10%)."""

ASHRAE_MONTHLY_CVRMSE_THRESHOLD: float = 0.15
"""ASHRAE Guideline 14 monthly CVRMSE compliance ceiling (15%)."""

ASHRAE_MONTHLY_NMBE_THRESHOLD: float = 0.05
"""ASHRAE Guideline 14 monthly |NMBE| compliance band (5%).

Intentionally tighter than the hourly NMBE band per Guideline 14,
which recognizes that monthly aggregation removes short-timescale
noise but amplifies systematic bias.
"""


def hourly_cvrmse_passes(cvrmse: float) -> bool:
    """Return True if hourly CVRMSE is finite and within the 30% ceiling."""
    return math.isfinite(cvrmse) and cvrmse <= ASHRAE_HOURLY_CVRMSE_THRESHOLD


def hourly_nmbe_passes(nmbe: float) -> bool:
    """Return True if hourly NMBE is finite and |NMBE| <= 10%."""
    return math.isfinite(nmbe) and abs(nmbe) <= ASHRAE_HOURLY_NMBE_THRESHOLD


def monthly_cvrmse_passes(cvrmse: float) -> bool:
    """Return True if monthly CVRMSE is finite and within the 15% ceiling."""
    return math.isfinite(cvrmse) and cvrmse <= ASHRAE_MONTHLY_CVRMSE_THRESHOLD


def monthly_nmbe_passes(nmbe: float) -> bool:
    """Return True if monthly NMBE is finite and |NMBE| <= 5%."""
    return math.isfinite(nmbe) and abs(nmbe) <= ASHRAE_MONTHLY_NMBE_THRESHOLD


def overall_passes(
    hourly_cvrmse: float,
    hourly_nmbe: float,
    monthly_cvrmse: float,
    monthly_nmbe: float,
) -> bool:
    """Return True if all four ASHRAE Guideline 14 thresholds are met."""
    return (
        hourly_cvrmse_passes(hourly_cvrmse)
        and hourly_nmbe_passes(hourly_nmbe)
        and monthly_cvrmse_passes(monthly_cvrmse)
        and monthly_nmbe_passes(monthly_nmbe)
    )
