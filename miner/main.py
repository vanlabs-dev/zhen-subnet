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
from validator.utils.logging import setup_logging

logger = logging.getLogger(__name__)

DEFAULT_NETUID = int(os.environ.get("ZHEN_NETUID", "456"))
DEFAULT_NETWORK = os.environ.get("ZHEN_NETWORK", "test")

# Module-level metagraph reference for blacklist_fn (must be standalone per SDK v10)
_metagraph: Any = None


def blacklist_fn(synapse: CalibrationSynapse) -> Tuple[bool, str]:
    """Reject requests from hotkeys not registered on the subnet."""
    if _metagraph is None:
        return (False, "No metagraph available, accepting all")

    requester_hotkey = synapse.dendrite.hotkey
    if requester_hotkey not in _metagraph.hotkeys:
        return (True, f"Hotkey {requester_hotkey[:16]} not registered on subnet")

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
        axon_port: int = 8091,
    ) -> None:
        """Initialize the miner neuron.

        Args:
            netuid: Subnet UID on the chain.
            network: Network name (test, finney, or ws:// URL).
            wallet_name: Bittensor wallet name.
            wallet_hotkey: Bittensor wallet hotkey name.
            algorithm: Calibration algorithm to use.
            n_calls: Number of optimization iterations.
            axon_port: Port for the axon server to listen on.
        """
        self.netuid = netuid
        self.network = network
        self.n_calls = n_calls
        self.axon_port = axon_port

        # Calibration engine
        self.calibration_engine = CalibrationEngine(algorithm=algorithm, n_calls=n_calls)
        self.handler = CalibrationHandler(self.calibration_engine)

        # Bittensor components
        self.wallet: Any = None
        self.subtensor: Any = None
        self.metagraph: Any = None
        self.axon: Any = None

        if bt is not None:
            self._init_bittensor(wallet_name, wallet_hotkey)

    def _init_bittensor(self, wallet_name: str, wallet_hotkey: str) -> None:
        """Initialize Bittensor SDK v10 components and register axon handler."""
        global _metagraph

        logger.info(f"Connecting to {self.network} (netuid={self.netuid})")

        self.wallet = bt.Wallet(name=wallet_name, hotkey=wallet_hotkey)
        self.subtensor = bt.Subtensor(network=self.network)
        self.metagraph = self.subtensor.metagraph(netuid=self.netuid)
        _metagraph = self.metagraph
        self.axon = bt.Axon(wallet=self.wallet, port=self.axon_port)

        self.axon.attach(
            forward_fn=self.handler.forward,
            blacklist_fn=blacklist_fn,
            priority_fn=priority_fn,
        )

        logger.info(f"Wallet: {wallet_name}/{wallet_hotkey}")
        logger.info(f"Hotkey: {self.wallet.hotkey.ss58_address}")
        logger.info(f"Metagraph: {len(self.metagraph.neurons)} neurons")

    async def _sync_metagraph_loop(self) -> None:
        """Periodically sync metagraph to keep blacklist current."""
        global _metagraph

        while True:
            await asyncio.sleep(600)
            try:
                self.metagraph.sync()
                _metagraph = self.metagraph
                logger.info(f"Metagraph synced: {len(self.metagraph.neurons)} neurons")
            except Exception as e:
                logger.warning(f"Metagraph sync failed: {e}")

    async def run(self) -> None:
        """Start the miner axon and serve indefinitely."""
        if self.axon is None:
            logger.error("Cannot run miner without Bittensor (axon not initialized)")
            return

        if self.subtensor is None:
            logger.error("Cannot run miner without subtensor connection")
            return

        logger.info(f"Starting ZhenMiner (netuid={self.netuid}, port={self.axon_port})")

        # Serve axon on the network
        self.axon.serve(netuid=self.netuid, subtensor=self.subtensor)
        self.axon.start()

        logger.info("Axon started, serving CalibrationSynapse requests")
        logger.info(f"Calibration algorithm: bayesian (n_calls={self.n_calls})")
        logger.info("Waiting for challenges from validators...")

        # Launch metagraph sync as background task
        sync_task = asyncio.create_task(self._sync_metagraph_loop())

        try:
            while True:
                await asyncio.sleep(60)
        except KeyboardInterrupt:
            logger.info("Miner shutting down")
        finally:
            sync_task.cancel()
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
    parser.add_argument("--axon-port", type=int, default=8091, help="Axon server port")
    parser.add_argument(
        "--log-level", type=str, default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="Logging level",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    setup_logging("miner", args.log_level)
    miner = ZhenMiner(
        netuid=args.netuid,
        network=args.network,
        wallet_name=args.wallet_name,
        wallet_hotkey=args.wallet_hotkey,
        algorithm=args.algorithm,
        n_calls=args.n_calls,
        axon_port=args.axon_port,
    )
    asyncio.run(miner.run())
