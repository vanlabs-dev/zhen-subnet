"""Composite score computation engine (shared implementation).

Computes weighted composite scores from CVRMSE (50%), NMBE (25%),
R-squared (15%), and convergence speed (10%). This module is the
single source of truth for scoring, used by both the validator and
the local eval harness.
"""

from __future__ import annotations

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
    reason: str | None = None
    detail: str | None = None


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

    def compute(self, verified: dict[int, VerifiedResult], sim_budget: int = 1000) -> dict[int, float]:
        """Compute normalized weight vector from verification results.

        Args:
            verified: Mapping of miner UID to their VerifiedResult.
            sim_budget: Maximum simulation budget for convergence scoring.

        Returns:
            Mapping of miner UID to normalized weight (sums to 1.0).
            Returns equal weights if all composites are zero.
            Returns empty dict if no miners.
        """
        scores: dict[int, float] = {}

        for uid, v in verified.items():
            if v.reason:
                scores[uid] = 0.0
                continue

            cvrmse_norm = safe_clamp(1.0 - (v.cvrmse / self.CVRMSE_THRESHOLD))
            nmbe_norm = safe_clamp(1.0 - (abs(v.nmbe) / self.NMBE_THRESHOLD))
            r2_norm = safe_clamp(v.r_squared)

            conv_norm = safe_clamp(1.0 - (v.simulations_used / sim_budget)) if sim_budget > 0 else 0.0

            composite = (
                self.WEIGHTS["cvrmse"] * cvrmse_norm
                + self.WEIGHTS["nmbe"] * nmbe_norm
                + self.WEIGHTS["r_squared"] * r2_norm
                + self.WEIGHTS["convergence"] * conv_norm
            )
            scores[uid] = composite

        # Normalize to weight vector
        total = sum(scores.values())
        if total > 0:
            return {uid: s / total for uid, s in scores.items()}
        n = len(scores)
        if n > 0:
            return {uid: 1.0 / n for uid in scores}
        return {}
