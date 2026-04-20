"""Unit tests for monthly-resolution ASHRAE Guideline 14 metrics."""

from __future__ import annotations

import math

import pytest

from scoring.metrics import (
    aggregate_to_monthly,
    compute_cvrmse_monthly,
    compute_nmbe_monthly,
)


class TestAggregateToMonthly:
    """Tests for aggregate_to_monthly."""

    def test_single_period_mean(self) -> None:
        """168 hours of constant temperature aggregates to the constant."""
        values = [20.0] * 168
        assert aggregate_to_monthly(values, aggregate_method="mean") == [20.0]

    def test_single_period_sum(self) -> None:
        """168 hours of unit energy aggregates to 168."""
        values = [1.0] * 168
        assert aggregate_to_monthly(values, aggregate_method="sum") == [168.0]

    def test_mean_of_linear_series(self) -> None:
        """Mean of 0..9 is 4.5."""
        values = [float(i) for i in range(10)]
        assert aggregate_to_monthly(values, aggregate_method="mean") == [4.5]

    def test_multi_month_chunks(self) -> None:
        """1500 hours of constant 2.0 aggregates under hours_per_month=720 into three sums."""
        values = [2.0] * 1500
        result = aggregate_to_monthly(values, aggregate_method="sum", hours_per_month=720)
        assert result == [1440.0, 1440.0, 120.0]

    def test_multi_month_chunks_mean(self) -> None:
        """Mean aggregation chunks into per-month means; trailing partial month keeps its mean."""
        values = [float(i) for i in range(1500)]
        result = aggregate_to_monthly(values, aggregate_method="mean", hours_per_month=720)
        # First chunk: mean(0..719) = 359.5
        # Second chunk: mean(720..1439) = 1079.5
        # Trailing partial (1440..1499): mean = 1469.5
        assert len(result) == 3
        assert result[0] == pytest.approx(359.5)
        assert result[1] == pytest.approx(1079.5)
        assert result[2] == pytest.approx(1469.5)

    def test_empty_raises(self) -> None:
        """Empty input raises ValueError."""
        with pytest.raises(ValueError, match="empty"):
            aggregate_to_monthly([], aggregate_method="mean")

    def test_non_finite_raises_nan(self) -> None:
        """NaN value raises ValueError."""
        with pytest.raises(ValueError, match="non-finite"):
            aggregate_to_monthly([1.0, float("nan"), 3.0], aggregate_method="mean")

    def test_non_finite_raises_inf(self) -> None:
        """Inf value raises ValueError."""
        with pytest.raises(ValueError, match="non-finite"):
            aggregate_to_monthly([1.0, float("inf"), 3.0], aggregate_method="sum")

    def test_unknown_method_raises(self) -> None:
        """Unknown aggregate_method raises ValueError."""
        with pytest.raises(ValueError, match="unknown aggregate_method"):
            aggregate_to_monthly([1.0, 2.0], aggregate_method="median")  # type: ignore[arg-type]

    def test_non_positive_hours_per_month_raises(self) -> None:
        """hours_per_month <= 0 raises ValueError."""
        with pytest.raises(ValueError, match="hours_per_month"):
            aggregate_to_monthly([1.0], aggregate_method="mean", hours_per_month=0)


class TestComputeCvrmseMonthly:
    """Tests for compute_cvrmse_monthly."""

    def test_perfect_match_mean_method(self) -> None:
        """Identical predicted and measured over a single month yields 0.0."""
        data = {"temp": [20.0] * 168}
        result = compute_cvrmse_monthly(data, data, {"temp": "mean"})
        assert result == 0.0

    def test_known_values_single_month(self) -> None:
        """Hand-computed CVRMSE at monthly resolution.

        For constant predicted=22 and measured=20 over one month, the
        monthly means are 22 and 20, so CVRMSE = sqrt((22-20)**2) / 20 = 0.1.
        """
        predicted = {"temp": [22.0] * 168}
        measured = {"temp": [20.0] * 168}
        result = compute_cvrmse_monthly(predicted, measured, {"temp": "mean"})
        assert result == pytest.approx(0.1)

    def test_sum_aggregate_energy(self) -> None:
        """Energy output with sum aggregate: both series sum to totals, CVRMSE computed on totals.

        predicted sum = 168, measured sum = 160. CVRMSE = |168-160| / 160 = 0.05.
        """
        predicted = {"energy_kWh": [1.0] * 168}
        measured = {"energy_kWh": [160.0 / 168] * 168}
        result = compute_cvrmse_monthly(predicted, measured, {"energy_kWh": "sum"})
        assert result == pytest.approx(0.05, abs=1e-6)

    def test_mixed_aggregate_methods(self) -> None:
        """Outputs with different aggregate methods are averaged."""
        predicted = {
            "temp": [22.0] * 168,
            "energy_kWh": [1.0] * 168,
        }
        measured = {
            "temp": [20.0] * 168,
            "energy_kWh": [160.0 / 168] * 168,
        }
        methods = {"temp": "mean", "energy_kWh": "sum"}
        result = compute_cvrmse_monthly(predicted, measured, methods)
        # temp CVRMSE = 0.1, energy CVRMSE ~ 0.05; mean = 0.075
        assert result == pytest.approx(0.075, abs=1e-4)

    def test_skips_zero_mean_output(self) -> None:
        """Output with monthly mean(measured) near zero is skipped."""
        predicted = {
            "temp": [22.0] * 168,
            "zero_mean": [0.01] * 168,
        }
        measured = {
            "temp": [20.0] * 168,
            "zero_mean": [0.0] * 168,
        }
        result = compute_cvrmse_monthly(predicted, measured, {"temp": "mean", "zero_mean": "mean"})
        # Only temp output contributes; CVRMSE = 0.1
        assert result == pytest.approx(0.1)

    def test_returns_one_when_all_invalid(self) -> None:
        """No valid outputs returns 1.0 (worst plausible)."""
        predicted = {"zero": [0.0] * 168}
        measured = {"zero": [0.0] * 168}
        result = compute_cvrmse_monthly(predicted, measured, {"zero": "mean"})
        assert result == 1.0

    def test_skips_unknown_aggregate_method(self) -> None:
        """Output with unknown method in output_aggregate_methods is skipped."""
        predicted = {"temp": [22.0] * 168}
        measured = {"temp": [20.0] * 168}
        result = compute_cvrmse_monthly(predicted, measured, {"temp": "median"})
        # Only output is skipped because method is unknown; falls through to worst-plausible
        assert result == 1.0

    def test_defaults_to_mean_when_method_missing(self) -> None:
        """Output absent from output_aggregate_methods defaults to mean aggregation."""
        predicted = {"temp": [22.0] * 168}
        measured = {"temp": [20.0] * 168}
        result = compute_cvrmse_monthly(predicted, measured, {})
        assert result == pytest.approx(0.1)

    def test_skips_non_finite_series(self) -> None:
        """Output containing NaN in predicted is skipped entirely."""
        predicted = {
            "temp": [20.0, float("nan")] + [20.0] * 166,
            "other": [10.0] * 168,
        }
        measured = {
            "temp": [20.0] * 168,
            "other": [10.0] * 168,
        }
        result = compute_cvrmse_monthly(predicted, measured, {"temp": "mean", "other": "mean"})
        # temp is skipped due to NaN; other is perfect match
        assert result == 0.0


class TestComputeNmbeMonthly:
    """Tests for compute_nmbe_monthly."""

    def test_no_bias(self) -> None:
        """Identical predicted and measured yields 0.0."""
        data = {"temp": [20.0] * 168}
        assert compute_nmbe_monthly(data, data, {"temp": "mean"}) == 0.0

    def test_positive_bias_mean(self) -> None:
        """Constant +2 offset on temperature: monthly NMBE = (22-20) / (1*20) = 0.1.

        With n=1 month, sum(p-m)=2, NMBE = 2 / (1 * 20) = 0.1.
        """
        predicted = {"temp": [22.0] * 168}
        measured = {"temp": [20.0] * 168}
        result = compute_nmbe_monthly(predicted, measured, {"temp": "mean"})
        assert result == pytest.approx(0.1)

    def test_negative_bias_mean(self) -> None:
        """Constant -1 offset: NMBE = -1 / 20 = -0.05."""
        predicted = {"temp": [19.0] * 168}
        measured = {"temp": [20.0] * 168}
        result = compute_nmbe_monthly(predicted, measured, {"temp": "mean"})
        assert result == pytest.approx(-0.05)

    def test_sum_aggregate(self) -> None:
        """Energy output bias under sum aggregate.

        predicted sum = 168, measured sum = 160. NMBE = 8 / (1 * 160) = 0.05.
        """
        predicted = {"energy_kWh": [1.0] * 168}
        measured = {"energy_kWh": [160.0 / 168] * 168}
        result = compute_nmbe_monthly(predicted, measured, {"energy_kWh": "sum"})
        assert result == pytest.approx(0.05, abs=1e-6)

    def test_skips_zero_mean_output(self) -> None:
        """Zero-mean output is skipped without distorting the aggregate."""
        predicted = {
            "temp": [22.0] * 168,
            "zero_mean": [0.0] * 168,
        }
        measured = {
            "temp": [20.0] * 168,
            "zero_mean": [0.0] * 168,
        }
        result = compute_nmbe_monthly(predicted, measured, {"temp": "mean", "zero_mean": "mean"})
        assert result == pytest.approx(0.1)

    def test_returns_one_when_all_invalid(self) -> None:
        """No valid outputs returns 1.0."""
        predicted = {"zero": [0.0] * 168}
        measured = {"zero": [0.0] * 168}
        result = compute_nmbe_monthly(predicted, measured, {"zero": "mean"})
        assert result == 1.0

    def test_nan_in_monthly_result_skipped(self) -> None:
        """Non-finite series is skipped."""
        predicted = {"temp": [float("inf")] + [20.0] * 167}
        measured = {"temp": [20.0] * 168}
        result = compute_nmbe_monthly(predicted, measured, {"temp": "mean"})
        assert result == 1.0

    def test_finite_result_for_clean_input(self) -> None:
        """Clean input produces a finite NMBE."""
        predicted = {"temp": [21.0] * 168}
        measured = {"temp": [20.0] * 168}
        result = compute_nmbe_monthly(predicted, measured, {"temp": "mean"})
        assert math.isfinite(result)
        assert result == pytest.approx(0.05)
