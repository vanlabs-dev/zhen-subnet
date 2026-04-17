"""Unit tests for validator state persistence."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from validator.state import load_state, save_state


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    """Save state then load it, verify all fields match."""
    state_path = tmp_path / "state.json"
    ema_scores = {2: 0.45, 4: 0.35, 5: 0.20}

    save_state(round_count=5, ema_scores=ema_scores, round_id="round-4", state_path=state_path)

    loaded = load_state(state_path=state_path)
    assert loaded is not None
    assert loaded["round_count"] == 5
    assert loaded["ema_scores"] == {2: 0.45, 4: 0.35, 5: 0.20}
    assert loaded["last_round_id"] == "round-4"
    assert "last_round_timestamp" in loaded

    import protocol

    assert loaded["spec_version"] == protocol.__spec_version__


def test_load_missing_file(tmp_path: Path) -> None:
    """Returns None when no state file exists."""
    state_path = tmp_path / "nonexistent.json"
    assert load_state(state_path=state_path) is None


def test_load_corrupted_file(tmp_path: Path) -> None:
    """Returns None on corrupted JSON without crashing."""
    state_path = tmp_path / "state.json"
    state_path.write_text("{garbage not json!!", encoding="utf-8")

    assert load_state(state_path=state_path) is None


def test_load_missing_keys(tmp_path: Path) -> None:
    """Returns None when required keys are missing."""
    state_path = tmp_path / "state.json"
    state_path.write_text('{"round_count": 1}', encoding="utf-8")

    assert load_state(state_path=state_path) is None


def test_atomic_write_no_tmp_left(tmp_path: Path) -> None:
    """Verify .tmp file is cleaned up after successful write."""
    state_path = tmp_path / "state.json"
    save_state(round_count=1, ema_scores={0: 0.5}, round_id="round-0", state_path=state_path)

    tmp_file = state_path.with_suffix(".json.tmp")
    assert not tmp_file.exists()
    assert state_path.exists()


def test_rejects_incompatible_spec_version(tmp_path: Path) -> None:
    """State saved with a different spec_version is discarded on load."""
    state_path = tmp_path / "state.json"

    # Save with current spec_version
    save_state(round_count=3, ema_scores={1: 0.8}, round_id="round-2", state_path=state_path)

    # Simulate a spec_version bump to an unrelated value
    with patch("validator.state.protocol") as mock_protocol:
        mock_protocol.__spec_version__ = 99
        loaded = load_state(state_path=state_path)

    assert loaded is None
