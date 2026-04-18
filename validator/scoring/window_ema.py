"""Compute per-UID EMA over a rolling window of persisted round scores.

Pure function, no state. Bit-identical to the retired ``EMATracker`` when
fed rounds sequentially.
"""

from __future__ import annotations

import math

from validator.scoring_db import RoundScoreRow


def compute_window_ema(
    rows: list[RoundScoreRow],
    alpha: float = 0.3,
) -> dict[int, float]:
    """Return normalized EMA weights from windowed round scores.

    Rows must be ordered by ``received_at`` ASC. Rows are grouped by
    ``round_id`` (preserving first-appearance order). For each round,
    present miners with a finite composite are blended into the running
    EMA; absent miners (including those with non-finite composites)
    decay by ``(1 - alpha)``. EMA values below ``1e-6`` are pruned.

    Args:
        rows: Persisted rows for the desired time window, oldest first.
        alpha: Blending factor for new scores. Default ``0.3`` matches
            the retired ``EMATracker``.

    Returns:
        Mapping of miner UID to normalized weight summing to ``1.0``.
        Empty dict if no rows OR every EMA entry has decayed to zero
        (caller uses emptiness as the signal to fall back to chain-copy
        rather than publishing uniform weights for miners that all
        scored zero). Matches ``ScoringEngine.compute``'s contract.
    """
    if not rows:
        return {}

    rounds: list[tuple[str, list[RoundScoreRow]]] = []
    index: dict[str, int] = {}
    for row in rows:
        idx = index.get(row.round_id)
        if idx is None:
            index[row.round_id] = len(rounds)
            rounds.append((row.round_id, [row]))
        else:
            rounds[idx][1].append(row)

    ema: dict[int, float] = {}
    for _, round_rows in rounds:
        round_scores: dict[int, float] = {}
        for row in round_rows:
            if math.isfinite(row.composite):
                round_scores[row.uid] = row.composite

        for uid, score in round_scores.items():
            if uid in ema:
                ema[uid] = alpha * score + (1 - alpha) * ema[uid]
            else:
                ema[uid] = score

        for uid in list(ema.keys()):
            if uid not in round_scores:
                ema[uid] = (1 - alpha) * ema[uid]
                if ema[uid] < 1e-6:
                    del ema[uid]

    total = sum(ema.values())
    if total > 0:
        return {uid: s / total for uid, s in ema.items()}
    # Every entry decayed to zero: return empty so the caller falls back
    # to chain-copy rather than publishing uniform weights for miners
    # that all scored zero. Matches ScoringEngine.compute's contract.
    return {}
