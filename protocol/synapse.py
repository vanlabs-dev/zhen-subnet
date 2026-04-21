"""CalibrationSynapse definition.

Single synapse for calibration rounds. Validator fills challenge fields
(test case ID, training data, parameter bounds, simulation budget).
Miner fills result fields (calibrated parameters, simulation count,
training CVRMSE, metadata).

NOTE: This file intentionally does NOT use `from __future__ import annotations`.
Pydantic (used by bt.Synapse) requires real type objects at class definition time,
not deferred string annotations.
"""

import importlib.util
import warnings
from typing import Optional

_HAS_BITTENSOR = importlib.util.find_spec("bittensor") is not None

warnings.filterwarnings(
    "ignore",
    message="Field name.*required_hash_fields.*shadows an attribute in parent.*Synapse",
)

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
        training_data: dict = {}
        parameter_names: list = []
        parameter_bounds: dict = {}
        simulation_budget: int = 1000
        round_id: str = ""
        train_start_hour: int = 0
        train_end_hour: int = 0

        # Result fields (miner fills, Optional)
        calibrated_params: Optional[dict] = None
        simulations_used: Optional[int] = None
        training_cvrmse: Optional[float] = None
        metadata: Optional[dict] = None

        # Validator-populated report field (spec v7). Carries the miner's own
        # CalibrationReport (serialized via CalibrationReport.to_dict()) after
        # verification. Miners MUST NOT populate this on submission; the
        # validator sets it per miner before the response is delivered back.
        # Older miners (pre-v7) that do not know about this field still
        # deserialize cleanly because it is optional with a None default.
        calibration_report: Optional[dict] = None

        required_hash_fields: list = [
            "test_case_id",
            "round_id",
            "train_start_hour",
            "train_end_hour",
            "training_data",
            "parameter_bounds",
            "simulation_budget",
            "manifest_version",
        ]

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
        training_data: dict = field(default_factory=dict)
        parameter_names: list = field(default_factory=list)
        parameter_bounds: dict = field(default_factory=dict)
        simulation_budget: int = 1000
        round_id: str = ""
        train_start_hour: int = 0
        train_end_hour: int = 0

        # Result fields
        calibrated_params: Optional[dict] = None
        simulations_used: Optional[int] = None
        training_cvrmse: Optional[float] = None
        metadata: Optional[dict] = None

        # Validator-populated report field (spec v7).
        calibration_report: Optional[dict] = None
