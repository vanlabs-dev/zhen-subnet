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
        config = self.load_test_case_config(test_case["id"])
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

        config = self.load_test_case_config(test_case["id"])
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

    def build_verification_config(self, test_case: dict[str, Any]) -> dict[str, Any]:
        """Build the verification config by merging manifest entry with config.json.

        Args:
            test_case: Test case dict from manifest.

        Returns:
            Combined config dict with parameter_bounds, scoring_outputs, etc.
        """
        config = self.load_test_case_config(test_case["id"])
        return {
            "id": test_case["id"],
            "parameter_bounds": config["parameter_bounds"],
            "scoring_outputs": config["scoring_outputs"],
            "simulation_budget": config.get("simulation_budget", 1000),
            "defaults": config["defaults"],
        }

    def load_test_case_config(self, test_case_id: str) -> dict[str, Any]:
        """Load config.json for a test case.

        Args:
            test_case_id: Test case identifier.

        Returns:
            Parsed config dict.
        """
        config_path = Path.home() / ".zhen" / "test_cases" / test_case_id / "config.json"
        result: dict[str, Any] = json.loads(config_path.read_text(encoding="utf-8"))
        return result
