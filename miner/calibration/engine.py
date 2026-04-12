"""Calibration orchestration engine.

Coordinates the optimization loop: receives a challenge, selects the
calibration algorithm, runs the optimization, and packages the result.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from miner.calibration import CalibrationOutput
from miner.calibration.bayesian import BayesianCalibrator


class CalibrationEngine:
    """Dispatches calibration challenges to the selected algorithm."""

    def __init__(self, algorithm: str = "bayesian") -> None:
        """Initialize the calibration engine.

        Args:
            algorithm: Algorithm to use. Currently only "bayesian" is supported.
        """
        self.algorithm = algorithm

    async def calibrate(self, challenge: dict[str, Any]) -> CalibrationOutput:
        """Run calibration for a given challenge.

        Extracts challenge parameters and dispatches to the configured
        calibration algorithm.

        Args:
            challenge: Challenge dict with test_case_id, training_data,
                parameter_names, parameter_bounds, simulation_budget,
                train_start_hour, train_end_hour.

        Returns:
            CalibrationOutput with optimized parameters.
        """
        test_case_id: str = challenge["test_case_id"]
        training_data: dict[str, list[float]] = challenge["training_data"]
        parameter_names: list[str] = challenge["parameter_names"]
        parameter_bounds: dict[str, list[float]] = challenge["parameter_bounds"]
        simulation_budget: int = challenge.get("simulation_budget", 1000)
        train_start: int = challenge["train_start_hour"]
        train_end: int = challenge["train_end_hour"]

        # Get scoring outputs from local config
        scoring_outputs = self._get_scoring_outputs(test_case_id)

        if self.algorithm == "bayesian":
            calibrator = BayesianCalibrator()
            return calibrator.calibrate(
                test_case_id=test_case_id,
                training_data=training_data,
                parameter_names=parameter_names,
                parameter_bounds=parameter_bounds,
                simulation_budget=simulation_budget,
                train_start=train_start,
                train_end=train_end,
                scoring_outputs=scoring_outputs,
            )
        else:
            raise ValueError(f"Unknown calibration algorithm: {self.algorithm}")

    def _get_scoring_outputs(self, test_case_id: str) -> list[str]:
        """Load scoring outputs from the local test case config.

        Args:
            test_case_id: Test case identifier.

        Returns:
            List of scoring output names.
        """
        config_path = Path.home() / ".zhen" / "test_cases" / test_case_id / "config.json"
        config: dict[str, Any] = json.loads(config_path.read_text(encoding="utf-8"))
        return list(config["scoring_outputs"])
