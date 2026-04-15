"""Unit tests for EMA tracker decay and pruning behavior."""

from __future__ import annotations

from scoring.ema import EMATracker


def test_absent_uids_decay_each_round() -> None:
    """UIDs not present in round_scores decay by (1 - alpha) per round."""
    tracker = EMATracker(alpha=0.3)

    # Round 1: miner 0 scores 0.8
    tracker.update({0: 0.8})
    assert tracker.scores[0] == 0.8

    # Round 2: miner 0 absent, should decay to 0.8 * 0.7 = 0.56
    tracker.update({1: 0.6})
    assert abs(tracker.scores[0] - 0.8 * 0.7) < 1e-9
    assert 1 in tracker.scores


def test_absent_uids_pruned_below_threshold() -> None:
    """UIDs that decay below 1e-6 get removed from tracking."""
    tracker = EMATracker(alpha=0.3)

    # Seed with a very small score
    tracker.scores[99] = 1e-5

    # One decay round should push it below 1e-6: 1e-5 * 0.7 = 7e-6 (still above)
    tracker.update({0: 1.0})
    assert 99 in tracker.scores

    # Keep decaying until pruned
    for _ in range(10):
        tracker.update({0: 1.0})

    assert 99 not in tracker.scores


def test_active_uids_unaffected_by_decay() -> None:
    """UIDs present in round_scores are blended normally, not decayed."""
    tracker = EMATracker(alpha=0.3)

    tracker.update({0: 0.8, 1: 0.6})
    score_0_r1 = tracker.scores[0]
    score_1_r1 = tracker.scores[1]

    # Round 2: both active again
    tracker.update({0: 0.9, 1: 0.5})

    expected_0 = 0.3 * 0.9 + 0.7 * score_0_r1
    expected_1 = 0.3 * 0.5 + 0.7 * score_1_r1
    assert abs(tracker.scores[0] - expected_0) < 1e-9
    assert abs(tracker.scores[1] - expected_1) < 1e-9


def test_decay_does_not_affect_weight_of_active_miners() -> None:
    """After an absent miner decays, active miners reclaim its weight share."""
    tracker = EMATracker(alpha=0.3)

    # Round 1: two miners
    tracker.update({0: 0.8, 1: 0.6})

    # Round 2: miner 0 goes offline
    tracker.update({1: 0.6})

    weights = tracker.get_weights()
    # Miner 1 should have more weight than miner 0 now
    assert weights[1] > weights[0]

    # After many rounds absent, miner 0 should be pruned entirely
    for _ in range(50):
        tracker.update({1: 0.6})

    weights = tracker.get_weights()
    assert 0 not in weights
    assert abs(weights[1] - 1.0) < 1e-9
