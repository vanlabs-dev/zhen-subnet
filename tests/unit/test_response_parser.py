"""Unit tests for the ResponseParser.

Tests response parsing without requiring bittensor.
Uses the stub CalibrationSynapse dataclass.
"""

from __future__ import annotations

from protocol.synapse import CalibrationSynapse
from validator.network.result_receiver import ResponseParser


def test_parse_valid_responses() -> None:
    """Mock responses with calibrated_params are extracted correctly."""
    parser = ResponseParser()

    r1 = CalibrationSynapse()
    r1.calibrated_params = {"wall_r_value": 3.5, "roof_r_value": 5.0}
    r1.simulations_used = 100
    r1.training_cvrmse = 0.03
    r1.metadata = {"algorithm": "bayesian"}

    r2 = CalibrationSynapse()
    r2.calibrated_params = {"wall_r_value": 4.0, "roof_r_value": 6.0}
    r2.simulations_used = 200
    r2.training_cvrmse = 0.05
    r2.metadata = {"algorithm": "cma-es"}

    submissions = parser.parse_responses([r1, r2], uids=[0, 1])

    assert len(submissions) == 2
    assert 0 in submissions
    assert 1 in submissions
    assert submissions[0]["calibrated_params"]["wall_r_value"] == 3.5
    assert submissions[1]["simulations_used"] == 200


def test_parse_empty_response() -> None:
    """Response with None calibrated_params is filtered out."""
    parser = ResponseParser()

    r1 = CalibrationSynapse()
    # calibrated_params is None by default (empty response)

    submissions = parser.parse_responses([r1], uids=[0])

    assert len(submissions) == 0


def test_parse_mixed_responses() -> None:
    """Mix of valid and empty responses; only valid ones returned."""
    parser = ResponseParser()

    valid = CalibrationSynapse()
    valid.calibrated_params = {"wall_r_value": 3.5}
    valid.simulations_used = 50
    valid.training_cvrmse = 0.04

    empty = CalibrationSynapse()
    # calibrated_params is None

    also_valid = CalibrationSynapse()
    also_valid.calibrated_params = {"wall_r_value": 7.0}
    also_valid.simulations_used = 300

    submissions = parser.parse_responses([valid, empty, also_valid], uids=[10, 20, 30])

    assert len(submissions) == 2
    assert 10 in submissions
    assert 20 not in submissions
    assert 30 in submissions
    assert submissions[10]["calibrated_params"]["wall_r_value"] == 3.5
    assert submissions[30]["simulations_used"] == 300


def test_oversized_metadata_discarded() -> None:
    """Metadata exceeding MAX_METADATA_BYTES is discarded, submission kept."""
    parser = ResponseParser()

    r = CalibrationSynapse()
    r.calibrated_params = {"wall_r_value": 3.5}
    r.simulations_used = 100
    r.training_cvrmse = 0.03
    r.metadata = {"payload": "x" * 100_000}

    submissions = parser.parse_responses([r], uids=[0])

    assert 0 in submissions
    assert submissions[0]["metadata"] is None
    assert submissions[0]["calibrated_params"]["wall_r_value"] == 3.5


def test_too_many_params_skipped() -> None:
    """Submissions with more than MAX_PARAMS calibrated params are excluded."""
    parser = ResponseParser()

    r = CalibrationSynapse()
    r.calibrated_params = {f"param_{i}": float(i) for i in range(100)}
    r.simulations_used = 50
    r.training_cvrmse = 0.02

    submissions = parser.parse_responses([r], uids=[0])

    assert 0 not in submissions
