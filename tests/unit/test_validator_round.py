"""Unit tests for test case selection and split generation.

Tests determinism, bounds checking, and period length constraints.
"""

from __future__ import annotations

from validator.round import split_generator, test_case_selector

MANIFEST = {
    "version": "v1.0.0",
    "test_cases": [
        {"id": "case_a", "simplified_model_type": "rc_network", "parameter_count": 6, "scoring_outputs": ["temp"]},
        {"id": "case_b", "simplified_model_type": "rc_network", "parameter_count": 4, "scoring_outputs": ["temp"]},
        {"id": "case_c", "simplified_model_type": "rc_network", "parameter_count": 8, "scoring_outputs": ["temp"]},
        {"id": "case_d", "simplified_model_type": "rc_network", "parameter_count": 5, "scoring_outputs": ["temp"]},
        {"id": "case_e", "simplified_model_type": "rc_network", "parameter_count": 7, "scoring_outputs": ["temp"]},
    ],
}


def test_deterministic_test_case_selection() -> None:
    """Same round_id always picks same test case."""
    result1 = test_case_selector.select("round-42", MANIFEST)
    result2 = test_case_selector.select("round-42", MANIFEST)
    assert result1["id"] == result2["id"]


def test_different_rounds_different_selection() -> None:
    """Different round_ids can pick different cases with enough test cases."""
    selections = set()
    for i in range(100):
        tc = test_case_selector.select(f"round-{i}", MANIFEST)
        selections.add(tc["id"])
    # With 5 test cases and 100 rounds, we should hit at least 2 different ones
    assert len(selections) >= 2


def test_split_within_bounds() -> None:
    """Train/test periods never exceed total_hours."""
    total = 8760
    for i in range(50):
        (train_start, train_end), (test_start, test_end) = split_generator.compute(
            f"round-{i}", "case_a", total_hours=total
        )
        assert train_start >= 0
        assert train_end <= total
        assert test_start >= 0
        assert test_end <= total


def test_split_deterministic() -> None:
    """Same inputs always produce same split."""
    split1 = split_generator.compute("round-7", "case_a")
    split2 = split_generator.compute("round-7", "case_a")
    assert split1 == split2


def test_split_no_overlap() -> None:
    """Training and test periods do not overlap."""
    for i in range(50):
        (train_start, train_end), (test_start, test_end) = split_generator.compute(f"round-{i}", "case_a")
        assert train_end <= test_start


def test_train_length() -> None:
    """Training period is exactly 336 hours."""
    (train_start, train_end), _ = split_generator.compute("round-1", "case_a")
    assert train_end - train_start == 336


def test_test_length() -> None:
    """Test period is exactly 168 hours."""
    _, (test_start, test_end) = split_generator.compute("round-1", "case_a")
    assert test_end - test_start == 168
