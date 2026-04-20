"""Unit tests for ASHRAE Guideline 14 threshold predicates."""

from __future__ import annotations

import math

from scoring.ashrae import (
    ASHRAE_HOURLY_CVRMSE_THRESHOLD,
    ASHRAE_HOURLY_NMBE_THRESHOLD,
    ASHRAE_MONTHLY_CVRMSE_THRESHOLD,
    ASHRAE_MONTHLY_NMBE_THRESHOLD,
    hourly_cvrmse_passes,
    hourly_nmbe_passes,
    monthly_cvrmse_passes,
    monthly_nmbe_passes,
    overall_passes,
)


class TestThresholdConstants:
    """Threshold constants match ASHRAE Guideline 14 specification."""

    def test_hourly_cvrmse_threshold(self) -> None:
        assert ASHRAE_HOURLY_CVRMSE_THRESHOLD == 0.30

    def test_hourly_nmbe_threshold(self) -> None:
        assert ASHRAE_HOURLY_NMBE_THRESHOLD == 0.10

    def test_monthly_cvrmse_threshold(self) -> None:
        assert ASHRAE_MONTHLY_CVRMSE_THRESHOLD == 0.15

    def test_monthly_nmbe_threshold(self) -> None:
        assert ASHRAE_MONTHLY_NMBE_THRESHOLD == 0.05


class TestHourlyCvrmse:
    """Tests for hourly_cvrmse_passes."""

    def test_below_threshold_passes(self) -> None:
        assert hourly_cvrmse_passes(0.15) is True

    def test_at_threshold_passes(self) -> None:
        """Exactly 30% is inclusive (ASHRAE states <=)."""
        assert hourly_cvrmse_passes(0.30) is True

    def test_above_threshold_fails(self) -> None:
        assert hourly_cvrmse_passes(0.31) is False

    def test_zero_passes(self) -> None:
        assert hourly_cvrmse_passes(0.0) is True

    def test_nan_fails(self) -> None:
        assert hourly_cvrmse_passes(float("nan")) is False

    def test_inf_fails(self) -> None:
        assert hourly_cvrmse_passes(float("inf")) is False


class TestHourlyNmbe:
    """Tests for hourly_nmbe_passes."""

    def test_within_band_positive(self) -> None:
        assert hourly_nmbe_passes(0.05) is True

    def test_within_band_negative(self) -> None:
        """Negative NMBE within |NMBE| <= 10% passes."""
        assert hourly_nmbe_passes(-0.05) is True

    def test_at_upper_boundary(self) -> None:
        assert hourly_nmbe_passes(0.10) is True

    def test_at_lower_boundary(self) -> None:
        assert hourly_nmbe_passes(-0.10) is True

    def test_above_upper_fails(self) -> None:
        assert hourly_nmbe_passes(0.101) is False

    def test_below_lower_fails(self) -> None:
        assert hourly_nmbe_passes(-0.101) is False

    def test_nan_fails(self) -> None:
        assert hourly_nmbe_passes(float("nan")) is False


class TestMonthlyCvrmse:
    """Tests for monthly_cvrmse_passes."""

    def test_below_threshold_passes(self) -> None:
        assert monthly_cvrmse_passes(0.10) is True

    def test_at_threshold_passes(self) -> None:
        assert monthly_cvrmse_passes(0.15) is True

    def test_above_threshold_fails(self) -> None:
        assert monthly_cvrmse_passes(0.16) is False

    def test_hourly_threshold_fails_monthly(self) -> None:
        """0.30 is the hourly ceiling but exceeds the monthly ceiling."""
        assert monthly_cvrmse_passes(0.30) is False


class TestMonthlyNmbe:
    """Tests for monthly_nmbe_passes."""

    def test_within_band(self) -> None:
        assert monthly_nmbe_passes(0.03) is True

    def test_at_upper_boundary(self) -> None:
        assert monthly_nmbe_passes(0.05) is True

    def test_at_lower_boundary(self) -> None:
        assert monthly_nmbe_passes(-0.05) is True

    def test_above_upper_fails(self) -> None:
        assert monthly_nmbe_passes(0.06) is False

    def test_below_lower_fails(self) -> None:
        assert monthly_nmbe_passes(-0.06) is False

    def test_hourly_nmbe_fails_monthly_when_above_5(self) -> None:
        """An NMBE that passes hourly (e.g. 0.08) fails the tighter monthly band."""
        assert hourly_nmbe_passes(0.08) is True
        assert monthly_nmbe_passes(0.08) is False


class TestOverallPasses:
    """Tests for overall_passes (all four bands)."""

    def test_all_passing(self) -> None:
        assert overall_passes(0.15, 0.05, 0.10, 0.03) is True

    def test_hourly_cvrmse_fails(self) -> None:
        assert overall_passes(0.31, 0.05, 0.10, 0.03) is False

    def test_hourly_nmbe_fails(self) -> None:
        assert overall_passes(0.15, 0.11, 0.10, 0.03) is False

    def test_monthly_cvrmse_fails(self) -> None:
        assert overall_passes(0.15, 0.05, 0.16, 0.03) is False

    def test_monthly_nmbe_fails(self) -> None:
        assert overall_passes(0.15, 0.05, 0.10, 0.06) is False

    def test_all_at_boundary(self) -> None:
        """All four exactly at their thresholds is a pass."""
        assert overall_passes(0.30, 0.10, 0.15, 0.05) is True

    def test_any_nan_fails(self) -> None:
        assert overall_passes(float("nan"), 0.05, 0.10, 0.03) is False
        assert overall_passes(0.15, float("nan"), 0.10, 0.03) is False
        assert overall_passes(0.15, 0.05, float("nan"), 0.03) is False
        assert overall_passes(0.15, 0.05, 0.10, float("nan")) is False

    def test_all_nan_fails(self) -> None:
        nan = float("nan")
        assert overall_passes(nan, nan, nan, nan) is False
        # sanity: math.isfinite agrees
        assert math.isfinite(nan) is False
