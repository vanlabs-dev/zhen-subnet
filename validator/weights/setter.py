"""Bittensor set_weights integration.

Sets normalized EMA scores as weights on-chain via the Bittensor SDK,
with weight processing, NaN/Inf guards, and version tracking.
Uses SDK v10 ExtrinsicResponse. Chain calls run in a thread executor
with a timeout to prevent indefinite hangs.
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
from typing import Any

import numpy as np
import numpy.typing as npt

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
    uids: npt.NDArray[np.int64],
    weights: npt.NDArray[np.float32],
) -> tuple[npt.NDArray[np.int64], npt.NDArray[np.float32]]:
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

    WEIGHT_TIMEOUT_SECONDS: int = 120

    def __init__(self, subtensor: Any, wallet: Any, netuid: int, metagraph: Any = None) -> None:
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

    def _set_weights_sync(self, uids_arr: npt.NDArray[np.int64], weights_arr: npt.NDArray[np.float32]) -> bool:
        """Synchronous weight-setting call (runs in thread executor).

        Processes weights, submits to chain, and handles the response.

        Args:
            uids_arr: Processed UID array (int64).
            weights_arr: Processed weight array (float32).

        Returns:
            True if weights were set successfully, False otherwise.
        """
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

    async def set_weights(self, scores: dict[int, float]) -> bool:
        """Set weights on-chain from normalized scores.

        Applies NaN/Inf guards, then runs the blocking chain call in a
        thread executor with a timeout to prevent indefinite hangs.

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
        weights_arr: npt.NDArray[np.float32] = np.array(raw_weights, dtype=np.float32)
        if np.isnan(weights_arr).any() or np.isinf(weights_arr).any():
            logger.warning("Weights contain NaN/Inf values. Replacing with 0.")
            weights_arr = np.nan_to_num(weights_arr, nan=0.0, posinf=0.0, neginf=0.0)

        if weights_arr.sum() == 0:
            logger.warning("All weights are zero after NaN cleanup, skipping submission")
            return False

        uids_arr: npt.NDArray[np.int64] = np.array(uids, dtype=np.int64)

        try:
            loop = asyncio.get_event_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(None, self._set_weights_sync, uids_arr, weights_arr),
                timeout=float(self.WEIGHT_TIMEOUT_SECONDS),
            )
            return result
        except asyncio.TimeoutError:
            logger.error(f"Weight setting timed out after {self.WEIGHT_TIMEOUT_SECONDS}s (chain may be congested)")
            return False
        except Exception as e:
            logger.error(f"Failed to set weights: {e}")
            return False

    def copy_weights_from_chain(self) -> dict[int, float]:
        """Copy existing weights from chain as a fallback.

        Used when scoring fails to avoid missing weight-setting windows.
        Reads the current on-chain weight vector aggregated across
        validators with permit, weighted by stake.

        Returns:
            Mapping of miner UID to weight, or empty dict on failure.
        """
        if self.metagraph is None:
            logger.warning("No metagraph available for weight fallback")
            return {}

        try:
            self.metagraph.sync(subtensor=self.subtensor)

            valid_indices = np.where(self.metagraph.validator_permit)[0]
            if len(valid_indices) == 0:
                logger.warning("No validators with permit found for weight fallback")
                return {}

            valid_weights = self.metagraph.weights[valid_indices]
            valid_stakes = self.metagraph.stake[valid_indices]

            total_stake = float(np.sum(valid_stakes))
            if total_stake == 0:
                return {}

            normalized_stakes = valid_stakes / total_stake
            stake_weighted_avg: npt.NDArray[np.floating[Any]] = np.dot(normalized_stakes, valid_weights)

            uids = self.metagraph.uids.tolist()
            weights_list = stake_weighted_avg.tolist()

            result = {uid: w for uid, w in zip(uids, weights_list, strict=False) if w > 0}
            logger.info(f"Copied {len(result)} weights from chain as fallback")
            return result
        except Exception as e:
            logger.error(f"Failed to copy weights from chain: {e}")
            return {}
