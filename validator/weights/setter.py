"""Bittensor set_weights integration.

Sets normalized EMA scores as weights on-chain via the Bittensor SDK,
with weight processing, NaN/Inf guards, and version tracking.
Uses SDK v10 ExtrinsicResponse.
"""

from __future__ import annotations

import importlib.util
import logging
from typing import Any

import numpy as np

if importlib.util.find_spec("bittensor"):
    import bittensor as bt
else:
    bt = None

import protocol

logger = logging.getLogger(__name__)

# Attempt to import the SDK weight processing utility
_HAS_PROCESS_WEIGHTS = False
_process_weights_fn: Any = None
if bt is not None:
    try:
        from bittensor.utils.weight_utils import process_weights_for_netuid

        _process_weights_fn = process_weights_for_netuid
        _HAS_PROCESS_WEIGHTS = True
    except ImportError:
        pass


def _process_weights_manual(
    uids: np.ndarray,
    weights: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Normalize weights to u16 format for chain submission.

    Fallback when bt.utils.weight_utils.process_weights_for_netuid
    is not available.

    Args:
        uids: Array of miner UIDs (int64).
        weights: Array of raw weights (float32).

    Returns:
        Tuple of (uids, processed_weights) with weights as float32
        normalized to sum to 1.0.
    """
    total = weights.sum()
    if total > 0:
        weights = weights / total
    return uids, weights


class WeightSetter:
    """Sets miner weights on-chain via Bittensor subtensor."""

    def __init__(
        self, subtensor: Any, wallet: Any, netuid: int, metagraph: Any = None
    ) -> None:
        """Initialize the weight setter.

        Args:
            subtensor: Bittensor subtensor instance.
            wallet: Bittensor wallet instance.
            netuid: Subnet UID to set weights on.
            metagraph: Bittensor metagraph instance for weight processing.
        """
        self.subtensor = subtensor
        self.wallet = wallet
        self.netuid = netuid
        self.metagraph = metagraph

    async def set_weights(self, scores: dict[int, float]) -> bool:
        """Set weights on-chain from normalized scores.

        Applies NaN/Inf guards, processes weights for chain format,
        and uses SDK v10 ExtrinsicResponse pattern.

        Args:
            scores: Mapping of miner UID to normalized weight (should sum to 1.0).

        Returns:
            True if weights were set successfully, False otherwise.
        """
        if not scores:
            logger.warning("No scores to set weights for")
            return False

        uids = list(scores.keys())
        raw_weights = [scores[uid] for uid in uids]

        # NaN/Inf guard
        weights_arr = np.array(raw_weights, dtype=np.float32)
        if np.isnan(weights_arr).any() or np.isinf(weights_arr).any():
            logger.warning("Weights contain NaN/Inf values. Replacing with 0.")
            weights_arr = np.nan_to_num(weights_arr, nan=0.0, posinf=0.0, neginf=0.0)

        if weights_arr.sum() == 0:
            logger.warning("All weights are zero after NaN cleanup, skipping submission")
            return False

        # Process weights for chain submission
        uids_arr = np.array(uids, dtype=np.int64)

        if _HAS_PROCESS_WEIGHTS and self.metagraph is not None:
            logger.info("Processing weights via bt.utils.weight_utils")
            try:
                uids_arr, weights_arr = _process_weights_fn(
                    uids_arr, weights_arr, self.netuid, self.subtensor, self.metagraph
                )
            except Exception as e:
                logger.warning(f"SDK weight processing failed, using manual: {e}")
                uids_arr, weights_arr = _process_weights_manual(uids_arr, weights_arr)
        else:
            if not _HAS_PROCESS_WEIGHTS:
                logger.info("Processing weights manually (SDK utility not available)")
            else:
                logger.info("Processing weights manually (no metagraph provided)")
            uids_arr, weights_arr = _process_weights_manual(uids_arr, weights_arr)

        try:
            logger.info(f"Setting weights for {len(uids_arr)} miners on netuid {self.netuid}")
            response = self.subtensor.set_weights(
                wallet=self.wallet,
                netuid=self.netuid,
                uids=uids_arr.tolist(),
                weights=weights_arr.tolist(),
                wait_for_inclusion=True,
                wait_for_finalization=True,
                version_key=protocol.__spec_version__,
            )

            # SDK v10: ExtrinsicResponse with .success attribute
            if hasattr(response, "success"):
                if response.success:
                    block_hash = getattr(response, "block_hash", "unknown")
                    logger.info(f"Weights set successfully (block: {block_hash})")
                    return True
                else:
                    error = getattr(response, "error_message", "unknown error")
                    logger.error(f"Weight setting failed: {error}")
                    return False

            # Fallback for older SDK versions
            return bool(response)

        except Exception as e:
            logger.error(f"Failed to set weights: {e}")
            return False
