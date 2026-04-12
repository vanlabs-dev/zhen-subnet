"""Bittensor set_weights integration.

Sets normalized EMA scores as weights on-chain via the Bittensor SDK,
with wait_for_inclusion confirmation.
"""

from __future__ import annotations

import importlib.util
import logging
from typing import Any

if importlib.util.find_spec("bittensor"):
    import bittensor as bt
else:
    bt = None

logger = logging.getLogger(__name__)


class WeightSetter:
    """Sets miner weights on-chain via Bittensor subtensor."""

    def __init__(self, subtensor: Any, wallet: Any, netuid: int) -> None:
        """Initialize the weight setter.

        Args:
            subtensor: Bittensor subtensor instance.
            wallet: Bittensor wallet instance.
            netuid: Subnet UID to set weights on.
        """
        self.subtensor = subtensor
        self.wallet = wallet
        self.netuid = netuid

    async def set_weights(self, scores: dict[int, float]) -> bool:
        """Set weights on-chain from normalized scores.

        Args:
            scores: Mapping of miner UID to normalized weight (should sum to 1.0).

        Returns:
            True if weights were set successfully, False otherwise.
        """
        if not scores:
            logger.warning("No scores to set weights for")
            return False

        uids = list(scores.keys())
        weights = [scores[uid] for uid in uids]

        try:
            self.subtensor.set_weights(
                wallet=self.wallet,
                netuid=self.netuid,
                uids=uids,
                weights=weights,
                wait_for_inclusion=True,
            )
            logger.info(f"Weights set for {len(uids)} miners on netuid {self.netuid}")
            return True
        except Exception as e:
            logger.error(f"Failed to set weights: {e}")
            return False
