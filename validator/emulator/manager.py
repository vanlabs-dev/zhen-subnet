"""BOPTEST emulator lifecycle management.

Connects to an externally-managed BOPTEST service, runs simulations for
specified time periods, and collects output time-series data for use as
ground truth in calibration rounds.
"""

from __future__ import annotations

import logging
from typing import Any

from validator.emulator.boptest_client import BOPTESTClient

logger = logging.getLogger(__name__)

SECONDS_PER_HOUR = 3600

# Supported unit conversions from BOPTEST native units to Zhen scoring units.
# Each converter takes (raw_values, step_seconds) and returns converted values.
UNIT_CONVERTERS: dict[str, Any] = {
    "kelvin_to_celsius": lambda values, _step_s: [v - 273.15 for v in values],
    "watts_to_kwh": lambda values, step_s: [v * (step_s / 3600.0) / 1000.0 for v in values],
    "none": lambda values, _step_s: values,
}


class BOPTESTManager:
    """Manages interaction with a running BOPTEST service.

    Does NOT start or stop Docker containers. Assumes the BOPTEST service
    is externally managed and reachable at the configured URL.
    """

    def __init__(self, api_url: str) -> None:
        """Initialize the manager with the BOPTEST service URL.

        Args:
            api_url: Base URL of the running BOPTEST service
                (e.g. "http://localhost:8000").
        """
        self.client = BOPTESTClient(api_url)

    async def run_simulation(
        self,
        testcase_id: str,
        start_hour: int,
        end_hour: int,
        scoring_outputs: list[str],
        output_mapping: dict[str, dict[str, str]],
        step_seconds: int = 3600,
        warmup_hours: int = 24,
    ) -> dict[str, list[float]]:
        """Run a BOPTEST simulation and collect scoring output time-series.

        Selects a test case, initializes to the start time, advances
        through the simulation period, retrieves results, and applies
        unit conversions so outputs match the RC model format.

        Args:
            testcase_id: BOPTEST test case identifier
                (e.g. "bestest_hydronic_heat_pump").
            start_hour: First hour of the simulation window (inclusive).
            end_hour: Last hour of the simulation window (exclusive).
            scoring_outputs: List of Zhen scoring output names
                (e.g. ["zone_air_temperature_C", "total_heating_energy_kWh"]).
            output_mapping: Maps Zhen scoring output names to dicts with
                "boptest_var" (BOPTEST variable name) and "unit_conversion"
                (conversion function key from UNIT_CONVERTERS).
            step_seconds: Simulation communication step size in seconds.
                Defaults to 3600 (1 hour).
            warmup_hours: Warmup period in hours before the start of the
                simulation window. Defaults to 24.

        Returns:
            Dict mapping Zhen scoring output names to lists of float values,
            one value per timestep. Units match the RC model output format
            (Celsius for temperature, kWh for energy).

        Raises:
            BOPTESTError: If any BOPTEST API call fails.
            KeyError: If a scoring output has no entry in output_mapping.
            ValueError: If an unknown unit_conversion is specified.
        """
        # Resolve BOPTEST variable names and conversions for requested outputs
        boptest_vars: list[str] = []
        conversions: list[str] = []
        for name in scoring_outputs:
            if name not in output_mapping:
                raise KeyError(
                    f"Scoring output '{name}' has no BOPTEST variable mapping. "
                    f"Add it to boptest_output_mapping in config.json."
                )
            entry = output_mapping[name]
            boptest_vars.append(entry["boptest_var"])
            conversion = entry.get("unit_conversion", "none")
            if conversion not in UNIT_CONVERTERS:
                raise ValueError(
                    f"Unknown unit_conversion '{conversion}' for output '{name}'. "
                    f"Supported: {list(UNIT_CONVERTERS.keys())}"
                )
            conversions.append(conversion)

        # Convert hours to seconds (BOPTEST uses seconds from start of year)
        start_time_s = float(start_hour * SECONDS_PER_HOUR)
        end_time_s = float(end_hour * SECONDS_PER_HOUR)
        warmup_s = float(warmup_hours * SECONDS_PER_HOUR)

        n_steps = end_hour - start_hour
        logger.info(
            f"BOPTEST simulation: testcase={testcase_id}, "
            f"hours={start_hour}-{end_hour} ({n_steps} steps), "
            f"step={step_seconds}s, warmup={warmup_hours}h"
        )

        # 1. Select test case to get a running instance
        testid = await self.client.select_testcase(testcase_id)
        logger.info(f"BOPTEST testid: {testid}")

        try:
            # 2. Set communication step size
            await self.client.set_step(testid, float(step_seconds))

            # 3. Initialize simulation
            await self.client.initialize(testid, start_time_s, warmup_s)

            # 4. Advance through the simulation period
            for step_idx in range(n_steps):
                await self.client.advance(testid)
                if (step_idx + 1) % 100 == 0:
                    logger.info(f"BOPTEST advance: step {step_idx + 1}/{n_steps}")

            logger.info(f"BOPTEST simulation complete: {n_steps} steps advanced")

            # 5. Retrieve results for all requested variables
            results = await self.client.get_results(testid, boptest_vars, start_time_s, end_time_s)

            # 6. Map BOPTEST variables back to Zhen names and apply unit conversions
            output: dict[str, list[float]] = {}
            for zhen_name, boptest_name, conversion in zip(
                scoring_outputs, boptest_vars, conversions, strict=True
            ):
                if boptest_name not in results:
                    logger.warning(
                        f"BOPTEST variable '{boptest_name}' not in results. "
                        f"Available: {list(results.keys())}"
                    )
                    output[zhen_name] = []
                else:
                    raw_values = [float(v) for v in results[boptest_name]]
                    converter = UNIT_CONVERTERS[conversion]
                    converted = converter(raw_values, step_seconds)
                    output[zhen_name] = [float(v) for v in converted]
                    logger.info(
                        f"  {zhen_name}: {len(converted)} values, "
                        f"conversion={conversion}"
                    )

            return output

        finally:
            # 7. Always stop the test instance to free resources
            try:
                await self.client.stop(testid)
                logger.info(f"BOPTEST testid {testid} stopped")
            except Exception as e:
                logger.warning(f"Failed to stop BOPTEST testid {testid}: {e}")
