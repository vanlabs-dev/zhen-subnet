"""Parse CalibrationSynapse responses from miners.

Extracts calibrated parameters and metadata from dendrite responses,
filtering out failed or empty submissions.
"""

from __future__ import annotations

import logging
from typing import Any

from protocol.synapse import CalibrationSynapse

logger = logging.getLogger(__name__)


class ResponseParser:
    """Parses dendrite responses into submission dicts for the orchestrator."""

    def parse_responses(self, responses: list[CalibrationSynapse], uids: list[int]) -> dict[int, dict[str, Any]]:
        """Extract valid miner submissions from synapse responses.

        Args:
            responses: List of CalibrationSynapse responses from dendrite.
            uids: List of miner UIDs corresponding to each response.

        Returns:
            Dict mapping miner UID to submission dict with calibrated_params
            and simulations_used. Only includes miners that returned results.
        """
        submissions: dict[int, dict[str, Any]] = {}

        for uid, response in zip(uids, responses, strict=True):
            if response.calibrated_params is None:
                logger.debug(f"Miner {uid}: no calibrated_params in response")
                continue

            submissions[uid] = {
                "calibrated_params": response.calibrated_params,
                "simulations_used": response.simulations_used or 0,
                "training_cvrmse": response.training_cvrmse,
                "metadata": response.metadata,
            }

        logger.info(f"Parsed {len(submissions)}/{len(responses)} valid responses")
        return submissions
