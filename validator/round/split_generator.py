"""Deterministic train/test split computation.

Computes training and held-out time periods from the round ID and test case ID,
ensuring all validators use identical splits for consistent scoring.
"""

from __future__ import annotations

import hashlib

TRAIN_HOURS = 336  # 2 weeks
TEST_HOURS = 168  # 1 week
TOTAL_WINDOW = TRAIN_HOURS + TEST_HOURS  # 504 hours needed


def compute(round_id: str, test_case_id: str, total_hours: int = 8760) -> tuple[tuple[int, int], tuple[int, int]]:
    """Compute deterministic train/test split for a round.

    Uses SHA-256 hash of "{round_id}:{test_case_id}" to determine
    the start offset within the year. Training period is 336 hours
    (2 weeks), test period is 168 hours (1 week) immediately after.

    Args:
        round_id: Unique identifier for the current round.
        test_case_id: Identifier of the selected test case.
        total_hours: Total hours available in the dataset (default 8760 = 1 year).

    Returns:
        Tuple of ((train_start, train_end), (test_start, test_end)) in hours.
        Both intervals are [start, end) half-open.

    Raises:
        ValueError: If total_hours is too small for a training + test window.
    """
    if total_hours < TOTAL_WINDOW:
        raise ValueError(
            f"total_hours ({total_hours}) must be at least {TOTAL_WINDOW} "
            f"to fit training ({TRAIN_HOURS}h) + test ({TEST_HOURS}h)"
        )

    seed = f"{round_id}:{test_case_id}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    hash_int = int(digest, 16)

    max_start = total_hours - TOTAL_WINDOW
    start_offset = hash_int % (max_start + 1)

    train_start = start_offset
    train_end = train_start + TRAIN_HOURS
    test_start = train_end
    test_end = test_start + TEST_HOURS

    return (train_start, train_end), (test_start, test_end)
