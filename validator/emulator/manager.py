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


def _kelvin_to_celsius(values: list[float], _timestamps: list[float]) -> list[float]:
    """Convert Kelvin to Celsius."""
    return [v - 273.15 for v in values]


def _watts_to_kwh(values: list[float], timestamps: list[float]) -> list[float]:
    """Convert instantaneous Watts to energy in kWh per interval.

    Uses actual timestamp deltas to compute energy for each interval,
    so the conversion is correct regardless of BOPTEST reporting resolution.
    """
    if len(values) < 2:
        return values
    result: list[float] = []
    for i in range(1, len(values)):
        dt_s = timestamps[i] - timestamps[i - 1]
        dt_h = dt_s / 3600.0
        kwh = values[i] * dt_h / 1000.0
        result.append(kwh)
    return result


def _identity(values: list[float], _timestamps: list[float]) -> list[float]:
    """No-op conversion."""
    return values


# Supported unit conversions from BOPTEST native units to Zhen scoring units.
# Each converter takes (raw_values, timestamps_seconds) and returns converted values.
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
    timestamps: list[float],
    start_hour: int,
    n_hours: int,
    method: str,
) -> list[float]:
    """Resample sub-hourly data into hourly buckets.

    Groups values by the hour they fall into (based on timestamps in
    seconds from start of year) and applies the aggregation method.

    Args:
        values: Data values (already unit-converted).
        timestamps: Corresponding timestamps in seconds from start of year.
            For watts_to_kwh the conversion drops the first timestamp, so
            timestamps here should match the length of values.
        start_hour: First hour of the window (inclusive).
        n_hours: Expected number of hourly output values.
        method: Aggregation method ("mean" or "sum").

    Returns:
        List of exactly n_hours float values.
    """
    if method not in RESAMPLE_METHODS:
        raise ValueError(f"Unknown resample_method '{method}'. Supported: {list(RESAMPLE_METHODS.keys())}")

    aggregator = RESAMPLE_METHODS[method]

    # Pre-allocate buckets for each hour
    buckets: list[list[float]] = [[] for _ in range(n_hours)]

    start_s = float(start_hour * SECONDS_PER_HOUR)
    for val, ts in zip(values, timestamps, strict=True):
        hour_idx = int((ts - start_s) / SECONDS_PER_HOUR)
        # Clamp to valid range (timestamps at exact boundaries)
        if hour_idx >= n_hours:
            hour_idx = n_hours - 1
        if hour_idx < 0:
            hour_idx = 0
        buckets[hour_idx].append(val)

    result: list[float] = []
    for i, bucket in enumerate(buckets):
        if bucket:
            result.append(float(aggregator(bucket)))
        else:
            logger.warning(f"Resample hour {start_hour + i}: empty bucket, using 0.0")
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

        n_hours = end_hour - start_hour
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
            n_advance_steps = int((end_time_s - start_time_s) / step_seconds)
            for step_idx in range(n_advance_steps):
                await self.client.advance(testid)
                if (step_idx + 1) % 100 == 0:
                    logger.info(f"BOPTEST advance: step {step_idx + 1}/{n_advance_steps}")

            logger.info(f"BOPTEST simulation complete: {n_advance_steps} steps advanced")

            # 5. Retrieve results (include "time" for timestamp-aware processing)
            all_vars = ["time", *boptest_vars]
            results = await self.client.get_results(testid, all_vars, start_time_s, end_time_s)

            timestamps = [float(t) for t in results["time"]]
            logger.info(f"BOPTEST returned {len(timestamps)} datapoints over {n_hours} hours")

            # 6. Convert units, resample to hourly, and map to Zhen output names
            output: dict[str, list[float]] = {}
            for zhen_name, boptest_name, conversion, resample in zip(
                scoring_outputs, boptest_vars, conversions, resample_methods, strict=True
            ):
                if boptest_name not in results:
                    logger.warning(
                        f"BOPTEST variable '{boptest_name}' not in results. Available: {list(results.keys())}"
                    )
                    output[zhen_name] = [0.0] * n_hours
                    continue

                raw_values = [float(v) for v in results[boptest_name]]

                # Apply unit conversion (uses timestamps for interval-aware conversions)
                converter = UNIT_CONVERTERS[conversion]
                converted = converter(raw_values, timestamps)

                # watts_to_kwh produces N-1 values from N inputs (each value
                # is energy over the interval ending at timestamps[i]).
                # Trim timestamps to match: use the trailing N-1 timestamps.
                n_converted = len(converted)
                resample_ts = timestamps[-n_converted:] if n_converted < len(timestamps) else timestamps

                logger.info(
                    f"  {zhen_name}: {len(raw_values)} raw -> {n_converted} converted, "
                    f"{len(resample_ts)} timestamps after conversion"
                )

                # Resample to hourly resolution
                hourly = _resample_to_hourly(converted, resample_ts, start_hour, n_hours, resample)
                output[zhen_name] = hourly
                logger.info(
                    f"  {zhen_name}: {n_converted} converted -> {len(hourly)} hourly "
                    f"(conversion={conversion}, resample={resample})"
                )

            return output

        finally:
            # 7. Always stop the test instance to free resources
            try:
                await self.client.stop(testid)
                logger.info(f"BOPTEST testid {testid} stopped")
            except Exception as e:
                logger.warning(f"Failed to stop BOPTEST testid {testid}: {e}")
