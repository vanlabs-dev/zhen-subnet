"""CalibrationSynapse definition.

Single synapse for calibration rounds. Validator fills challenge fields
(test case ID, training data, parameter bounds, simulation budget).
Miner fills result fields (calibrated parameters, simulation count,
training CVRMSE, metadata).
"""

from __future__ import annotations

import importlib.util

_HAS_BITTENSOR = importlib.util.find_spec("bittensor") is not None

if _HAS_BITTENSOR:
    import bittensor as bt

    class CalibrationSynapse(bt.Synapse):  # type: ignore[misc]
        """Single synapse for calibration rounds.

        Validator fills challenge fields. Miner fills result fields.
        Uses Pydantic via bt.Synapse; all fields need defaults.
        """

        # Challenge fields (validator fills)
        test_case_id: str = ""
        manifest_version: str = ""
        training_data: dict[str, list[float]] = {}
        parameter_names: list[str] = []
        parameter_bounds: dict[str, list[float]] = {}
        simulation_budget: int = 1000
        round_id: str = ""
        train_start_hour: int = 0
        train_end_hour: int = 0

        # Result fields (miner fills, Optional)
        calibrated_params: dict[str, float] | None = None
        simulations_used: int | None = None
        training_cvrmse: float | None = None
        metadata: dict[str, object] | None = None

else:
    # Bittensor not available (e.g. Windows dev environment)
    # Provide a lightweight stub for import compatibility
    from dataclasses import dataclass, field

    @dataclass
    class CalibrationSynapse:  # type: ignore[no-redef]
        """Stub CalibrationSynapse for environments without bittensor."""

        # Challenge fields
        test_case_id: str = ""
        manifest_version: str = ""
        training_data: dict[str, list[float]] = field(default_factory=dict)
        parameter_names: list[str] = field(default_factory=list)
        parameter_bounds: dict[str, list[float]] = field(default_factory=dict)
        simulation_budget: int = 1000
        round_id: str = ""
        train_start_hour: int = 0
        train_end_hour: int = 0

        # Result fields
        calibrated_params: dict[str, float] | None = None
        simulations_used: int | None = None
        training_cvrmse: float | None = None
        metadata: dict[str, object] | None = None
