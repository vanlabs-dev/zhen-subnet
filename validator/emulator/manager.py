"""BOPTEST emulator lifecycle management.

Connects to an externally-managed BOPTEST service, runs simulations for
specified time periods, and collects output time-series data for use as
ground truth in calibration rounds. Handles unit conversion and resampling
to produce hourly data matching the RC model output format.
"""

from __future__ import annotations

import logging
from typing import Any

from validator.emulator.boptest_client import BOPTESTClient

logger = logging.getLogger(__name__)

SECONDS_PER_HOUR = 3600


def _kelvin_to_celsius(values: list[float], _internal_step_s: float) -> list[float]:
    """Convert Kelvin to Celsius."""
    return [v - 273.15 for v in values]


def _watts_to_kwh(values: list[float], internal_step_s: float) -> list[float]:
    """Convert instantaneous Watts to energy in kWh per sample interval.

    Each sample represents power sustained over internal_step_s seconds.
    Energy per sample = watts * (internal_step_s / 3600) / 1000.
    """
    factor = internal_step_s / 3600.0 / 1000.0
    return [v * factor for v in values]


def _identity(values: list[float], _internal_step_s: float) -> list[float]:
    """No-op conversion."""
    return values


# Supported unit conversions from BOPTEST native units to Zhen scoring units.
# Each converter takes (raw_values, internal_step_seconds) and returns
# converted values of the same length.
UNIT_CONVERTERS: dict[str, Any] = {
    "kelvin_to_celsius": _kelvin_to_celsius,
    "watts_to_kwh": _watts_to_kwh,
    "none": _identity,
}

# Supported hourly resampling methods.
RESAMPLE_METHODS: dict[str, Any] = {
    "mean": lambda bucket: sum(bucket) / len(bucket) if bucket else 0.0,
    "sum": lambda bucket: sum(bucket),
}


def _resample_to_hourly(
    values: list[float],
    n_hours: int,
    method: str,
) -> list[float]:
    """Resample sub-hourly data into hourly values by chunking.

    Divides the values array into n_hours equal chunks and applies
    the aggregation method to each chunk. No timestamps needed.

    Args:
        values: Data values (already unit-converted), evenly distributed
            across the time window.
        n_hours: Expected number of hourly output values.
        method: Aggregation method ("mean" or "sum").

    Returns:
        List of exactly n_hours float values.

    Raises:
        ValueError: If method is unknown or values cannot be evenly chunked.
    """
    if method not in RESAMPLE_METHODS:
        raise ValueError(f"Unknown resample_method '{method}'. Supported: {list(RESAMPLE_METHODS.keys())}")

    n_values = len(values)
    if n_values == 0 or n_hours == 0:
        return [0.0] * n_hours

    aggregator = RESAMPLE_METHODS[method]
    values_per_hour = n_values // n_hours
    remainder = n_values % n_hours

    if remainder != 0:
        logger.warning(
            f"Resample: {n_values} values not evenly divisible by {n_hours} hours "
            f"(remainder={remainder}). Truncating last {remainder} samples."
        )

    result: list[float] = []
    for hour_idx in range(n_hours):
        start = hour_idx * values_per_hour
        end = start + values_per_hour
        chunk = values[start:end]
        if chunk:
            result.append(float(aggregator(chunk)))
        else:
            logger.warning(f"Resample hour {hour_idx}: empty chunk, using 0.0")
            result.append(0.0)

    return result


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
        through the simulation period, retrieves results, applies unit
        conversions, and resamples to hourly resolution matching the
        RC model output format.

        Args:
            testcase_id: BOPTEST test case identifier
                (e.g. "bestest_hydronic_heat_pump").
            start_hour: First hour of the simulation window (inclusive).
            end_hour: Last hour of the simulation window (exclusive).
            scoring_outputs: List of Zhen scoring output names
                (e.g. ["zone_air_temperature_C", "total_heating_energy_kWh"]).
            output_mapping: Maps Zhen scoring output names to dicts with
                "boptest_var" (BOPTEST variable name), "unit_conversion"
                (conversion key), and "resample_method" ("mean" or "sum").
            step_seconds: Simulation communication step size in seconds.
                Defaults to 3600 (1 hour).
            warmup_hours: Warmup period in hours before the start of the
                simulation window. Defaults to 24.

        Returns:
            Dict mapping Zhen scoring output names to lists of float values,
            exactly one value per hour. Units match the RC model output
            (Celsius for temperature, kWh for energy).

        Raises:
            BOPTESTError: If any BOPTEST API call fails.
            KeyError: If a scoring output has no entry in output_mapping.
            ValueError: If an unknown unit_conversion or resample_method
                is specified.
        """
        # Resolve BOPTEST variable names, conversions, and resample methods
        boptest_vars: list[str] = []
        conversions: list[str] = []
        resample_methods: list[str] = []
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
            resample = entry.get("resample_method", "mean")
            if resample not in RESAMPLE_METHODS:
                raise ValueError(
                    f"Unknown resample_method '{resample}' for output '{name}'. "
                    f"Supported: {list(RESAMPLE_METHODS.keys())}"
                )
            resample_methods.append(resample)

        # Convert hours to seconds (BOPTEST uses seconds from start of year)
        start_time_s = float(start_hour * SECONDS_PER_HOUR)
        end_time_s = float(end_hour * SECONDS_PER_HOUR)
        warmup_s = float(warmup_hours * SECONDS_PER_HOUR)
        total_seconds = float(n_hours := end_hour - start_hour) * SECONDS_PER_HOUR

        logger.info(
            f"BOPTEST simulation: testcase={testcase_id}, "
            f"hours={start_hour}-{end_hour} ({n_hours} hours), "
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
            # Suppress httpx request logging during the advance loop to avoid
            # hundreds of "HTTP Request: POST .../advance" lines per round.
            httpx_logger = logging.getLogger("httpx")
            httpx_level = httpx_logger.level
            httpx_logger.setLevel(logging.WARNING)
            try:
                n_advance_steps = int((end_time_s - start_time_s) / step_seconds)
                for step_idx in range(n_advance_steps):
                    await self.client.advance(testid)
                    if (step_idx + 1) % 100 == 0:
                        logger.info(f"BOPTEST advance: step {step_idx + 1}/{n_advance_steps}")
            finally:
                httpx_logger.setLevel(httpx_level)

            logger.info(f"BOPTEST simulation complete: {n_advance_steps} steps advanced")

            # 5-6. Fetch each variable (without "time"), apply unit conversion,
            # and resample to hourly by chunking.
            output: dict[str, list[float]] = {}
            for zhen_name, boptest_name, conversion, resample in zip(
                scoring_outputs,
                boptest_vars,
                conversions,
                resample_methods,
                strict=True,
            ):
                var_results = await self.client.get_results(testid, [boptest_name], start_time_s, end_time_s)

                if boptest_name not in var_results:
                    logger.warning(
                        f"BOPTEST variable '{boptest_name}' not in results. Available: {list(var_results.keys())}"
                    )
                    output[zhen_name] = [0.0] * n_hours
                    continue

                raw_values = [float(v) for v in var_results[boptest_name]]
                n_samples = len(raw_values)
                logger.info(f"  {zhen_name} ({boptest_name}): {n_samples} raw samples")

                # Compute the internal reporting step from array length
                internal_step_s = total_seconds / n_samples if n_samples > 0 else 0.0

                # Apply unit conversion
                converter = UNIT_CONVERTERS[conversion]
                converted = converter(raw_values, internal_step_s)
                assert len(converted) == n_samples, (
                    f"Unit converter changed array length: {n_samples} -> {len(converted)} for {boptest_name}"
                )

                logger.info(
                    f"  {zhen_name}: {n_samples} samples, internal_step={internal_step_s:.1f}s, conversion={conversion}"
                )

                # Resample to hourly by chunking
                hourly = _resample_to_hourly(converted, n_hours, resample)
                output[zhen_name] = hourly
                logger.info(f"  {zhen_name}: {n_samples} -> {len(hourly)} hourly (resample={resample})")

            return output

        finally:
            # 7. Always stop the test instance to free resources
            try:
                await self.client.stop(testid)
                logger.info(f"BOPTEST testid {testid} stopped")
            except Exception as e:
                logger.warning(f"Failed to stop BOPTEST testid {testid}: {e}")
