"""Deterministic test case selection using hashlib.sha256.

Selects the next test case from the manifest based on the round ID,
ensuring all validators choose the same test case for a given round.
"""

from __future__ import annotations

import hashlib
from typing import Any


def select(round_id: str, manifest: dict[str, Any]) -> dict[str, Any]:
    """Select a test case deterministically based on round_id.

    Uses SHA-256 hash of the round_id to pick a test case index.
    All validators with the same manifest and round_id will select
    the same test case.

    Args:
        round_id: Unique identifier for the current round.
        manifest: Parsed manifest dict with a "test_cases" list.

    Returns:
        The selected test case dict from the manifest.

    Raises:
        ValueError: If manifest has no test cases.
    """
    test_cases = manifest["test_cases"]
    if not test_cases:
        raise ValueError("Manifest contains no test cases")

    digest = hashlib.sha256(round_id.encode("utf-8")).hexdigest()
    index = int(digest, 16) % len(test_cases)
    return dict(test_cases[index])
