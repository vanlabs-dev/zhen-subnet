"""Objective function for calibration optimization.

Runs ZhenSimulator with candidate parameters, compares predictions to
training data, and returns CVRMSE as the minimization target.
"""

from __future__ import annotations

from scoring.metrics import compute_cvrmse
from simulation.rc_network import RCNetworkBackend

PENALTY_VALUE = 10.0


class CalibrationObjective:
    """Objective function that the optimizer minimizes.

    Runs the simplified model with candidate parameters and returns
    CVRMSE against training data.
    """

    def __init__(
        self,
        test_case_id: str,
        train_start: int,
        train_end: int,
        training_data: dict[str, list[float]],
        scoring_outputs: list[str],
    ) -> None:
        """Initialize the objective function.

        Args:
            test_case_id: Test case identifier for loading config.
            train_start: Start hour of training period.
            train_end: End hour of training period.
            training_data: Ground truth measurements for the training period.
            scoring_outputs: Output names to compare (e.g. zone_air_temperature_C).
        """
        import json
        from pathlib import Path

        self.test_case_id = test_case_id
        self.train_start = train_start
        self.train_end = train_end
        self.training_data = training_data
        self.scoring_outputs = scoring_outputs
        self.sim_count = 0

        config_path = Path.home() / ".zhen" / "test_cases" / test_case_id / "config.json"
        self.config: dict[str, object] = json.loads(config_path.read_text(encoding="utf-8"))

    def __call__(self, param_values: list[float], param_names: list[str]) -> float:
        """Evaluate candidate parameters and return CVRMSE.

        Args:
            param_values: Parameter values in the same order as param_names.
            param_names: Names of calibratable parameters.

        Returns:
            CVRMSE value (lower is better). Returns PENALTY_VALUE on crash.
        """
        self.sim_count += 1

        try:
            params = dict(zip(param_names, param_values, strict=True))
            rc = RCNetworkBackend(self.config, params)
            result = rc.run(start_hour=self.train_start, end_hour=self.train_end)
            predicted = result.get_outputs(self.scoring_outputs)
            measured = {k: self.training_data[k] for k in self.scoring_outputs if k in self.training_data}

            if not predicted or not measured:
                return PENALTY_VALUE

            cvrmse = compute_cvrmse(predicted, measured)
            if not __import__("math").isfinite(cvrmse):
                return PENALTY_VALUE
            return cvrmse

        except Exception:
            return PENALTY_VALUE
