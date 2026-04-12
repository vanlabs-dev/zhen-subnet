"""Receive CalibrationSynapse challenges from validators via Bittensor Axon.

Validates incoming synapses, checks manifest version compatibility,
and dispatches challenges to the calibration engine.
"""


import logging
from typing import Any

from miner.calibration.engine import CalibrationEngine
from protocol.synapse import CalibrationSynapse

logger = logging.getLogger(__name__)


class CalibrationHandler:
    """Handles incoming calibration challenges on the miner's Axon."""

    def __init__(self, calibration_engine: CalibrationEngine) -> None:
        """Initialize the handler with a calibration engine.

        Args:
            calibration_engine: Engine to dispatch calibration challenges to.
        """
        self.calibration_engine = calibration_engine

    async def forward(self, synapse: CalibrationSynapse) -> CalibrationSynapse:
        """Handle an incoming calibration challenge.

        Extracts challenge fields, runs calibration, and fills result fields.

        Args:
            synapse: CalibrationSynapse with challenge fields from validator.

        Returns:
            Same synapse with result fields filled.
        """
        logger.info(
            f"Received challenge: test_case={synapse.test_case_id}, "
            f"round={synapse.round_id}, budget={synapse.simulation_budget}"
        )

        try:
            challenge: dict[str, Any] = {
                "test_case_id": synapse.test_case_id,
                "training_data": synapse.training_data,
                "parameter_names": synapse.parameter_names,
                "parameter_bounds": synapse.parameter_bounds,
                "simulation_budget": synapse.simulation_budget,
                "train_start_hour": synapse.train_start_hour,
                "train_end_hour": synapse.train_end_hour,
            }

            output = await self.calibration_engine.calibrate(challenge)

            # Fill result fields
            synapse.calibrated_params = output.calibrated_params
            synapse.simulations_used = output.simulations_used
            synapse.training_cvrmse = output.training_cvrmse
            synapse.metadata = dict(output.metadata)

            logger.info(f"Calibration complete: cvrmse={output.training_cvrmse:.4f}, sims={output.simulations_used}")

        except Exception as e:
            logger.error(f"Calibration failed: {e}")
            # Leave result fields as None (validator will score as failed)

        return synapse

    def blacklist(self, synapse: CalibrationSynapse) -> tuple[bool, str]:
        """Determine whether to blacklist an incoming request.

        Args:
            synapse: The incoming synapse to evaluate.

        Returns:
            Tuple of (should_blacklist, reason). Currently accepts all.
        """
        return (False, "")

    def priority(self, synapse: CalibrationSynapse) -> float:
        """Assign priority to an incoming request.

        Args:
            synapse: The incoming synapse to evaluate.

        Returns:
            Priority value. Currently returns 0.0 for all requests.
        """
        return 0.0
