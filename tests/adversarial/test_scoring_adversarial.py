"""Adversarial edge case tests for the scoring engine.

Tests numerical hardening against NaN, Inf, negative values, zero
denominators, empty inputs, and mismatched keys.
"""

from __future__ import annotations

import math

from scoring import (
    ScoringEngine,
    VerifiedResult,
    compute_cvrmse,
    compute_nmbe,
    compute_r_squared,
)


class TestNaNHandling:
    """All-NaN and partial-NaN inputs must not crash."""

    def test_all_miners_nan(self) -> None:
        """Every miner has NaN metrics. Should not crash, all weights finite.

        NaN cvrmse/nmbe/r_squared clamp to 0 via safe_clamp, but convergence
        still contributes from simulations_used. With equal sim counts, weights
        are equal. With different sim counts, weights differ (correct behavior).
        """
        engine = ScoringEngine()
        # Same simulations_used so convergence component is equal too
        verified = {
            0: VerifiedResult(cvrmse=float("nan"), nmbe=float("nan"), r_squared=float("nan"), simulations_used=500),
            1: VerifiedResult(cvrmse=float("nan"), nmbe=float("nan"), r_squared=float("nan"), simulations_used=500),
        }
        weights = engine.compute(verified)

        # Only convergence contributes, and it is equal -> equal weights
        assert len(weights) == 2
        for uid in weights:
            assert math.isfinite(weights[uid])
        assert abs(weights[0] - weights[1]) < 1e-10


class TestInfHandling:
    """Inf values must be clamped gracefully."""

    def test_inf_cvrmse(self) -> None:
        """Inf CVRMSE should clamp to 0.0 component score via safe_clamp."""
        engine = ScoringEngine()
        verified = {
            0: VerifiedResult(cvrmse=float("inf"), nmbe=0.01, r_squared=0.90, simulations_used=200),
        }
        weights = engine.compute(verified)
        assert math.isfinite(weights[0])
        assert weights[0] == 1.0  # Only miner, gets all weight


class TestNegativeRSquared:
    """R-squared can be negative (worse than mean prediction)."""

    def test_negative_r_squared(self) -> None:
        """Negative R-squared should clamp to 0.0 via safe_clamp."""
        engine = ScoringEngine()
        verified = {
            0: VerifiedResult(cvrmse=0.10, nmbe=0.02, r_squared=-0.5, simulations_used=200),
        }
        weights = engine.compute(verified)
        assert math.isfinite(weights[0])

        # r2_norm should be 0.0 (clamped), but other components contribute
        # So composite > 0, and single miner gets weight 1.0
        assert weights[0] == 1.0


class TestZeroDivision:
    """Division by zero scenarios."""

    def test_zero_sim_budget(self) -> None:
        """sim_budget=0 should not crash (convergence becomes 0.0)."""
        engine = ScoringEngine()
        verified = {
            0: VerifiedResult(cvrmse=0.10, nmbe=0.02, r_squared=0.90, simulations_used=200),
        }
        weights = engine.compute(verified, sim_budget=0)
        assert math.isfinite(weights[0])
        assert weights[0] == 1.0


class TestEmptyInputs:
    """Empty predicted/measured dicts."""

    def test_empty_predictions(self) -> None:
        """Empty dicts should return fallback values."""
        assert compute_cvrmse({}, {}) == 1.0
        assert compute_nmbe({}, {}) == 1.0
        assert compute_r_squared({}, {}) == 0.0


class TestSingleTimestep:
    """Arrays of length 1."""

    def test_single_timestep(self) -> None:
        """Single-element arrays should compute without error."""
        predicted = {"temp": [21.0]}
        measured = {"temp": [20.0]}

        cvrmse = compute_cvrmse(predicted, measured)
        nmbe = compute_nmbe(predicted, measured)
        r2 = compute_r_squared(predicted, measured)

        assert math.isfinite(cvrmse)
        assert math.isfinite(nmbe)
        # R-squared with single point: SS_tot = 0, so skipped -> returns 0.0
        assert r2 == 0.0


class TestMismatchedKeys:
    """Predicted has keys not in measured."""

    def test_mismatched_keys(self) -> None:
        """Extra keys in predicted should be skipped gracefully."""
        predicted = {
            "temp": [20.0, 21.0, 22.0],
            "humidity": [50.0, 55.0, 60.0],
        }
        measured = {
            "temp": [20.0, 21.0, 22.0],
        }

        # Should only compute on "temp", skip "humidity"
        cvrmse = compute_cvrmse(predicted, measured)
        assert cvrmse == 0.0  # Perfect prediction on the matching key

        nmbe = compute_nmbe(predicted, measured)
        assert nmbe == 0.0

        r2 = compute_r_squared(predicted, measured)
        assert r2 == 1.0
