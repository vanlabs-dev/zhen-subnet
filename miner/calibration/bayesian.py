"""Bayesian optimization calibration using scikit-optimize.

Reference implementation that wraps ZhenSimulator with gp_minimize
to search the parameter space and minimize CVRMSE on training data.
"""

from __future__ import annotations

import math

from skopt import gp_minimize
from skopt.space import Real

from miner.calibration import CalibrationOutput
from miner.calibration.objective import CalibrationObjective


class BayesianCalibrator:
    """Reference calibrator using Gaussian Process-based Bayesian optimization."""

    def __init__(
        self,
        n_calls: int = 500,
        n_initial_points: int = 20,
        random_state: int | None = None,
    ) -> None:
        """Initialize the Bayesian calibrator.

        Args:
            n_calls: Maximum number of objective evaluations.
            n_initial_points: Number of random initial evaluations before GP fitting.
            random_state: Seed for reproducibility. None means each instance uses
                a fresh random seed, producing different optimization trajectories.
                Set to a fixed integer only for testing or reproducibility studies.
        """
        self.n_calls = n_calls
        self.n_initial_points = n_initial_points
        self.random_state = random_state

    def calibrate(
        self,
        test_case_id: str,
        training_data: dict[str, list[float]],
        parameter_names: list[str],
        parameter_bounds: dict[str, list[float]],
        simulation_budget: int,
        train_start: int,
        train_end: int,
        scoring_outputs: list[str],
    ) -> CalibrationOutput:
        """Run Bayesian optimization to find best parameters.

        Args:
            test_case_id: Test case identifier.
            training_data: Ground truth measurements for training period.
            parameter_names: Ordered list of parameter names.
            parameter_bounds: Mapping of parameter name to [lower, upper] bounds.
            simulation_budget: Maximum simulations allowed by validator.
            train_start: Start hour of training period.
            train_end: End hour of training period.
            scoring_outputs: Output names to optimize against.

        Returns:
            CalibrationOutput with best parameters found.
        """
        # Validate bounds structure before constructing the search space.
        for name in parameter_names:
            if name not in parameter_bounds:
                raise ValueError(f"Missing bounds for parameter: {name}")
            bounds = parameter_bounds[name]
            if len(bounds) != 2:
                raise ValueError(f"Invalid bounds format for {name}: expected [lo, hi]")
            lo, hi = bounds
            if not (math.isfinite(lo) and math.isfinite(hi)):
                raise ValueError(f"Non-finite bounds for {name}: [{lo}, {hi}]")
            if lo >= hi:
                raise ValueError(f"Invalid bounds for {name}: lo ({lo}) >= hi ({hi})")

        # Build search space dimensions
        dimensions = []
        for name in parameter_names:
            lo, hi = parameter_bounds[name]
            dimensions.append(Real(lo, hi, name=name))

        # Create objective
        objective = CalibrationObjective(
            test_case_id=test_case_id,
            train_start=train_start,
            train_end=train_end,
            training_data=training_data,
            scoring_outputs=scoring_outputs,
        )

        # Cap calls at simulation budget
        effective_calls = min(simulation_budget, self.n_calls)
        effective_initial = min(self.n_initial_points, effective_calls)

        # Wrapper for skopt (only passes positional param_values)
        def skopt_objective(param_values: list[float]) -> float:
            """Wrapper matching skopt's expected signature."""
            return objective(param_values, parameter_names)

        # Run optimization
        result = gp_minimize(
            skopt_objective,
            dimensions,
            n_calls=effective_calls,
            n_initial_points=effective_initial,
            random_state=self.random_state,
        )

        # Package output
        best_params = dict(zip(parameter_names, result.x, strict=True))

        return CalibrationOutput(
            calibrated_params=best_params,
            simulations_used=objective.sim_count,
            training_cvrmse=float(result.fun),
            metadata={
                "algorithm": "bayesian_optimization",
                "library": "scikit-optimize",
                "n_calls": effective_calls,
                "n_initial_points": effective_initial,
            },
        )
