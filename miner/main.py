"""Miner entry point and Bittensor neuron lifecycle management."""

import argparse
import asyncio
import importlib.util
import logging
import os
from typing import Any, Tuple

if importlib.util.find_spec("bittensor"):
    import bittensor as bt
else:
    bt = None

from miner.calibration.engine import CalibrationEngine
from miner.network.axon_handler import CalibrationHandler
from protocol.synapse import CalibrationSynapse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

DEFAULT_NETUID = int(os.environ.get("ZHEN_NETUID", "456"))
DEFAULT_NETWORK = os.environ.get("ZHEN_NETWORK", "test")


def blacklist_fn(synapse: CalibrationSynapse) -> Tuple[bool, str]:
    """Determine whether to blacklist request. Accepts all for now."""
    return (False, "")


def priority_fn(synapse: CalibrationSynapse) -> float:
    """Assign priority to request. Equal priority for now."""
    return 0.0


class ZhenMiner:
    """Zhen subnet miner. Receives calibration challenges and returns optimized params.

    Registers a CalibrationHandler on the Bittensor Axon to process
    incoming CalibrationSynapse challenges from validators.
    """

    def __init__(
        self,
        netuid: int = DEFAULT_NETUID,
        network: str = DEFAULT_NETWORK,
        wallet_name: str = "zhen-miner",
        wallet_hotkey: str = "default",
        algorithm: str = "bayesian",
        n_calls: int = 100,
    ) -> None:
        """Initialize the miner neuron.

        Args:
            netuid: Subnet UID on the chain.
            network: Network name (test, finney, or ws:// URL).
            wallet_name: Bittensor wallet name.
            wallet_hotkey: Bittensor wallet hotkey name.
            algorithm: Calibration algorithm to use.
            n_calls: Number of optimization iterations.
        """
        self.netuid = netuid
        self.network = network
        self.n_calls = n_calls

        # Calibration engine
        self.calibration_engine = CalibrationEngine(algorithm=algorithm, n_calls=n_calls)
        self.handler = CalibrationHandler(self.calibration_engine)

        # Bittensor components
        self.wallet: Any = None
        self.subtensor: Any = None
        self.axon: Any = None

        if bt is not None:
            self._init_bittensor(wallet_name, wallet_hotkey)

    def _init_bittensor(self, wallet_name: str, wallet_hotkey: str) -> None:
        """Initialize Bittensor SDK v10 components and register axon handler."""
        logger.info(f"Connecting to {self.network} (netuid={self.netuid})")

        self.wallet = bt.Wallet(name=wallet_name, hotkey=wallet_hotkey)
        self.subtensor = bt.Subtensor(network=self.network)
        self.axon = bt.Axon(wallet=self.wallet)

        self.axon.attach(
            forward_fn=self.handler.forward,
            blacklist_fn=blacklist_fn,
            priority_fn=priority_fn,
        )

        logger.info(f"Wallet: {wallet_name}/{wallet_hotkey}")
        logger.info(f"Hotkey: {self.wallet.hotkey.ss58_address}")

    async def run(self) -> None:
        """Start the miner axon and serve indefinitely."""
        if self.axon is None:
            logger.error("Cannot run miner without Bittensor (axon not initialized)")
            return

        if self.subtensor is None:
            logger.error("Cannot run miner without subtensor connection")
            return

        logger.info(f"Starting ZhenMiner (netuid={self.netuid})")

        # Serve axon on the network
        self.axon.serve(netuid=self.netuid, subtensor=self.subtensor)
        self.axon.start()

        logger.info("Axon started, serving CalibrationSynapse requests")
        logger.info(f"Calibration algorithm: bayesian (n_calls={self.n_calls})")
        logger.info("Waiting for challenges from validators...")

        try:
            while True:
                await asyncio.sleep(60)
        except KeyboardInterrupt:
            logger.info("Miner shutting down")
        finally:
            self.axon.stop()
            logger.info("Axon stopped")


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Zhen Subnet Miner")
    parser.add_argument("--netuid", type=int, default=DEFAULT_NETUID, help="Subnet UID")
    parser.add_argument("--network", type=str, default=DEFAULT_NETWORK, help="Network (test, finney, or ws:// URL)")
    parser.add_argument("--wallet-name", type=str, default="zhen-miner", help="Wallet name")
    parser.add_argument("--wallet-hotkey", type=str, default="default", help="Wallet hotkey")
    parser.add_argument("--algorithm", type=str, default="bayesian", help="Calibration algorithm")
    parser.add_argument("--n-calls", type=int, default=100, help="Optimization iterations")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    miner = ZhenMiner(
        netuid=args.netuid,
        network=args.network,
        wallet_name=args.wallet_name,
        wallet_hotkey=args.wallet_hotkey,
        algorithm=args.algorithm,
        n_calls=args.n_calls,
    )
    asyncio.run(miner.run())
