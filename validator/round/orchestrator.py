"""Round lifecycle management.

Runs one calibration round per tempo: selects a test case, computes the
train/test split, runs the complex emulator, sends challenges to miners,
verifies submissions, computes scores, and sets weights.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from simulation.rc_network import RCNetworkBackend
from validator.emulator.manager import BOPTESTManager
from validator.registry.manifest import ManifestLoader
from validator.round import split_generator, test_case_selector
from validator.scoring import breakdown
from validator.scoring.ema import EMATracker
from validator.scoring.engine import ScoringEngine
from validator.verification.engine import VerificationEngine

logger = logging.getLogger(__name__)


class RoundOrchestrator:
    """Orchestrates a single calibration round.

    In local mode (no BOPTEST), uses the RC model with default parameters
    as "ground truth" so the full pipeline can be tested without Docker.
    """

    def __init__(self, manifest_path: Path, boptest_url: str | None = None) -> None:
        """Initialize the round orchestrator.

        Args:
            manifest_path: Path to the manifest.json file.
            boptest_url: BOPTEST service URL. If None, uses local ground truth mode.
        """
        loader = ManifestLoader()
        self.manifest = loader.load(manifest_path)
        self.boptest_url = boptest_url
        self.scoring_engine = ScoringEngine()
        self.ema = EMATracker(alpha=0.3)
        self.verification_engine = VerificationEngine()
        self.round_count = 0

    async def run_round(self, miner_submissions: dict[int, dict[str, Any]]) -> dict[str, Any]:
        """Run a single calibration round with provided miner submissions.

        Args:
            miner_submissions: Mapping of miner UID to submission dict containing
                "calibrated_params" (dict[str, float]) and "simulations_used" (int).

        Returns:
            Round results dict with scores, breakdowns, weights, and metadata.
        """
        round_id = f"round-{self.round_count}"
        self.round_count += 1

        # 1. Select test case deterministically
        test_case = test_case_selector.select(round_id, self.manifest)

        # 2. Compute train/test split
        train_period, test_period = split_generator.compute(round_id, test_case["id"])

        # 3. Generate held-out ground truth (local mode within orchestrator)
        held_out_data = self._generate_ground_truth_local(test_case, test_period)

        # 4. Build test case config for verification (merge manifest + config.json)
        verification_test_case = self._build_verification_config(test_case)

        # 5. Verify all miner submissions
        verified = await self.verification_engine.verify_all(
            miner_submissions,
            verification_test_case,
            test_period,
            held_out_data,
            sim_budget=verification_test_case.get("simulation_budget", 1000),
        )

        # 6. Compute scores
        sim_budget = verification_test_case.get("simulation_budget", 1000)
        scores = self.scoring_engine.compute(verified, sim_budget=sim_budget)
        raw_scores = self.scoring_engine.compute_raw(verified, sim_budget=sim_budget)

        # 7. Update EMA
        self.ema.update(scores)
        weights = self.ema.get_weights()

        # 8. Generate breakdowns
        breakdowns: dict[int, dict[str, Any]] = {}
        for uid, v in verified.items():
            breakdowns[uid] = breakdown.generate(
                uid=uid,
                verified=v,
                composite=raw_scores.get(uid, 0.0),
                weights=weights,
                round_id=round_id,
                sim_budget=sim_budget,
            )

        return {
            "round_id": round_id,
            "test_case_id": test_case["id"],
            "train_period": train_period,
            "test_period": test_period,
            "scores": scores,
            "raw_scores": raw_scores,
            "weights": weights,
            "breakdowns": breakdowns,
            "verified": verified,
        }

    async def generate_ground_truth(
        self,
        test_case: dict[str, Any],
        period: tuple[int, int],
        local_mode: bool = True,
    ) -> dict[str, list[float]]:
        """Generate ground truth data, dispatching to the appropriate backend.

        Args:
            test_case: Test case dict from manifest.
            period: (start_hour, end_hour) for the simulation window.
            local_mode: If True, use RC model with defaults. If False,
                use BOPTEST complex emulator.

        Returns:
            Dict mapping scoring output names to lists of values.
        """
        if local_mode:
            return self._generate_ground_truth_local(test_case, period)
        return await self._generate_ground_truth_boptest(test_case, period)

    def _generate_ground_truth_local(
        self, test_case: dict[str, Any], period: tuple[int, int]
    ) -> dict[str, list[float]]:
        """Generate ground truth using the RC model with default parameters.

        Used in local/testnet mode where no BOPTEST service is available.

        Args:
            test_case: Test case dict from manifest.
            period: (start_hour, end_hour) for the simulation window.

        Returns:
            Dict mapping scoring output names to lists of values.
        """
        config = self._load_test_case_config(test_case["id"])
        default_params = config["defaults"]
        rc = RCNetworkBackend(config, default_params)
        result = rc.run(start_hour=period[0], end_hour=period[1])

        scoring_outputs = test_case.get("scoring_outputs", config.get("scoring_outputs", []))
        return result.get_outputs(scoring_outputs)

    async def _generate_ground_truth_boptest(
        self, test_case: dict[str, Any], period: tuple[int, int]
    ) -> dict[str, list[float]]:
        """Generate ground truth using the BOPTEST complex emulator.

        Connects to an externally-managed BOPTEST service, runs the
        simulation for the specified period, and collects output data.

        Args:
            test_case: Test case dict from manifest.
            period: (start_hour, end_hour) for the simulation window.

        Returns:
            Dict mapping scoring output names to lists of values.

        Raises:
            ValueError: If no boptest_url is configured.
        """
        if self.boptest_url is None:
            raise ValueError("BOPTEST URL not configured. Pass --boptest-url or use local mode.")

        config = self._load_test_case_config(test_case["id"])
        scoring_outputs = test_case.get("scoring_outputs", config.get("scoring_outputs", []))
        output_mapping: dict[str, dict[str, str]] = config.get("boptest_output_mapping", {})

        if not output_mapping:
            raise ValueError(
                f"Test case '{test_case['id']}' has no boptest_output_mapping "
                f"in config.json. Cannot run BOPTEST ground truth."
            )

        manager = BOPTESTManager(self.boptest_url)
        logger.info(f"Generating BOPTEST ground truth for {test_case['id']} (hours {period[0]}-{period[1]})")

        return await manager.run_simulation(
            testcase_id=test_case["id"],
            start_hour=period[0],
            end_hour=period[1],
            scoring_outputs=scoring_outputs,
            output_mapping=output_mapping,
        )

    def _build_verification_config(self, test_case: dict[str, Any]) -> dict[str, Any]:
        """Build the verification config by merging manifest entry with config.json.

        Args:
            test_case: Test case dict from manifest.

        Returns:
            Combined config dict with parameter_bounds, scoring_outputs, etc.
        """
        config = self._load_test_case_config(test_case["id"])
        return {
            "id": test_case["id"],
            "parameter_bounds": config["parameter_bounds"],
            "scoring_outputs": config["scoring_outputs"],
            "simulation_budget": config.get("simulation_budget", 1000),
            "defaults": config["defaults"],
        }

    def _load_test_case_config(self, test_case_id: str) -> dict[str, Any]:
        """Load config.json for a test case.

        Args:
            test_case_id: Test case identifier.

        Returns:
            Parsed config dict.
        """
        config_path = Path.home() / ".zhen" / "test_cases" / test_case_id / "config.json"
        result: dict[str, Any] = json.loads(config_path.read_text(encoding="utf-8"))
        return result
