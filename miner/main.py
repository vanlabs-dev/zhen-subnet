"""Miner entry point and Bittensor neuron lifecycle management."""

from __future__ import annotations

import asyncio
import importlib.util
import logging
from typing import Any

if importlib.util.find_spec("bittensor"):
    import bittensor as bt
else:
    bt = None

from miner.calibration.engine import CalibrationEngine
from miner.network.axon_handler import CalibrationHandler

logger = logging.getLogger(__name__)


class ZhenMiner:
    """Zhen subnet miner. Receives calibration challenges and returns optimized params.

    Registers a CalibrationHandler on the Bittensor Axon to process
    incoming CalibrationSynapse challenges from validators.
    """

    def __init__(self, config: Any = None, algorithm: str = "bayesian", netuid: int = 1) -> None:
        """Initialize the miner neuron.

        Args:
            config: Bittensor config object (optional).
            algorithm: Calibration algorithm to use.
            netuid: Subnet UID.
        """
        self.config = config
        self.netuid = netuid

        # Calibration
        self.calibration_engine = CalibrationEngine(algorithm=algorithm)
        self.handler = CalibrationHandler(self.calibration_engine)

        # Bittensor components
        self.wallet: Any = None
        self.subtensor: Any = None
        self.axon: Any = None

        if bt is not None:
            self._init_bittensor()

    def _init_bittensor(self) -> None:
        """Initialize Bittensor SDK components and register axon handler."""
        self.wallet = bt.wallet(config=self.config)
        self.subtensor = bt.subtensor(config=self.config)
        self.axon = bt.axon(wallet=self.wallet)

        # Attach handler for CalibrationSynapse
        self.axon.attach(
            forward_fn=self.handler.forward,
            blacklist_fn=self.handler.blacklist,
            priority_fn=self.handler.priority,
        )

    async def run(self) -> None:
        """Start the miner axon and serve indefinitely."""
        if self.axon is None:
            logger.error("Cannot run miner without Bittensor (axon not initialized)")
            return

        logger.info(f"Starting ZhenMiner (netuid={self.netuid})")

        # Serve axon on the network
        self.axon.serve(netuid=self.netuid, subtensor=self.subtensor)
        self.axon.start()

        logger.info("Axon started, serving CalibrationSynapse requests")

        try:
            while True:
                await asyncio.sleep(60)
        except KeyboardInterrupt:
            logger.info("Miner shutting down")
        finally:
            self.axon.stop()


if __name__ == "__main__":
    miner = ZhenMiner()
    asyncio.run(miner.run())
