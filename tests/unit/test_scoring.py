"""Unit tests for the scoring engine, metrics, and normalization."""

from __future__ import annotations

import math

from scoring import (
    ScoringEngine,
    VerifiedResult,
    compute_cvrmse,
    compute_nmbe,
    compute_r_squared,
    safe_clamp,
)
from scoring.engine import CVRMSE_DECAY_BASE, CVRMSE_TOP_K

# ---------------------------------------------------------------------------
# Metric tests
# ---------------------------------------------------------------------------


class TestCVRMSE:
    """Tests for compute_cvrmse."""

    def test_cvrmse_perfect_prediction(self) -> None:
        """Identical predicted and measured should give 0.0."""
        data = {"temp": [20.0, 21.0, 22.0, 23.0]}
        assert compute_cvrmse(data, data) == 0.0

    def test_cvrmse_known_values(self) -> None:
        """Hand-computed CVRMSE for a simple case.

        measured = [10, 20, 30], mean = 20
        predicted = [12, 18, 33]
        errors = [2, -2, 3], squared = [4, 4, 9], mean = 17/3
        RMSE = sqrt(17/3) = 2.3805...
        CVRMSE = 2.3805 / 20 = 0.11902...
        """
        predicted = {"out": [12.0, 18.0, 33.0]}
        measured = {"out": [10.0, 20.0, 30.0]}
        result = compute_cvrmse(predicted, measured)
        expected = (17.0 / 3.0) ** 0.5 / 20.0
        assert abs(result - expected) < 1e-10


class TestNMBE:
    """Tests for compute_nmbe."""

    def test_nmbe_no_bias(self) -> None:
        """Identical predicted and measured should give 0.0."""
        data = {"temp": [20.0, 21.0, 22.0]}
        assert compute_nmbe(data, data) == 0.0

    def test_nmbe_positive_bias(self) -> None:
        """Predicted systematically higher should give positive NMBE.

        measured = [10, 20, 30], mean = 20, n = 3
        predicted = [12, 22, 32]  (each +2)
        sum(p - m) = 6
        NMBE = 6 / (3 * 20) = 0.1
        """
        predicted = {"out": [12.0, 22.0, 32.0]}
        measured = {"out": [10.0, 20.0, 30.0]}
        result = compute_nmbe(predicted, measured)
        assert abs(result - 0.1) < 1e-10


class TestRSquared:
    """Tests for compute_r_squared."""

    def test_r_squared_perfect(self) -> None:
        """Identical predicted and measured should give 1.0."""
        data = {"temp": [10.0, 20.0, 30.0, 40.0]}
        assert compute_r_squared(data, data) == 1.0

    def test_r_squared_known_values(self) -> None:
        """Hand-computed R-squared for a simple case.

        measured = [10, 20, 30], mean = 20
        predicted = [12, 18, 33]
        SS_res = (10-12)^2 + (20-18)^2 + (30-33)^2 = 4+4+9 = 17
        SS_tot = (10-20)^2 + (20-20)^2 + (30-20)^2 = 100+0+100 = 200
        R^2 = 1 - 17/200 = 0.915
        """
        predicted = {"out": [12.0, 18.0, 33.0]}
        measured = {"out": [10.0, 20.0, 30.0]}
        result = compute_r_squared(predicted, measured)
        expected = 1.0 - 17.0 / 200.0
        assert abs(result - expected) < 1e-10


# ---------------------------------------------------------------------------
# Normalization tests
# ---------------------------------------------------------------------------


class TestSafeClamp:
    """Tests for safe_clamp."""

    def test_safe_clamp_normal(self) -> None:
        """Values in [0, 1] should pass through unchanged."""
        assert safe_clamp(0.0) == 0.0
        assert safe_clamp(0.5) == 0.5
        assert safe_clamp(1.0) == 1.0

    def test_safe_clamp_nan_inf(self) -> None:
        """NaN and Inf should return 0.0."""
        assert safe_clamp(float("nan")) == 0.0
        assert safe_clamp(float("inf")) == 0.0
        assert safe_clamp(float("-inf")) == 0.0

    def test_safe_clamp_out_of_range(self) -> None:
        """Negative clamps to 0, >1 clamps to 1."""
        assert safe_clamp(-0.5) == 0.0
        assert safe_clamp(1.5) == 1.0
        assert safe_clamp(-100.0) == 0.0


# ---------------------------------------------------------------------------
# Scoring engine tests
# ---------------------------------------------------------------------------


class TestScoringEngine:
    """Tests for ScoringEngine."""

    def test_scoring_engine_basic(self) -> None:
        """Three miners with different accuracy, verify rank order."""
        engine = ScoringEngine()

        verified = {
            0: VerifiedResult(cvrmse=0.05, nmbe=0.01, r_squared=0.95, simulations_used=200),
            1: VerifiedResult(cvrmse=0.15, nmbe=0.05, r_squared=0.80, simulations_used=500),
            2: VerifiedResult(cvrmse=0.25, nmbe=0.08, r_squared=0.60, simulations_used=800),
        }
        weights = engine.compute(verified)

        # Best miner (0) should have highest weight
        assert weights[0] > weights[1] > weights[2]

    def test_scoring_engine_failed_verification(self) -> None:
        """Miner with reason set should get 0.0 composite."""
        engine = ScoringEngine()
        verified = {
            0: VerifiedResult(cvrmse=0.05, nmbe=0.01, r_squared=0.95, simulations_used=200),
            1: VerifiedResult(reason="SIMULATION_TIMEOUT", detail="Exceeded 300s"),
        }
        weights = engine.compute(verified)

        # Failed miner gets 0, successful miner gets all weight
        assert weights[1] == 0.0
        assert weights[0] == 1.0

    def test_all_failed_returns_empty(self) -> None:
        """All miners failed: compute returns {} so caller can fall back to chain weights."""
        engine = ScoringEngine()
        verified = {
            0: VerifiedResult(reason="TIMEOUT"),
            1: VerifiedResult(reason="CRASHED"),
            2: VerifiedResult(reason="INVALID_PARAMS"),
        }
        weights = engine.compute(verified)
        assert weights == {}

    def test_scoring_engine_single_miner(self) -> None:
        """One miner should get weight 1.0."""
        engine = ScoringEngine()
        verified = {
            0: VerifiedResult(cvrmse=0.10, nmbe=0.02, r_squared=0.90, simulations_used=300),
        }
        weights = engine.compute(verified)
        assert abs(weights[0] - 1.0) < 1e-10

    def test_scoring_engine_weights_sum_to_one(self) -> None:
        """Output weights should sum to 1.0."""
        engine = ScoringEngine()
        verified = {
            i: VerifiedResult(
                cvrmse=0.05 * (i + 1),
                nmbe=0.01 * (i + 1),
                r_squared=max(0.0, 0.95 - 0.1 * i),
                simulations_used=100 * (i + 1),
            )
            for i in range(5)
        }
        weights = engine.compute(verified)
        assert abs(sum(weights.values()) - 1.0) < 1e-10

    def test_scoring_engine_nan_inputs(self) -> None:
        """VerifiedResult with NaN cvrmse should not crash."""
        engine = ScoringEngine()
        verified = {
            0: VerifiedResult(cvrmse=float("nan"), nmbe=0.01, r_squared=0.90, simulations_used=200),
            1: VerifiedResult(cvrmse=0.10, nmbe=0.02, r_squared=0.85, simulations_used=300),
        }
        weights = engine.compute(verified)

        # Should not crash, weights should sum to 1.0
        assert math.isfinite(sum(weights.values()))
        assert abs(sum(weights.values()) - 1.0) < 1e-10


class TestCVRMSEComponent:
    """Rank-based CVRMSE component with top-K cap and ceiling gate (spec v6)."""

    def test_cvrmse_component_ceiling_gate_rejects_above_threshold(self) -> None:
        """CVRMSE above CVRMSE_CEILING produces zero component score."""
        engine = ScoringEngine()
        verified = {
            0: VerifiedResult(cvrmse=0.5, nmbe=0.0, r_squared=0.9, simulations_used=100),
            1: VerifiedResult(cvrmse=5.0, nmbe=0.0, r_squared=0.9, simulations_used=100),
            2: VerifiedResult(cvrmse=15.0, nmbe=0.0, r_squared=0.9, simulations_used=100),
        }
        cvrmse_scores = engine._cvrmse_component_scores(verified)

        assert cvrmse_scores[2] == 0.0
        assert verified[2].cvrmse_ceiling_exceeded is True
        assert verified[0].cvrmse_ceiling_exceeded is False
        assert verified[1].cvrmse_ceiling_exceeded is False
        # Two miners below ceiling: ranks 1 and 2 share the normalized decay weights.
        assert cvrmse_scores[0] > cvrmse_scores[1] > 0

    def test_cvrmse_component_top_k_cap(self) -> None:
        """Only the top CVRMSE_TOP_K miners receive a non-zero component score."""
        engine = ScoringEngine()
        verified = {
            i: VerifiedResult(cvrmse=0.1 * (i + 1), nmbe=0.0, r_squared=0.9, simulations_used=100) for i in range(7)
        }
        cvrmse_scores = engine._cvrmse_component_scores(verified)

        # Ranks 1-5 (UIDs 0-4) nonzero; ranks 6-7 (UIDs 5-6) zeroed.
        for i in range(CVRMSE_TOP_K):
            assert cvrmse_scores[i] > 0, f"rank {i + 1} miner should be in top-K"
        for i in range(CVRMSE_TOP_K, 7):
            assert cvrmse_scores[i] == 0, f"rank {i + 1} miner should be outside top-K"
        # The top-K scores normalize to 1.0.
        assert abs(sum(cvrmse_scores.values()) - 1.0) < 1e-10

    def test_cvrmse_component_exponential_decay(self) -> None:
        """Rank-r miner gets raw weight base^(r-1); normalized across the top-K."""
        engine = ScoringEngine()
        verified = {
            0: VerifiedResult(cvrmse=0.1, nmbe=0.0, r_squared=0.9, simulations_used=100),
            1: VerifiedResult(cvrmse=0.2, nmbe=0.0, r_squared=0.9, simulations_used=100),
            2: VerifiedResult(cvrmse=0.3, nmbe=0.0, r_squared=0.9, simulations_used=100),
        }
        cvrmse_scores = engine._cvrmse_component_scores(verified)

        raw = [CVRMSE_DECAY_BASE**r for r in range(3)]  # [1.0, 0.5, 0.25]
        total = sum(raw)
        assert abs(cvrmse_scores[0] - raw[0] / total) < 1e-12
        assert abs(cvrmse_scores[1] - raw[1] / total) < 1e-12
        assert abs(cvrmse_scores[2] - raw[2] / total) < 1e-12

    def test_cvrmse_component_all_miners_rejected(self) -> None:
        """If every miner exceeds the ceiling, every CVRMSE component score is zero."""
        engine = ScoringEngine()
        verified = {
            0: VerifiedResult(cvrmse=12.0, nmbe=0.0, r_squared=0.9, simulations_used=100),
            1: VerifiedResult(cvrmse=50.0, nmbe=0.0, r_squared=0.9, simulations_used=100),
            2: VerifiedResult(cvrmse=100.0, nmbe=0.0, r_squared=0.9, simulations_used=100),
        }
        cvrmse_scores = engine._cvrmse_component_scores(verified)

        assert all(s == 0.0 for s in cvrmse_scores.values())
        assert all(v.cvrmse_ceiling_exceeded for v in verified.values())
        # compute() short-circuits to empty so the caller falls back to chain weights.
        weights = engine.compute(verified)
        assert weights == {}

    def test_cvrmse_component_single_miner_passes(self) -> None:
        """With only one miner below the ceiling, it captures the full normalized weight."""
        engine = ScoringEngine()
        verified = {
            0: VerifiedResult(cvrmse=50.0, nmbe=0.0, r_squared=0.9, simulations_used=100),
            1: VerifiedResult(cvrmse=20.0, nmbe=0.0, r_squared=0.9, simulations_used=100),
            2: VerifiedResult(cvrmse=5.0, nmbe=0.0, r_squared=0.9, simulations_used=100),
            3: VerifiedResult(cvrmse=11.0, nmbe=0.0, r_squared=0.9, simulations_used=100),
            4: VerifiedResult(cvrmse=15.0, nmbe=0.0, r_squared=0.9, simulations_used=100),
        }
        cvrmse_scores = engine._cvrmse_component_scores(verified)

        assert cvrmse_scores[2] == 1.0
        for uid in (0, 1, 3, 4):
            assert cvrmse_scores[uid] == 0.0
            assert verified[uid].cvrmse_ceiling_exceeded is True

    def test_cvrmse_component_tied_values_stable_ordering(self) -> None:
        """Tied CVRMSEs produce a stable ordering; the pair still sums to 1.0."""
        engine = ScoringEngine()
        verified = {
            0: VerifiedResult(cvrmse=3.0, nmbe=0.0, r_squared=0.9, simulations_used=100),
            1: VerifiedResult(cvrmse=3.0, nmbe=0.0, r_squared=0.9, simulations_used=100),
        }
        cvrmse_scores = engine._cvrmse_component_scores(verified)

        assert cvrmse_scores[0] > 0
        assert cvrmse_scores[1] > 0
        assert abs(sum(cvrmse_scores.values()) - 1.0) < 1e-10
        # Stable sort by insertion order: UID 0 ranks first, gets the larger weight.
        assert cvrmse_scores[0] > cvrmse_scores[1]

    def test_composite_formula_unchanged_for_valid_round(self) -> None:
        """Spot-check: composite = 0.50*cvrmse_rank + 0.25*nmbe + 0.15*r2 + 0.10*conv."""
        engine = ScoringEngine()
        verified = {
            0: VerifiedResult(cvrmse=0.5, nmbe=0.02, r_squared=0.8, simulations_used=200),
            1: VerifiedResult(cvrmse=1.5, nmbe=0.05, r_squared=0.6, simulations_used=800),
        }
        sim_budget = 1000
        raw = engine.compute_raw(verified, sim_budget=sim_budget)

        # Rank-based CVRMSE: rank 1 gets 1.0 / (1.0 + 0.5) = 0.667; rank 2 gets 0.333.
        cvrmse_0 = 1.0 / 1.5
        cvrmse_1 = 0.5 / 1.5

        expected_0 = (
            0.50 * cvrmse_0
            + 0.25 * safe_clamp(1.0 - 0.02 / engine.NMBE_THRESHOLD)
            + 0.15 * safe_clamp(0.8)
            + 0.10 * safe_clamp(1.0 - 200 / sim_budget)
        )
        expected_1 = (
            0.50 * cvrmse_1
            + 0.25 * safe_clamp(1.0 - 0.05 / engine.NMBE_THRESHOLD)
            + 0.15 * safe_clamp(0.6)
            + 0.10 * safe_clamp(1.0 - 800 / sim_budget)
        )
        assert abs(raw[0] - expected_0) < 1e-12
        assert abs(raw[1] - expected_1) < 1e-12
