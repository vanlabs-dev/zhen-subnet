"""Unit tests for :func:`validator.scoring.window_ema.compute_window_ema`."""

from __future__ import annotations

import math

from validator.scoring.window_ema import compute_window_ema
from validator.scoring_db import RoundScoreRow


def _row(round_id: str, uid: int, composite: float, seq: int = 0) -> RoundScoreRow:
    """Fabricate a RoundScoreRow with minimal padding for tests."""
    return RoundScoreRow(
        id=seq,
        round_id=round_id,
        uid=uid,
        test_case="tc",
        train_period_start=0,
        train_period_end=48,
        test_period_start=48,
        test_period_end=72,
        cvrmse=0.1,
        nmbe=0.01,
        r_squared=0.9,
        sims_used=100,
        composite=composite,
        reason="",
        received_at=f"2026-04-18T00:00:00.{seq:03d}Z",
    )


def _rows_for_rounds(rounds: list[dict[int, float]], start_seq: int = 0) -> list[RoundScoreRow]:
    """Flatten a list of per-round {uid: composite} dicts into ordered rows."""
    out: list[RoundScoreRow] = []
    seq = start_seq
    for i, round_scores in enumerate(rounds):
        for uid, composite in round_scores.items():
            out.append(_row(f"round-{i}", uid, composite, seq=seq))
            seq += 1
    return out


def _reference_ema(rounds: list[dict[int, float]], alpha: float = 0.3) -> dict[int, float]:
    """Run the retired EMATracker algorithm inline as the reference oracle."""
    ema: dict[int, float] = {}
    for round_scores in rounds:
        finite = {uid: s for uid, s in round_scores.items() if math.isfinite(s)}
        for uid, score in finite.items():
            if uid in ema:
                ema[uid] = alpha * score + (1 - alpha) * ema[uid]
            else:
                ema[uid] = score
        for uid in list(ema.keys()):
            if uid not in finite:
                ema[uid] = (1 - alpha) * ema[uid]
                if ema[uid] < 1e-6:
                    del ema[uid]

    total = sum(ema.values())
    if total > 0:
        return {uid: s / total for uid, s in ema.items()}
    n = len(ema)
    if n > 0:
        return {uid: 1.0 / n for uid in ema}
    return {}


def test_empty_rows_returns_empty_dict() -> None:
    """No rows yields an empty weight dict."""
    assert compute_window_ema([]) == {}


def test_single_round_equals_first_composites_normalized() -> None:
    """One round with three miners produces normalized composites as weights."""
    rows = _rows_for_rounds([{1: 0.4, 2: 0.3, 3: 0.3}])
    weights = compute_window_ema(rows)
    total = 0.4 + 0.3 + 0.3
    assert weights[1] == 0.4 / total
    assert weights[2] == 0.3 / total
    assert weights[3] == 0.3 / total


def test_absent_miner_decays() -> None:
    """A miner missing from the next round decays by (1 - alpha)."""
    rows = _rows_for_rounds([{1: 0.8}, {2: 0.5}])
    weights = compute_window_ema(rows, alpha=0.3)

    expected_1 = 0.8 * (1 - 0.3)
    expected_2 = 0.5
    total = expected_1 + expected_2
    assert weights[1] == expected_1 / total
    assert weights[2] == expected_2 / total


def test_matches_old_ema_tracker_bit_identical() -> None:
    """compute_window_ema matches the retired EMATracker to 10 decimal places."""
    rounds = [
        {1: 0.9, 2: 0.6, 3: 0.3},
        {1: 0.85, 2: 0.65},
        {1: 0.7, 3: 0.4, 4: 0.2},
        {2: 0.55, 3: 0.45},
        {1: 0.95, 2: 0.5, 3: 0.5, 4: 0.1},
    ]
    rows = _rows_for_rounds(rounds)

    got = compute_window_ema(rows, alpha=0.3)
    expected = _reference_ema(rounds, alpha=0.3)

    assert set(got.keys()) == set(expected.keys())
    for uid in expected:
        assert round(got[uid] - expected[uid], 10) == 0, f"UID {uid} differs: {got[uid]} vs {expected[uid]}"


def test_prunes_below_threshold() -> None:
    """A miner absent for many rounds decays below 1e-6 and disappears."""
    rounds: list[dict[int, float]] = [{1: 0.8, 2: 0.5}]
    for _ in range(60):
        rounds.append({2: 0.5})

    rows = _rows_for_rounds(rounds)
    weights = compute_window_ema(rows, alpha=0.3)
    assert 1 not in weights
    assert 2 in weights


def test_all_zero_ema_returns_empty() -> None:
    """When every EMA entry is zero, the contract is empty dict, NOT
    uniform weights. The caller uses emptiness to trigger chain fallback.
    """
    rows = _rows_for_rounds([{1: 0.0, 2: 0.0, 3: 0.0}])
    result = compute_window_ema(rows)
    assert result == {}, f"All-zero composites must return empty dict for caller fallback, got {result}"


def test_nonfinite_composite_treated_as_absent() -> None:
    """A NaN composite decays that UID's prior EMA instead of corrupting it."""
    rows = _rows_for_rounds(
        [
            {1: 0.8, 2: 0.5},
            {1: float("nan"), 2: 0.6},
        ]
    )
    weights = compute_window_ema(rows, alpha=0.3)

    expected_1 = 0.8 * (1 - 0.3)
    expected_2 = 0.3 * 0.6 + 0.7 * 0.5
    total = expected_1 + expected_2
    assert weights[1] == expected_1 / total
    assert weights[2] == expected_2 / total
