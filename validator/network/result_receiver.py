"""Parse CalibrationSynapse responses from miners.

Extracts calibrated parameters and metadata from dendrite responses,
filtering out failed or empty submissions.
"""

import logging
import sys
from typing import Any

from protocol.synapse import CalibrationSynapse

logger = logging.getLogger(__name__)


MAX_METADATA_BYTES: int = 10_000  # 10 KB
MAX_PARAMS: int = 50


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

        if len(uids) != len(responses):
            logger.warning(f"UID/response count mismatch: {len(uids)} uids, {len(responses)} responses")

        for uid, response in zip(uids, responses, strict=False):
            if response.calibrated_params is None:
                logger.debug(f"Miner {uid}: no calibrated_params in response")
                continue

            if len(response.calibrated_params) > MAX_PARAMS:
                logger.warning(f"Miner {uid}: too many params ({len(response.calibrated_params)}), skipping")
                continue

            raw_metadata = response.metadata
            if raw_metadata is not None:
                try:
                    metadata_size = sys.getsizeof(str(raw_metadata))
                    if metadata_size > MAX_METADATA_BYTES:
                        logger.warning(f"Miner {uid}: metadata too large ({metadata_size} bytes), discarding")
                        raw_metadata = None
                except Exception:
                    raw_metadata = None

            submissions[uid] = {
                "calibrated_params": response.calibrated_params,
                "simulations_used": response.simulations_used or 0,
                "training_cvrmse": response.training_cvrmse,
                "metadata": raw_metadata,
            }

        logger.info(f"Parsed {len(submissions)}/{len(responses)} valid responses")
        return submissions
