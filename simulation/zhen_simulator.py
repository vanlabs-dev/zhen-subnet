"""Unified ZhenSimulator interface.

Abstracts simulation backends (RC network, reduced EnergyPlus) behind a
common interface. Loads test case configuration from the local registry,
initializes the appropriate backend, and runs simulations for specified
time periods.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from simulation.rc_network import RCNetworkBackend, SimulationResult


class ZhenSimulator:
    """Unified simulation interface for all model backends.

    Loads test case configuration from the local registry directory,
    initializes the appropriate backend based on simplified_model_type,
    and delegates simulation runs to the backend.
    """

    def __init__(self, test_case_id: str, params: dict[str, float]) -> None:
        """Initialize the simulator for a given test case.

        Args:
            test_case_id: Identifier for the test case (matches directory name).
            params: Calibratable parameter values from the miner.
        """
        self.test_case_id = test_case_id
        self.config = self._load_config(test_case_id)
        self.backend = self._init_backend(params)
        self._last_result: SimulationResult | None = None

    def _load_config(self, test_case_id: str) -> dict[str, Any]:
        """Load config.json from the local test case directory."""
        config_path = Path.home() / ".zhen" / "test_cases" / test_case_id / "config.json"
        return json.loads(config_path.read_text())  # type: ignore[no-any-return]

    def _init_backend(self, params: dict[str, float]) -> RCNetworkBackend:
        """Initialize the appropriate simulation backend from config."""
        model_type = self.config["simplified_model_type"]
        if model_type == "rc_network":
            return RCNetworkBackend(self.config, params)
        raise ValueError(f"Unknown model type: {model_type}")

    def run(self, start_hour: int, end_hour: int) -> SimulationResult:
        """Run the simulation for the specified period.

        Args:
            start_hour: First hour of the simulation window (inclusive).
            end_hour: Last hour of the simulation window (exclusive).

        Returns:
            SimulationResult containing output time-series.
        """
        self._last_result = self.backend.run(start_hour, end_hour)
        return self._last_result

    def get_outputs(self, output_names: list[str]) -> dict[str, list[float]]:
        """Return predicted values for the specified scoring output names.

        Must be called after run().

        Args:
            output_names: List of scoring output names to retrieve.

        Returns:
            Dict mapping output names to value lists.

        Raises:
            RuntimeError: If called before run().
        """
        if self._last_result is None:
            raise RuntimeError("Call run() before get_outputs()")
        return self._last_result.get_outputs(output_names)
