"""Exponential moving average tracker across calibration rounds.

Blends per-round composite scores into persistent EMA history per miner,
providing smoothed weight values for on-chain weight setting. Rewards
consistent calibrators over lucky one-offs.
"""

from __future__ import annotations

import math


class EMATracker:
    """Exponential Moving Average across rounds per miner.

    First round for a UID sets the score directly (no history to blend).
    Subsequent rounds blend: ema = alpha * current + (1 - alpha) * previous.
    """

    def __init__(self, alpha: float = 0.3) -> None:
        """Initialize the EMA tracker.

        Args:
            alpha: Blending factor for new scores. Higher alpha weights
                recent rounds more heavily. Default 0.3.
        """
        self.alpha = alpha
        self.scores: dict[int, float] = {}

    def update(self, round_scores: dict[int, float]) -> None:
        """Blend current round scores into EMA history.

        Args:
            round_scores: Mapping of miner UID to composite score for
                the current round.
        """
        for uid, score in round_scores.items():
            if not math.isfinite(score):
                continue
            if uid in self.scores:
                self.scores[uid] = self.alpha * score + (1 - self.alpha) * self.scores[uid]
            else:
                self.scores[uid] = score

        # Decay absent miners toward zero and prune negligible scores
        for uid in list(self.scores.keys()):
            if uid not in round_scores:
                self.scores[uid] = (1 - self.alpha) * self.scores[uid]
                if self.scores[uid] < 1e-6:
                    del self.scores[uid]

    def get_weights(self) -> dict[int, float]:
        """Return normalized EMA scores for weight setting.

        Returns:
            Mapping of miner UID to normalized weight (sums to 1.0).
            Returns equal weights if all scores are zero.
            Returns empty dict if no miners tracked.
        """
        total = sum(self.scores.values())
        if total > 0:
            return {uid: s / total for uid, s in self.scores.items()}
        n = len(self.scores)
        if n > 0:
            return {uid: 1.0 / n for uid in self.scores}
        return {}
