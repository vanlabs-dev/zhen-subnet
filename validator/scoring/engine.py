"""Composite score computation engine.

Computes weighted composite scores from CVRMSE (50%), NMBE (25%),
R-squared (15%), and convergence speed (10%) components. Normalizes
scores to a weight vector for on-chain weight setting.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from validator.scoring.normalization import safe_clamp


@dataclass
class VerifiedResult:
    """Result of verifying a miner's calibration submission."""

    cvrmse: float = 1.0
    nmbe: float = 1.0
    r_squared: float = 0.0
    simulations_used: int = 0
    calibrated_params: dict[str, float] = field(default_factory=dict)
    reason: str = ""
    detail: str = ""


class ScoringEngine:
    """Computes composite scores from verification results."""

    WEIGHTS: dict[str, float] = {
        "cvrmse": 0.50,
        "nmbe": 0.25,
        "r_squared": 0.15,
        "convergence": 0.10,
    }
    CVRMSE_THRESHOLD: float = 0.30
    NMBE_THRESHOLD: float = 0.10

    def compute(self, verified: dict[int, VerifiedResult], sim_budget: int = 1000) -> dict[int, float]:
        """Compute normalized composite scores for all verified miners.

        Args:
            verified: Mapping of miner UID to VerifiedResult.
            sim_budget: Maximum simulation budget allowed.

        Returns:
            Mapping of miner UID to normalized weight (sums to 1.0).
        """
        scores: dict[int, float] = {}

        for uid, v in verified.items():
            if v.reason:
                scores[uid] = 0.0
                continue

            cvrmse_norm = safe_clamp(1.0 - (v.cvrmse / self.CVRMSE_THRESHOLD))
            nmbe_norm = safe_clamp(1.0 - (abs(v.nmbe) / self.NMBE_THRESHOLD))
            r2_norm = safe_clamp(v.r_squared)
            conv_norm = safe_clamp(1.0 - (v.simulations_used / sim_budget))

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
        return {uid: 1.0 / n for uid in scores} if n > 0 else {}

    def compute_raw(self, verified: dict[int, VerifiedResult], sim_budget: int = 1000) -> dict[int, float]:
        """Compute raw (unnormalized) composite scores.

        Same as compute() but without the final normalization step.
        Useful for breakdowns and debugging.

        Args:
            verified: Mapping of miner UID to VerifiedResult.
            sim_budget: Maximum simulation budget allowed.

        Returns:
            Mapping of miner UID to raw composite score.
        """
        scores: dict[int, float] = {}

        for uid, v in verified.items():
            if v.reason:
                scores[uid] = 0.0
                continue

            cvrmse_norm = safe_clamp(1.0 - (v.cvrmse / self.CVRMSE_THRESHOLD))
            nmbe_norm = safe_clamp(1.0 - (abs(v.nmbe) / self.NMBE_THRESHOLD))
            r2_norm = safe_clamp(v.r_squared)
            conv_norm = safe_clamp(1.0 - (v.simulations_used / sim_budget))

            composite = (
                self.WEIGHTS["cvrmse"] * cvrmse_norm
                + self.WEIGHTS["nmbe"] * nmbe_norm
                + self.WEIGHTS["r_squared"] * r2_norm
                + self.WEIGHTS["convergence"] * conv_norm
            )
            scores[uid] = composite

        return scores
