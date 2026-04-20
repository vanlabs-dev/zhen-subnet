"""Verification engine for miner submissions.

Runs the simplified model with each miner's calibrated parameters on the
held-out period, compares predictions against complex emulator ground truth,
and computes per-miner CVRMSE, NMBE, and R-squared metrics. Supports parallel
verification with configurable concurrency via asyncio semaphore.
"""

from __future__ import annotations

import asyncio
import json
import math
from pathlib import Path
from typing import Any

from scoring.metrics import compute_cvrmse, compute_nmbe, compute_r_squared
from simulation.rc_network import RCNetworkBackend
from validator.round.orchestrator import validate_config_bounds
from validator.scoring.engine import VerifiedResult


class VerificationEngine:
    """Verifies miner submissions by running simplified model with their params."""

    TIMEOUT_SECONDS: int = 300
    MAX_PARALLEL: int = 8

    def __init__(self, timeout_seconds: int | None = None) -> None:
        """Initialize the verification engine.

        Args:
            timeout_seconds: Override default timeout per verification.
        """
        if timeout_seconds is not None:
            self.TIMEOUT_SECONDS = timeout_seconds

    async def verify_all(
        self,
        results: dict[int, dict[str, Any]],
        test_case: dict[str, Any],
        test_period: tuple[int, int],
        held_out_data: dict[str, list[float]],
        sim_budget: int = 1000,
    ) -> dict[int, VerifiedResult]:
        """Verify all miner submissions in parallel.

        Args:
            results: Mapping of miner UID to submission dict containing
                "calibrated_params" and "simulations_used".
            test_case: Test case dict with parameter_bounds, scoring_outputs, etc.
            test_period: (start_hour, end_hour) for the held-out period.
            held_out_data: Ground truth measurements for the test period.
            sim_budget: Maximum simulation budget allowed.

        Returns:
            Mapping of miner UID to VerifiedResult.
        """
        semaphore = asyncio.Semaphore(self.MAX_PARALLEL)

        async def bounded_verify(miner_uid: int, submission: dict[str, Any]) -> tuple[int, VerifiedResult]:
            """Run a single verification with concurrency limit and timeout."""
            async with semaphore:
                try:
                    result = await asyncio.wait_for(
                        self._verify_single(submission, test_case, test_period, held_out_data),
                        timeout=self.TIMEOUT_SECONDS,
                    )
                    return miner_uid, result
                except asyncio.TimeoutError:
                    return miner_uid, VerifiedResult(
                        reason="SIMULATION_TIMEOUT",
                        detail=f"Verification exceeded {self.TIMEOUT_SECONDS}s",
                    )
                except Exception as e:
                    return miner_uid, VerifiedResult(
                        reason="SIMULATION_CRASHED",
                        detail=str(e),
                    )

        tasks = [bounded_verify(uid, sub) for uid, sub in results.items()]
        completed = await asyncio.gather(*tasks, return_exceptions=True)

        verified: dict[int, VerifiedResult] = {}
        for item in completed:
            if isinstance(item, BaseException):
                continue
            uid, result = item
            verified[uid] = result

        return verified

    async def _verify_single(
        self,
        submission: dict[str, Any],
        test_case: dict[str, Any],
        test_period: tuple[int, int],
        held_out_data: dict[str, list[float]],
    ) -> VerifiedResult:
        """Verify a single miner submission.

        Validates parameters are within bounds, runs the simplified model,
        and computes metrics against held-out data.

        Args:
            submission: Miner submission with "calibrated_params" and "simulations_used".
            test_case: Test case configuration dict.
            test_period: (start_hour, end_hour) tuple.
            held_out_data: Ground truth measurement data.

        Returns:
            VerifiedResult with metrics or failure reason.
        """
        calibrated_params = submission["calibrated_params"]
        simulations_used = submission.get("simulations_used", 0)
        parameter_bounds = test_case["parameter_bounds"]

        # Clamp simulations_used to [0, simulation_budget] so negative values cannot
        # game convergence and runaway reports cannot underflow the normalization.
        simulations_used = max(0, min(simulations_used, test_case.get("simulation_budget", 1000)))

        # Validate parameters within bounds
        for param, value in calibrated_params.items():
            if param not in parameter_bounds:
                return VerifiedResult(
                    reason="INVALID_PARAMS",
                    detail=f"Unknown parameter: {param}",
                )
            bounds = parameter_bounds[param]
            if not (bounds[0] <= value <= bounds[1]):
                return VerifiedResult(
                    reason="INVALID_PARAMS",
                    detail=f"{param}={value} outside bounds [{bounds[0]}, {bounds[1]}]",
                )

        # Check for near-default parameter submission (anti-gaming)
        config_defaults: dict[str, float] = test_case.get("defaults", {})
        if config_defaults:
            all_near_default = True
            for param, value in calibrated_params.items():
                default_val = config_defaults.get(param)
                if default_val is not None and default_val != 0:
                    relative_diff = abs(value - default_val) / abs(default_val)
                    if relative_diff > 0.001:
                        all_near_default = False
                        break
                elif default_val == 0:
                    if abs(value) > 1e-6:
                        all_near_default = False
                        break
            if all_near_default:
                return VerifiedResult(
                    reason="DEFAULT_PARAMS",
                    detail="Submitted parameters are within 0.1% of config defaults. Run actual calibration.",
                )

        # Load test case config and run simplified model
        config = self._load_config(test_case["id"])
        rc = RCNetworkBackend(config, calibrated_params)
        predictions = rc.run(start_hour=test_period[0], end_hour=test_period[1])

        # Extract scoring outputs
        scoring_outputs = test_case["scoring_outputs"]
        predicted_values = predictions.get_outputs(scoring_outputs)

        # Guard against NaN/Inf from simulation (e.g., division by near-zero parameters)
        for key, values in predicted_values.items():
            if not all(math.isfinite(v) for v in values):
                return VerifiedResult(
                    reason="SIMULATION_NAN",
                    detail=f"RC model produced non-finite values in {key}",
                )

        measured_values = {k: held_out_data[k] for k in scoring_outputs if k in held_out_data}

        # Compute metrics
        cvrmse = compute_cvrmse(predicted_values, measured_values)
        nmbe = compute_nmbe(predicted_values, measured_values)
        r_squared = compute_r_squared(predicted_values, measured_values)

        return VerifiedResult(
            cvrmse=cvrmse,
            nmbe=nmbe,
            r_squared=r_squared,
            simulations_used=simulations_used,
            calibrated_params=calibrated_params,
            predicted_values=predicted_values,
            measured_values=measured_values,
        )

    def _load_config(self, test_case_id: str) -> dict[str, Any]:
        """Load the test case config.json.

        Args:
            test_case_id: Test case identifier.

        Returns:
            Parsed config dict.

        Raises:
            ValueError: If parameter_bounds in the config are malformed.
        """
        config_path = Path.home() / ".zhen" / "test_cases" / test_case_id / "config.json"
        result: dict[str, Any] = json.loads(config_path.read_text(encoding="utf-8"))
        validate_config_bounds(result)
        return result
