"""Calibration algorithms: Bayesian optimization, evolutionary, and surrogate methods."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CalibrationOutput:
    """Container for calibration results returned to the validator."""

    calibrated_params: dict[str, float]
    simulations_used: int
    training_cvrmse: float
    metadata: dict[str, Any] = field(default_factory=dict)
