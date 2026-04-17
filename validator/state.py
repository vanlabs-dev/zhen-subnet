"""Validator state persistence for crash recovery.

Saves EMA scores and round count to ~/.zhen/validator_state.json
after each round. Loads on startup to resume from last known state.
Uses atomic writes (tmp + rename) to prevent corruption on crash.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import protocol

logger = logging.getLogger(__name__)

DEFAULT_STATE_PATH = Path.home() / ".zhen" / "validator_state.json"

REQUIRED_KEYS = {"round_count", "ema_scores", "last_round_id", "last_round_timestamp", "spec_version"}


def save_state(
    round_count: int,
    ema_scores: dict[int, float],
    round_id: str,
    state_path: Path | None = None,
) -> None:
    """Save validator state to disk.

    Writes atomically: write to a .tmp file first, then os.replace()
    to the final path. os.replace() is atomic on both Linux and Windows.

    Args:
        round_count: Current round number.
        ema_scores: EMA tracker scores dict (UID to score).
        round_id: Last completed round ID string.
        state_path: Override path for testing. Defaults to ~/.zhen/validator_state.json.
    """
    path = state_path or DEFAULT_STATE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    state = {
        "round_count": round_count,
        "ema_scores": {str(uid): score for uid, score in ema_scores.items()},
        "last_round_id": round_id,
        "last_round_timestamp": datetime.now(timezone.utc).isoformat(),
        "spec_version": protocol.__spec_version__,
    }

    tmp_path = path.with_suffix(".json.tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(str(tmp_path), str(path))
        logger.info(f"State saved: round {round_count}, {len(ema_scores)} miners tracked")
    except Exception as e:
        logger.error(f"Failed to save state: {e}")
        # Clean up tmp file on failure
        with contextlib.suppress(Exception):
            tmp_path.unlink(missing_ok=True)


def load_state(state_path: Path | None = None) -> dict[str, Any] | None:
    """Load validator state from disk.

    Args:
        state_path: Override path for testing. Defaults to ~/.zhen/validator_state.json.

    Returns:
        Parsed state dict with int UID keys in ema_scores,
        or None if no state file exists or it is corrupted.
    """
    path = state_path or DEFAULT_STATE_PATH

    if not path.exists():
        return None

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Corrupted state file, starting fresh: {e}")
        return None

    if not REQUIRED_KEYS.issubset(raw.keys()):
        missing = REQUIRED_KEYS - raw.keys()
        logger.warning(f"State file missing keys {missing}, starting fresh")
        return None

    # Convert string UID keys back to int
    try:
        raw["ema_scores"] = {int(uid): float(score) for uid, score in raw["ema_scores"].items()}
    except (ValueError, TypeError, AttributeError) as e:
        logger.warning(f"Invalid ema_scores in state file, starting fresh: {e}")
        return None

    # Validate EMA score range. Normalized scores from ScoringEngine.compute() sum to 1.0,
    # so no individual score should exceed 1.0 in normal operation. Out-of-range values
    # indicate file tampering or a bug; refuse to load rather than poison the next round.
    for uid, score in raw["ema_scores"].items():
        if score < 0 or score > 1.0:
            logger.warning(f"EMA score for UID {uid} out of range ({score}), state may be tampered. Starting fresh.")
            return None

    # Reject state from incompatible spec versions
    saved_version = raw.get("spec_version", 0)
    if saved_version != protocol.__spec_version__:
        logger.warning(
            f"State file spec_version ({saved_version}) does not match "
            f"current ({protocol.__spec_version__}), starting fresh"
        )
        return None

    result: dict[str, Any] = raw
    return result
