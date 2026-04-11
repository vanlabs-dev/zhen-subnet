"""Exponential moving average tracker across calibration rounds.

Blends per-round composite scores into persistent EMA history per miner,
providing smoothed weight values for on-chain weight setting.
"""

from __future__ import annotations


class EMATracker:
    """Exponential Moving Average across rounds per miner."""

    def __init__(self, alpha: float = 0.3) -> None:
        """Initialize the EMA tracker.

        Args:
            alpha: Blending factor for new scores. Higher alpha means more
                weight on the current round (0 < alpha <= 1).
        """
        self.alpha = alpha
        self.scores: dict[int, float] = {}

    def update(self, round_scores: dict[int, float]) -> None:
        """Blend current round scores into EMA history.

        For miners seen for the first time, their score is taken as-is.
        For returning miners, score = alpha * new + (1 - alpha) * old.

        Args:
            round_scores: Mapping of miner UID to composite score for this round.
        """
        for uid, score in round_scores.items():
            if uid in self.scores:
                self.scores[uid] = self.alpha * score + (1.0 - self.alpha) * self.scores[uid]
            else:
                self.scores[uid] = score

    def get_weights(self) -> dict[int, float]:
        """Return normalized EMA scores for weight setting.

        Returns:
            Dict of miner UID to normalized weight (sums to 1.0).
            Returns uniform weights if total is zero.
        """
        total = sum(self.scores.values())
        if total > 0:
            return {uid: s / total for uid, s in self.scores.items()}
        n = len(self.scores)
        return {uid: 1.0 / n for uid in self.scores} if n > 0 else {}
