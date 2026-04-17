"""Composite score computation engine (shared implementation).

Computes weighted composite scores from CVRMSE (50%), NMBE (25%),
R-squared (15%), and convergence speed (10%). This module is the
single source of truth for scoring, used by both the validator and
the local eval harness.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from scoring.normalization import safe_clamp


@dataclass
class VerifiedResult:
    """Container for a single miner's verification outcome.

    If reason is set, the submission failed verification and receives
    score 0.0. Otherwise, the metric fields contain computed values.
    """

    cvrmse: float = 0.0
    nmbe: float = 0.0
    r_squared: float = 0.0
    simulations_used: int = 0
    calibrated_params: dict[str, float] = field(default_factory=dict)
    reason: str = ""
    detail: str = ""


class ScoringEngine:
    """Compute weighted composite scores from verification results.

    Scoring weights:
        CVRMSE:      50% (prediction accuracy)
        NMBE:        25% (systematic bias)
        R-squared:   15% (fit quality)
        Convergence: 10% (search efficiency)

    Output is normalized to a weight vector summing to 1.0 for
    on-chain weight setting.
    """

    WEIGHTS: dict[str, float] = {
        "cvrmse": 0.50,
        "nmbe": 0.25,
        "r_squared": 0.15,
        "convergence": 0.10,
    }
    CVRMSE_THRESHOLD: float = 0.30
    NMBE_THRESHOLD: float = 0.10
    POWER_EXPONENT: float = 2.0
    """Exponent applied to raw composites before normalization. p=2 amplifies
    quality differences so Sybil swarms cannot dilute legitimate miners."""
    SCORE_FLOOR_RATIO: float = 0.05
    """Miners whose raw composite is below this fraction of the top scorer
    receive zero weight. Eliminates the long tail of garbage submissions."""

    def _compute_composite(self, v: VerifiedResult, sim_budget: int) -> float:
        """Compute raw composite score for a single miner.

        Any non-finite metric (NaN/Inf in CVRMSE, NMBE, or R-squared) forces
        the composite to 0.0 so a partially-broken result cannot still earn
        weight through the healthy components.

        Args:
            v: Verification result with metrics.
            sim_budget: Maximum simulation budget for convergence scoring.

        Returns:
            Raw composite score (not normalized).
        """
        if not (math.isfinite(v.cvrmse) and math.isfinite(v.nmbe) and math.isfinite(v.r_squared)):
            return 0.0

        cvrmse_norm = safe_clamp(1.0 - (v.cvrmse / self.CVRMSE_THRESHOLD))
        nmbe_norm = safe_clamp(1.0 - (abs(v.nmbe) / self.NMBE_THRESHOLD))
        r2_norm = safe_clamp(v.r_squared)
        conv_norm = safe_clamp(1.0 - (v.simulations_used / sim_budget)) if sim_budget > 0 else 0.0

        return (
            self.WEIGHTS["cvrmse"] * cvrmse_norm
            + self.WEIGHTS["nmbe"] * nmbe_norm
            + self.WEIGHTS["r_squared"] * r2_norm
            + self.WEIGHTS["convergence"] * conv_norm
        )

    def compute(self, verified: dict[int, VerifiedResult], sim_budget: int = 1000) -> dict[int, float]:
        """Compute normalized weight vector from verification results.

        Pipeline:
            1. Compute raw composite per miner (failed submissions get 0.0).
            2. Score floor: zero out any miner below SCORE_FLOOR_RATIO of the top.
            3. Power-law normalize: w_i = score_i^p / sum(score_j^p).

        The power-law step amplifies quality differences so an attacker running
        many low-quality miners cannot dilute a legitimate miner's share.

        Args:
            verified: Mapping of miner UID to their VerifiedResult.
            sim_budget: Maximum simulation budget for convergence scoring.

        Returns:
            Mapping of miner UID to normalized weight (sums to 1.0).
            Returns empty dict if no miners or every miner scored zero;
            the caller is expected to fall back to the on-chain weight copy.
        """
        scores: dict[int, float] = {}
        for uid, v in verified.items():
            scores[uid] = 0.0 if v.reason else self._compute_composite(v, sim_budget)

        if not scores:
            return {}

        # Score floor: zero out miners below the relative threshold of the top scorer.
        max_score = max(scores.values())
        if max_score > 0:
            floor = max_score * self.SCORE_FLOOR_RATIO
            scores = {uid: (s if s >= floor else 0.0) for uid, s in scores.items()}

        # Power-law normalization: amplify quality differences before normalizing.
        powered: dict[int, float] = {uid: s**self.POWER_EXPONENT for uid, s in scores.items()}

        total = sum(powered.values())
        if total > 0:
            return {uid: s / total for uid, s in powered.items()}
        return {}

    def compute_raw(self, verified: dict[int, VerifiedResult], sim_budget: int = 1000) -> dict[int, float]:
        """Compute raw (unnormalized) composite scores.

        Same formula as compute() but without the final normalization step.
        Useful for breakdowns and debugging.

        Args:
            verified: Mapping of miner UID to their VerifiedResult.
            sim_budget: Maximum simulation budget for convergence scoring.

        Returns:
            Mapping of miner UID to raw composite score.
        """
        scores: dict[int, float] = {}
        for uid, v in verified.items():
            scores[uid] = 0.0 if v.reason else self._compute_composite(v, sim_budget)
        return scores
