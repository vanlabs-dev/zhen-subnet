"""Validator entry point and Bittensor neuron lifecycle management."""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import logging
import os
from pathlib import Path
from typing import Any

if importlib.util.find_spec("bittensor"):
    import bittensor as bt
else:
    bt = None

import time

import protocol
from protocol.synapse import CalibrationSynapse
from validator.network.challenge_sender import ChallengeSender
from validator.network.result_receiver import ResponseParser
from validator.registry.manifest import ManifestLoader
from validator.round import split_generator, test_case_selector
from validator.round.orchestrator import RoundOrchestrator
from validator.scoring.ema import EMATracker
from validator.scoring.engine import ScoringEngine
from validator.verification.engine import VerificationEngine
from validator.weights.setter import WeightSetter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

DEFAULT_MANIFEST_PATH = Path(__file__).resolve().parent.parent / "registry" / "manifest.json"
DEFAULT_NETUID = int(os.environ.get("ZHEN_NETUID", "456"))
DEFAULT_NETWORK = os.environ.get("ZHEN_NETWORK", "test")
TEMPO_BLOCKS = 360
BLOCK_TIME_SECONDS = 12
DEFAULT_TEMPO_SECONDS = TEMPO_BLOCKS * BLOCK_TIME_SECONDS  # 4320s = 72min


class ZhenValidator:
    """Zhen subnet validator. Runs calibration rounds and sets weights.

    Operates in local mode (RC model as ground truth) for testnet, or
    BOPTEST mode for production ground truth generation.
    """

    def __init__(
        self,
        netuid: int = DEFAULT_NETUID,
        network: str = DEFAULT_NETWORK,
        wallet_name: str = "zhen-validator",
        wallet_hotkey: str = "default",
        local_mode: bool = True,
        manifest_path: Path = DEFAULT_MANIFEST_PATH,
        boptest_url: str = "http://localhost:8000",
    ) -> None:
        """Initialize the validator neuron.

        Args:
            netuid: Subnet UID on the chain.
            network: Network name (test, finney, or ws:// URL).
            wallet_name: Bittensor wallet name.
            wallet_hotkey: Bittensor wallet hotkey name.
            local_mode: Use RC model as ground truth (no BOPTEST needed).
            manifest_path: Path to manifest.json.
            boptest_url: BOPTEST service URL for non-local ground truth.
        """
        self.netuid = netuid
        self.network = network
        self.local_mode = local_mode
        self.boptest_url = boptest_url
        self.tempo_seconds = DEFAULT_TEMPO_SECONDS

        # Load manifest
        loader = ManifestLoader()
        self.manifest = loader.load(manifest_path)

        # Core components
        boptest = None if local_mode else boptest_url
        self.orchestrator = RoundOrchestrator(manifest_path=manifest_path, boptest_url=boptest)
        self.scoring_engine = ScoringEngine()
        self.ema = EMATracker(alpha=0.3)
        self.verification_engine = VerificationEngine()
        self.response_parser = ResponseParser()
        self.round_count = 0

        # Bittensor components
        self.wallet: Any = None
        self.subtensor: Any = None
        self.dendrite: Any = None
        self.metagraph: Any = None
        self.challenge_sender: ChallengeSender | None = None
        self.weight_setter: WeightSetter | None = None
        self.my_uid: int | None = None

        if bt is not None:
            self._init_bittensor(wallet_name, wallet_hotkey)

    def _init_bittensor(self, wallet_name: str, wallet_hotkey: str) -> None:
        """Initialize Bittensor SDK v10 components."""
        logger.info(f"Connecting to {self.network} (netuid={self.netuid})")

        self.wallet = bt.Wallet(name=wallet_name, hotkey=wallet_hotkey)
        self.subtensor = bt.Subtensor(network=self.network)
        self.dendrite = bt.Dendrite(wallet=self.wallet)
        self.metagraph = self.subtensor.metagraph(netuid=self.netuid)
        self.challenge_sender = ChallengeSender(self.wallet, self.dendrite)
        self.weight_setter = WeightSetter(self.subtensor, self.wallet, self.netuid, metagraph=self.metagraph)

        # Find our UID in the metagraph
        my_hotkey = self.wallet.hotkey.ss58_address
        for neuron in self.metagraph.neurons:
            if neuron.hotkey == my_hotkey:
                self.my_uid = neuron.uid
                break

        logger.info(f"Wallet: {wallet_name}/{wallet_hotkey}")
        logger.info(f"Hotkey: {my_hotkey}")
        logger.info(f"My UID: {self.my_uid}")
        logger.info(f"Neurons in metagraph: {len(self.metagraph.neurons)}")

    def _get_miner_axons(self) -> tuple[list[Any], list[int]]:
        """Get axon info for all miners (excluding self).

        Returns:
            Tuple of (axon_list, uid_list) for miners to query.
        """
        if self.metagraph is None:
            return [], []

        axons = []
        uids = []
        my_hotkey = self.wallet.hotkey.ss58_address if self.wallet else None

        for neuron in self.metagraph.neurons:
            # Skip ourselves
            if neuron.hotkey == my_hotkey:
                continue
            # Skip neurons without a serving axon
            if neuron.axon_info.ip == "0.0.0.0" or neuron.axon_info.port == 0:
                continue
            axons.append(neuron.axon_info)
            uids.append(neuron.uid)

        return axons, uids

    async def _wait_for_boptest(self) -> bool:
        """Poll BOPTEST /testcases endpoint until the service is ready.

        Retries every 10 seconds for up to 10 minutes. Handles the
        MinIO bucket race condition where the web container crashes
        on first startup and needs a restart.

        Returns:
            True if the service responded, False if all retries exhausted.
        """
        import httpx

        max_retries = 60
        retry_interval = 10
        url = f"{self.boptest_url}/testcases"

        logger.info(f"Waiting for BOPTEST service at {self.boptest_url}...")
        for attempt in range(1, max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(url)
                if resp.status_code < 400:
                    data = resp.json()
                    n_cases = len(data) if isinstance(data, list) else 0
                    logger.info(f"BOPTEST service ready ({n_cases} test cases available)")
                    return True
            except Exception:
                pass

            if attempt < max_retries:
                logger.info(f"  BOPTEST not ready (attempt {attempt}/{max_retries}), retrying in {retry_interval}s...")
                await asyncio.sleep(retry_interval)

        logger.error("BOPTEST service did not respond after 10 minutes. Continuing without warmup.")
        return False

    async def _warmup_boptest(self) -> None:
        """Pre-warm all BOPTEST test cases by selecting and stopping each one.

        First polls the service until it is ready, then selects and stops
        each test case to force FMU compilation. Retries each test case
        once on failure (the worker might be busy finishing a previous compile).
        """
        from validator.emulator.boptest_client import BOPTESTClient

        if not await self._wait_for_boptest():
            return

        client = BOPTESTClient(self.boptest_url)
        try:
            test_cases = self.manifest.get("test_cases", [])
            logger.info(f"Pre-warming {len(test_cases)} BOPTEST test cases...")

            for tc in test_cases:
                tc_id = tc["id"]
                for attempt in range(1, 3):
                    start = time.monotonic()
                    try:
                        testid = await client.select_testcase(tc_id)
                        await client.stop(testid)
                        elapsed = time.monotonic() - start
                        logger.info(f"  Warmed {tc_id} in {elapsed:.1f}s")
                        break
                    except Exception as e:
                        elapsed = time.monotonic() - start
                        if attempt == 1:
                            logger.warning(f"  {tc_id} failed ({elapsed:.1f}s): {e}. Retrying...")
                            await asyncio.sleep(5)
                        else:
                            logger.warning(f"  {tc_id} failed on retry ({elapsed:.1f}s): {e}. Skipping.")

            logger.info("BOPTEST warmup complete")
        finally:
            await client.close()

    async def run(self) -> None:
        """Main loop: run rounds at tempo intervals."""
        logger.info(f"Starting ZhenValidator (netuid={self.netuid}, tempo={self.tempo_seconds}s)")
        logger.info(f"Local mode: {self.local_mode}")
        if not self.local_mode:
            logger.info(f"BOPTEST URL: {self.boptest_url}")
            await self._warmup_boptest()
        logger.info(f"Manifest version: {self.manifest['version']}")
        logger.info(f"Spec version: {protocol.__spec_version__}")

        while True:
            try:
                await self.run_round()
            except Exception as e:
                logger.error(f"Round failed: {e}", exc_info=True)

            logger.info(f"Sleeping {self.tempo_seconds}s until next round...")
            await asyncio.sleep(self.tempo_seconds)

    async def run_round(self) -> dict[str, Any]:
        """Run a single calibration round.

        Returns:
            Round results dict.
        """
        round_id = f"round-{self.round_count}"
        self.round_count += 1
        logger.info(f"=== {round_id} starting ===")

        # 1. Sync metagraph
        if self.metagraph is not None:
            logger.info("Syncing metagraph...")
            try:
                self.metagraph.sync()
            except Exception as e:
                logger.warning(f"Metagraph sync failed, using stale data: {e}")
            logger.info(f"Metagraph: {len(self.metagraph.neurons)} neurons")

        # 2. Select test case and compute split
        test_case = test_case_selector.select(round_id, self.manifest)
        train_period, test_period = split_generator.compute(round_id, test_case["id"])
        logger.info(f"Test case: {test_case['id']}")
        logger.info(f"Train period: hours {train_period[0]}-{train_period[1]}")
        logger.info(f"Test period: hours {test_period[0]}-{test_period[1]}")

        # 3. Generate ground truth
        if self.local_mode:
            logger.info("Generating ground truth (local mode: RC model)...")
        else:
            logger.info(f"Generating ground truth (BOPTEST: {self.boptest_url})...")
        held_out_data = await self.orchestrator.generate_ground_truth(
            test_case, test_period, local_mode=self.local_mode
        )
        training_data = await self.orchestrator.generate_ground_truth(
            test_case, train_period, local_mode=self.local_mode
        )

        # 4. Build test case config
        config = self.orchestrator._load_test_case_config(test_case["id"])

        # 5. Build CalibrationSynapse
        synapse = CalibrationSynapse(
            test_case_id=test_case["id"],
            manifest_version=self.manifest["version"],
            training_data=training_data,
            parameter_names=list(config["parameter_names"]),
            parameter_bounds=config["parameter_bounds"],
            simulation_budget=config.get("simulation_budget", 1000),
            round_id=round_id,
            train_start_hour=train_period[0],
            train_end_hour=train_period[1],
        )

        # 6. Send to miners
        submissions: dict[int, dict[str, Any]] = {}
        axons, uids = self._get_miner_axons()

        if not axons:
            logger.warning("No miners available to query")
            return {"round_id": round_id, "scores": {}, "weights": {}}

        logger.info(f"Sending challenge to {len(axons)} miners (timeout={self.tempo_seconds - 300}s)")
        timeout = max(60.0, self.tempo_seconds - 300)

        if self.challenge_sender is not None:
            responses = await self.challenge_sender.send_challenge(axons, synapse, timeout)
            submissions = self.response_parser.parse_responses(responses, uids)

        logger.info(f"Received {len(submissions)} valid submissions")

        if not submissions:
            logger.warning("No valid submissions received this round")
            return {"round_id": round_id, "scores": {}, "weights": {}}

        # 7. Build verification config and verify
        verification_config = self.orchestrator._build_verification_config(test_case)
        logger.info("Verifying submissions...")
        verified = await self.verification_engine.verify_all(
            submissions, verification_config, test_period, held_out_data
        )

        # 8. Compute scores
        scores = self.scoring_engine.compute(verified)
        logger.info(f"Scores: {scores}")

        # Log per-metric breakdown for each miner
        for uid, v in verified.items():
            if v.reason:
                logger.info(f"  UID {uid}: REJECTED ({v.reason})")
            else:
                logger.info(
                    f"  UID {uid}: CVRMSE={v.cvrmse:.4f}, NMBE={v.nmbe:.4f}, "
                    f"R2={v.r_squared:.4f}, sims={v.simulations_used}, "
                    f"composite={scores.get(uid, 0.0):.4f}"
                )

        # 9. Update EMA
        self.ema.update(scores)
        weights = self.ema.get_weights()
        logger.info(f"EMA weights: {weights}")

        # 10. Set weights on chain
        if self.weight_setter is not None and weights:
            success = await self.weight_setter.set_weights(weights)
            if success:
                logger.info("Weights set on chain successfully")
            else:
                logger.warning("Failed to set weights on chain")

        logger.info(f"=== {round_id} complete ===")
        return {"round_id": round_id, "scores": scores, "weights": weights}


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Zhen Subnet Validator")
    parser.add_argument("--netuid", type=int, default=DEFAULT_NETUID, help="Subnet UID")
    parser.add_argument("--network", type=str, default=DEFAULT_NETWORK, help="Network (test, finney, or ws:// URL)")
    parser.add_argument("--wallet-name", type=str, default="zhen-validator", help="Wallet name")
    parser.add_argument("--wallet-hotkey", type=str, default="default", help="Wallet hotkey")
    parser.add_argument("--local-mode", action="store_true", default=True, help="Use RC model as ground truth")
    parser.add_argument("--no-local-mode", action="store_false", dest="local_mode", help="Use BOPTEST for ground truth")
    parser.add_argument("--boptest-url", type=str, default="http://localhost:8000", help="BOPTEST service URL")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    validator = ZhenValidator(
        netuid=args.netuid,
        network=args.network,
        wallet_name=args.wallet_name,
        wallet_hotkey=args.wallet_hotkey,
        local_mode=args.local_mode,
        boptest_url=args.boptest_url,
    )
    asyncio.run(validator.run())
