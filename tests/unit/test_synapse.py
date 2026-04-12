"""Unit tests for CalibrationSynapse.

Tests synapse creation, defaults, result fields, and serialization.
Skipped if bittensor is not installed.
"""

from __future__ import annotations

import pytest

try:
    import bittensor  # noqa: F401

    HAS_BITTENSOR = True
except ImportError:
    HAS_BITTENSOR = False

pytestmark = pytest.mark.skipif(not HAS_BITTENSOR, reason="bittensor not installed")


def test_synapse_creation() -> None:
    """Create CalibrationSynapse with challenge fields, verify fields set."""
    from protocol.synapse import CalibrationSynapse

    synapse = CalibrationSynapse(
        test_case_id="bestest_hydronic_heat_pump",
        manifest_version="v1.0.0",
        training_data={"zone_air_temperature_C": [20.0, 21.0, 20.5]},
        parameter_names=["wall_r_value", "roof_r_value"],
        parameter_bounds={"wall_r_value": [0.5, 10.0], "roof_r_value": [0.5, 12.0]},
        simulation_budget=500,
        round_id="round-42",
        train_start_hour=0,
        train_end_hour=336,
    )
    assert synapse.test_case_id == "bestest_hydronic_heat_pump"
    assert synapse.manifest_version == "v1.0.0"
    assert synapse.simulation_budget == 500
    assert synapse.round_id == "round-42"
    assert len(synapse.parameter_names) == 2


def test_synapse_defaults() -> None:
    """Create empty synapse, verify all defaults."""
    from protocol.synapse import CalibrationSynapse

    synapse = CalibrationSynapse()
    assert synapse.test_case_id == ""
    assert synapse.manifest_version == ""
    assert synapse.training_data == {}
    assert synapse.parameter_names == []
    assert synapse.parameter_bounds == {}
    assert synapse.simulation_budget == 1000
    assert synapse.round_id == ""
    assert synapse.train_start_hour == 0
    assert synapse.train_end_hour == 0


def test_synapse_result_fields() -> None:
    """Set result fields, verify they serialize."""
    from protocol.synapse import CalibrationSynapse

    synapse = CalibrationSynapse()
    synapse.calibrated_params = {"wall_r_value": 3.5, "roof_r_value": 5.0}
    synapse.simulations_used = 200
    synapse.training_cvrmse = 0.032
    synapse.metadata = {"algorithm": "bayesian"}

    assert synapse.calibrated_params["wall_r_value"] == 3.5
    assert synapse.simulations_used == 200
    assert synapse.training_cvrmse == 0.032


def test_synapse_roundtrip() -> None:
    """Create synapse, serialize to dict, deserialize back, verify fields."""
    from protocol.synapse import CalibrationSynapse

    original = CalibrationSynapse(
        test_case_id="test_case_1",
        round_id="round-7",
        simulation_budget=800,
        parameter_names=["param_a"],
        parameter_bounds={"param_a": [1.0, 10.0]},
    )
    original.calibrated_params = {"param_a": 5.5}
    original.simulations_used = 150

    # Serialize via Pydantic
    data = original.model_dump()
    restored = CalibrationSynapse(**data)

    assert restored.test_case_id == "test_case_1"
    assert restored.round_id == "round-7"
    assert restored.simulation_budget == 800
    assert restored.calibrated_params == {"param_a": 5.5}
    assert restored.simulations_used == 150


def test_synapse_optional_results() -> None:
    """Result fields should be None by default."""
    from protocol.synapse import CalibrationSynapse

    synapse = CalibrationSynapse()
    assert synapse.calibrated_params is None
    assert synapse.simulations_used is None
    assert synapse.training_cvrmse is None
    assert synapse.metadata is None
