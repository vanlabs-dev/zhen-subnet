"""BOPTEST emulator lifecycle management.

Connects to an externally-managed BOPTEST service, runs simulations for
specified time periods, and collects output time-series data for use as
ground truth in calibration rounds.
"""

from __future__ import annotations

import logging

from validator.emulator.boptest_client import BOPTESTClient

logger = logging.getLogger(__name__)

SECONDS_PER_HOUR = 3600


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
        output_mapping: dict[str, str],
        step_seconds: int = 3600,
        warmup_hours: int = 24,
    ) -> dict[str, list[float]]:
        """Run a BOPTEST simulation and collect scoring output time-series.

        Selects a test case, initializes to the start time, advances
        through the simulation period, and retrieves results for the
        requested output variables.

        Args:
            testcase_id: BOPTEST test case identifier
                (e.g. "bestest_hydronic_heat_pump").
            start_hour: First hour of the simulation window (inclusive).
            end_hour: Last hour of the simulation window (exclusive).
            scoring_outputs: List of Zhen scoring output names
                (e.g. ["zone_air_temperature_C", "total_heating_energy_kWh"]).
            output_mapping: Maps Zhen scoring output names to BOPTEST
                variable names (e.g. {"zone_air_temperature_C": "reaTZon_y"}).
            step_seconds: Simulation communication step size in seconds.
                Defaults to 3600 (1 hour).
            warmup_hours: Warmup period in hours before the start of the
                simulation window. Defaults to 24.

        Returns:
            Dict mapping Zhen scoring output names to lists of float values,
            one value per timestep. Same format as RCNetworkBackend output.

        Raises:
            BOPTESTError: If any BOPTEST API call fails.
            KeyError: If a scoring output has no entry in output_mapping.
        """
        # Resolve BOPTEST variable names for requested outputs
        boptest_vars = []
        for name in scoring_outputs:
            if name not in output_mapping:
                raise KeyError(
                    f"Scoring output '{name}' has no BOPTEST variable mapping. "
                    f"Add it to boptest_output_mapping in config.json."
                )
            boptest_vars.append(output_mapping[name])

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
            results = await self.client.get_results(
                testid, boptest_vars, start_time_s, end_time_s
            )

            # 6. Map BOPTEST variable names back to Zhen scoring output names
            output: dict[str, list[float]] = {}
            for zhen_name, boptest_name in zip(scoring_outputs, boptest_vars, strict=True):
                if boptest_name not in results:
                    logger.warning(
                        f"BOPTEST variable '{boptest_name}' not in results. "
                        f"Available: {list(results.keys())}"
                    )
                    output[zhen_name] = []
                else:
                    raw_values = results[boptest_name]
                    output[zhen_name] = [float(v) for v in raw_values]

            return output

        finally:
            # 7. Always stop the test instance to free resources
            try:
                await self.client.stop(testid)
                logger.info(f"BOPTEST testid {testid} stopped")
            except Exception as e:
                logger.warning(f"Failed to stop BOPTEST testid {testid}: {e}")
