"""Validator entry point and Bittensor neuron lifecycle management."""

from __future__ import annotations

import asyncio
import importlib.util
import logging
from pathlib import Path
from typing import Any

if importlib.util.find_spec("bittensor"):
    import bittensor as bt
else:
    bt = None

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

logger = logging.getLogger(__name__)

DEFAULT_MANIFEST_PATH = Path(__file__).resolve().parent.parent / "registry" / "manifest.json"
DEFAULT_TEMPO_SECONDS = 4320  # 72 minutes


class ZhenValidator:
    """Zhen subnet validator. Runs calibration rounds and sets weights.

    In production, runs BOPTEST for ground truth and communicates with
    miners via Bittensor dendrite. Supports local mode for testing.
    """

    def __init__(
        self,
        config: Any = None,
        manifest_path: Path = DEFAULT_MANIFEST_PATH,
        netuid: int = 1,
        tempo_seconds: int = DEFAULT_TEMPO_SECONDS,
    ) -> None:
        """Initialize the validator neuron.

        Args:
            config: Bittensor config object (optional).
            manifest_path: Path to manifest.json.
            netuid: Subnet UID.
            tempo_seconds: Seconds between rounds.
        """
        self.config = config
        self.netuid = netuid
        self.tempo_seconds = tempo_seconds

        # Load manifest
        loader = ManifestLoader()
        self.manifest = loader.load(manifest_path)

        # Scoring
        self.scoring_engine = ScoringEngine()
        self.ema = EMATracker(alpha=0.3)
        self.verification_engine = VerificationEngine()
        self.round_count = 0

        # Bittensor components (initialized if bt available)
        self.wallet: Any = None
        self.subtensor: Any = None
        self.dendrite: Any = None
        self.metagraph: Any = None
        self.challenge_sender: ChallengeSender | None = None
        self.response_parser = ResponseParser()
        self.weight_setter: WeightSetter | None = None

        if bt is not None:
            self._init_bittensor()

    def _init_bittensor(self) -> None:
        """Initialize Bittensor SDK components."""
        self.wallet = bt.wallet(config=self.config)
        self.subtensor = bt.subtensor(config=self.config)
        self.dendrite = bt.dendrite(wallet=self.wallet)
        self.metagraph = self.subtensor.metagraph(self.netuid)
        self.challenge_sender = ChallengeSender(self.wallet, self.dendrite)
        self.weight_setter = WeightSetter(self.subtensor, self.wallet, self.netuid)

    async def run(self) -> None:
        """Main loop: run rounds at tempo intervals."""
        logger.info(f"Starting ZhenValidator (netuid={self.netuid}, tempo={self.tempo_seconds}s)")

        while True:
            try:
                await self.run_round()
            except Exception as e:
                logger.error(f"Round failed: {e}", exc_info=True)

            await asyncio.sleep(self.tempo_seconds)

    async def run_round(self) -> dict[str, Any]:
        """Run a single calibration round.

        Returns:
            Round results dict.
        """
        round_id = f"round-{self.round_count}"
        self.round_count += 1
        logger.info(f"Starting {round_id}")

        # 1. Sync metagraph
        if self.metagraph is not None:
            self.metagraph.sync()

        # 2. Select test case and compute split
        test_case = test_case_selector.select(round_id, self.manifest)
        train_period, test_period = split_generator.compute(round_id, test_case["id"])

        # 3. Generate ground truth
        orchestrator = RoundOrchestrator(
            manifest_path=DEFAULT_MANIFEST_PATH,
        )
        held_out_data = orchestrator._generate_ground_truth(test_case, test_period)

        # 4. Build CalibrationSynapse
        synapse = CalibrationSynapse(
            test_case_id=test_case["id"],
            manifest_version=self.manifest["version"],
            training_data=orchestrator._generate_ground_truth(test_case, train_period),
            parameter_names=list(orchestrator._load_test_case_config(test_case["id"])["parameter_names"]),
            parameter_bounds=orchestrator._load_test_case_config(test_case["id"])["parameter_bounds"],
            simulation_budget=orchestrator._load_test_case_config(test_case["id"]).get("simulation_budget", 1000),
            round_id=round_id,
            train_start_hour=train_period[0],
            train_end_hour=train_period[1],
        )

        # 5. Send to miners
        submissions: dict[int, dict[str, Any]] = {}
        if self.challenge_sender is not None and self.metagraph is not None:
            miners = self.metagraph.axons
            uids = list(range(len(miners)))
            timeout = max(60.0, self.tempo_seconds - 300)
            responses = await self.challenge_sender.send_challenge(miners, synapse, timeout)
            submissions = self.response_parser.parse_responses(responses, uids)
        else:
            logger.warning("No Bittensor connection; no miners queried")

        if not submissions:
            logger.warning("No valid submissions received")
            return {"round_id": round_id, "scores": {}, "weights": {}}

        # 6. Build verification config
        verification_config = orchestrator._build_verification_config(test_case)

        # 7. Verify and score
        verified = await self.verification_engine.verify_all(
            submissions, verification_config, test_period, held_out_data
        )
        scores = self.scoring_engine.compute(verified)

        # 8. Update EMA
        self.ema.update(scores)
        weights = self.ema.get_weights()

        # 9. Set weights on chain
        if self.weight_setter is not None:
            await self.weight_setter.set_weights(weights)

        logger.info(f"{round_id} complete: {len(submissions)} submissions, {len(verified)} verified")
        return {"round_id": round_id, "scores": scores, "weights": weights}


if __name__ == "__main__":
    validator = ZhenValidator()
    asyncio.run(validator.run())
