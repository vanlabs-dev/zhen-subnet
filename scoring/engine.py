"""Composite score computation engine (shared implementation).

Computes weighted composite scores from CVRMSE (50%), NMBE (25%),
R-squared (15%), and convergence speed (10%). This module is the
single source of truth for scoring, used by both the validator and
the local eval harness.

The CVRMSE component is rank-based as of spec v6: submissions with
CVRMSE above CVRMSE_CEILING are excluded from the round-local rank,
the remaining submissions are sorted ascending by CVRMSE, and the
top CVRMSE_TOP_K miners receive exponential-decay weights (base
CVRMSE_DECAY_BASE) normalized to sum to 1.0. NMBE, R-squared, and
convergence remain per-miner absolute scores as before.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

from scoring.normalization import safe_clamp

logger = logging.getLogger(__name__)


CVRMSE_CEILING: float = 10.0
"""Submissions with CVRMSE above this value are excluded from the rank-based
CVRMSE component and receive zero on that component. NMBE, R-squared, and
convergence still contribute to their composite. A round in which every
miner exceeds the ceiling returns an empty weight dict (caller falls back
to the on-chain weight copy)."""

CVRMSE_TOP_K: int = 5
"""Only the top K miners by ascending CVRMSE receive a non-zero CVRMSE
component score. Ranks K+1 and lower get zero. Caps the reward surface
for garbage submissions in large subnets."""

CVRMSE_DECAY_BASE: float = 0.5
"""Exponential decay base for rank-based CVRMSE weights. Rank r (1-indexed)
gets raw weight CVRMSE_DECAY_BASE**(r-1); the top K raw weights are
normalized to sum to 1.0."""


@dataclass
class VerifiedResult:
    """Container for a single miner's verification outcome.

    If reason is set, the submission failed verification and receives
    score 0.0. Otherwise, the metric fields contain computed values.

    cvrmse_ceiling_exceeded flags miners whose CVRMSE exceeded
    CVRMSE_CEILING during scoring. It is a display/diagnostic flag,
    not a rejection: the miner may still earn weight through the
    NMBE, R-squared, and convergence components.
    """

    cvrmse: float = 0.0
    nmbe: float = 0.0
    r_squared: float = 0.0
    simulations_used: int = 0
    calibrated_params: dict[str, float] = field(default_factory=dict)
    reason: str = ""
    detail: str = ""
    cvrmse_ceiling_exceeded: bool = False


class ScoringEngine:
    """Compute weighted composite scores from verification results.

    Scoring weights:
        CVRMSE:      50% (prediction accuracy, rank-based across the round)
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
    """Legacy absolute CVRMSE threshold. No longer consumed by compute()
    (rank-based scoring replaced it) but retained for the diagnostic
    breakdown in validator.scoring.breakdown."""
    NMBE_THRESHOLD: float = 0.10
    POWER_EXPONENT: float = 2.0
    """Exponent applied to raw composites before normalization. p=2 amplifies
    quality differences so Sybil swarms cannot dilute legitimate miners."""
    SCORE_FLOOR_RATIO: float = 0.05
    """Miners whose raw composite is below this fraction of the top scorer
    receive zero weight. Eliminates the long tail of garbage submissions."""

    def _cvrmse_component_scores(self, verified: dict[int, VerifiedResult]) -> dict[int, float]:
        """Return the rank-based CVRMSE component score per miner.

        Pipeline:
            1. Ceiling gate: exclude miners with non-finite CVRMSE, an
               existing rejection reason, or CVRMSE > CVRMSE_CEILING. Flag
               ceiling-exceeded miners via VerifiedResult.cvrmse_ceiling_exceeded
               so logging can surface them.
            2. Sort remaining miners ascending by CVRMSE (lower is better).
               Python's sorted is stable, so ties resolve by insertion order.
            3. Take the top CVRMSE_TOP_K; assign raw weights
               CVRMSE_DECAY_BASE ** rank_index and normalize to sum 1.0.
            4. Miners outside the top-K or excluded by the gate get 0.0.

        Returns:
            Dict from uid to CVRMSE component score in [0, 1]. The returned
            values sum to 1.0 when at least one miner passes the gate,
            otherwise every value is 0.0.
        """
        eligible: dict[int, VerifiedResult] = {}
        for uid, v in verified.items():
            if v.reason:
                continue
            if not math.isfinite(v.cvrmse):
                continue
            if v.cvrmse > CVRMSE_CEILING:
                if not v.cvrmse_ceiling_exceeded:
                    logger.info(
                        f"UID {uid}: CVRMSE={v.cvrmse:.4f} exceeds ceiling {CVRMSE_CEILING}; CVRMSE component set to 0"
                    )
                v.cvrmse_ceiling_exceeded = True
                continue
            eligible[uid] = v

        scores: dict[int, float] = {uid: 0.0 for uid in verified}
        if not eligible:
            return scores

        sorted_uids = sorted(eligible.keys(), key=lambda u: eligible[u].cvrmse)
        top_k_uids = sorted_uids[:CVRMSE_TOP_K]
        raw_weights = [CVRMSE_DECAY_BASE**r for r in range(len(top_k_uids))]
        total = sum(raw_weights)
        for uid, weight in zip(top_k_uids, raw_weights, strict=True):
            scores[uid] = weight / total
        return scores

    def _compute_composite(self, v: VerifiedResult, sim_budget: int, cvrmse_score: float = 0.0) -> float:
        """Compute raw composite score for a single miner.

        The CVRMSE component is supplied by the caller because it is
        round-local (computed across all miners in _cvrmse_component_scores).
        Any non-finite metric (NaN/Inf in CVRMSE, NMBE, or R-squared) forces
        the composite to 0.0 so a partially-broken result cannot still earn
        weight through the healthy components.

        Args:
            v: Verification result with metrics.
            sim_budget: Maximum simulation budget for convergence scoring.
            cvrmse_score: Rank-based CVRMSE component in [0, 1].

        Returns:
            Raw composite score (not normalized).
        """
        if not (math.isfinite(v.cvrmse) and math.isfinite(v.nmbe) and math.isfinite(v.r_squared)):
            return 0.0

        nmbe_norm = safe_clamp(1.0 - (abs(v.nmbe) / self.NMBE_THRESHOLD))
        r2_norm = safe_clamp(v.r_squared)
        conv_norm = safe_clamp(1.0 - (v.simulations_used / sim_budget)) if sim_budget > 0 else 0.0

        return (
            self.WEIGHTS["cvrmse"] * cvrmse_score
            + self.WEIGHTS["nmbe"] * nmbe_norm
            + self.WEIGHTS["r_squared"] * r2_norm
            + self.WEIGHTS["convergence"] * conv_norm
        )

    def compute(self, verified: dict[int, VerifiedResult], sim_budget: int = 1000) -> dict[int, float]:
        """Compute normalized weight vector from verification results.

        Pipeline:
            1. Compute rank-based CVRMSE component per miner.
            2. Short-circuit to {} if no miner passed the CVRMSE ceiling
               gate (design rule: no weight commit for a round where every
               submission is worse than the absolute CVRMSE ceiling).
            3. Compute raw composite per miner (failed submissions get 0.0).
            4. Score floor: zero out any miner below SCORE_FLOOR_RATIO of the top.
            5. Power-law normalize: w_i = score_i^p / sum(score_j^p).

        Args:
            verified: Mapping of miner UID to their VerifiedResult.
            sim_budget: Maximum simulation budget for convergence scoring.

        Returns:
            Mapping of miner UID to normalized weight (sums to 1.0).
            Returns empty dict if no miners passed the ceiling, every
            miner scored zero, or the input dict was empty; the caller
            is expected to fall back to the on-chain weight copy.
        """
        cvrmse_scores = self._cvrmse_component_scores(verified)
        if not any(s > 0 for s in cvrmse_scores.values()):
            return {}

        scores: dict[int, float] = {}
        for uid, v in verified.items():
            if v.reason:
                scores[uid] = 0.0
            else:
                scores[uid] = self._compute_composite(v, sim_budget, cvrmse_scores.get(uid, 0.0))

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

        Same formula as compute() but without the final floor and
        power-law normalization. Useful for breakdowns and debugging.
        Unlike compute(), does not short-circuit when every miner is
        ceiling-exceeded: diagnostic callers need the per-miner partial
        scores (NMBE, R-squared, convergence) even when the round
        produces no on-chain weights.

        Args:
            verified: Mapping of miner UID to their VerifiedResult.
            sim_budget: Maximum simulation budget for convergence scoring.

        Returns:
            Mapping of miner UID to raw composite score.
        """
        cvrmse_scores = self._cvrmse_component_scores(verified)
        scores: dict[int, float] = {}
        for uid, v in verified.items():
            if v.reason:
                scores[uid] = 0.0
            else:
                scores[uid] = self._compute_composite(v, sim_budget, cvrmse_scores.get(uid, 0.0))
        return scores
