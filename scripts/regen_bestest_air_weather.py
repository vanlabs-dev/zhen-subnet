"""Regenerate registry/test_cases/bestest_air/weather.json from BOPTEST.

Extracts one year of dry-bulb temperature and global horizontal solar
irradiation from a running BOPTEST instance's bestest_air FMU, writes
them to weather.json in the format the RC network backend consumes.

Usage:
    python scripts/regen_bestest_air_weather.py [--boptest-url URL]

Default BOPTEST URL is http://localhost:8000. Run from repo root so the
output path resolves correctly.

Note: uses httpx (already a Zhen dependency) rather than the requests
library to avoid introducing a new dependency. The sync client is
sufficient for this one-shot script.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path
from typing import Any

import httpx

DEFAULT_BOPTEST_URL = "http://localhost:8000"
TESTCASE = "bestest_air"
HOURS_PER_YEAR = 8760
SECONDS_PER_HOUR = 3600

# Forecast variables we need (names match BOPTEST forecast point IDs, not output IDs)
FORECAST_TEMP_VAR = "TDryBul"
FORECAST_SOLAR_VAR = "HGloHor"

OUTPUT_PATH = Path("registry/test_cases/bestest_air/weather.json")


def _extract_samples(payload: Any, var_name: str) -> list[float]:
    """Pull an array of floats out of a BOPTEST /forecast payload and trim to a year."""
    raw = payload[var_name]
    return [float(x) for x in list(raw)[:HOURS_PER_YEAR]]


def main() -> int:
    """Run the regeneration flow and return a process exit code."""
    parser = argparse.ArgumentParser(description="Regenerate bestest_air weather from BOPTEST")
    parser.add_argument("--boptest-url", default=DEFAULT_BOPTEST_URL)
    parser.add_argument("--timeout", type=float, default=60.0, help="Per-request timeout in seconds")
    args = parser.parse_args()

    boptest_url: str = str(args.boptest_url).rstrip("/")
    timeout: float = float(args.timeout)

    print(f"[1/5] Selecting {TESTCASE} at {boptest_url}...")
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(f"{boptest_url}/testcases/{TESTCASE}/select", timeout=timeout)
        resp.raise_for_status()
        testid: str = str(resp.json()["testid"])
        print(f"      testid={testid}")

        try:
            print("[2/5] Initializing at start_time=0 with warmup_period=0...")
            resp = client.put(
                f"{boptest_url}/initialize/{testid}",
                json={"start_time": 0.0, "warmup_period": 0.0},
                timeout=timeout,
            )
            resp.raise_for_status()

            print(f"[3/5] Requesting {HOURS_PER_YEAR}h forecast at hourly intervals...")
            forecast_payload = {
                "point_names": [FORECAST_TEMP_VAR, FORECAST_SOLAR_VAR],
                "horizon": HOURS_PER_YEAR * SECONDS_PER_HOUR,
                "interval": SECONDS_PER_HOUR,
            }
            resp = client.put(
                f"{boptest_url}/forecast/{testid}",
                json=forecast_payload,
                timeout=timeout * 5,  # year-horizon forecast may be slow
            )
            resp.raise_for_status()
            payload: Any = resp.json()["payload"]

            # /forecast returns N+1 points (t=0 through t=N*interval inclusive).
            # Trim to exactly 8760 hourly samples aligned with the rest of the manifest.
            temp_kelvin = _extract_samples(payload, FORECAST_TEMP_VAR)
            solar_w_m2 = _extract_samples(payload, FORECAST_SOLAR_VAR)

            if len(temp_kelvin) != HOURS_PER_YEAR or len(solar_w_m2) != HOURS_PER_YEAR:
                print(
                    f"      WARNING: forecast returned {len(temp_kelvin)} temp samples, "
                    f"{len(solar_w_m2)} solar samples; expected {HOURS_PER_YEAR}. "
                    "Consider fallback via advance loop.",
                    file=sys.stderr,
                )
                return 2

            print("[4/5] Converting units and validating ranges...")
            temp_celsius = [k - 273.15 for k in temp_kelvin]
            solar = list(solar_w_m2)

            t_min = min(temp_celsius)
            t_max = max(temp_celsius)
            t_mean = sum(temp_celsius) / len(temp_celsius)
            s_min = min(solar)
            s_max = max(solar)
            s_mean = sum(solar) / len(solar)
            print(f"      temperature: min={t_min:.1f}C max={t_max:.1f}C mean={t_mean:.1f}C")
            print(f"      solar_radiation: min={s_min:.1f} max={s_max:.1f} mean={s_mean:.1f} W/m2")

            # Sanity checks against Denver TMY expectations
            if not (-30.0 <= t_min <= -5.0):
                print(
                    f"      WARNING: temperature min {t_min:.1f}C outside expected Denver range [-30, -5]. "
                    "Check that BOPTEST is serving the correct test case.",
                    file=sys.stderr,
                )
            if not (25.0 <= t_max <= 40.0):
                print(
                    f"      WARNING: temperature max {t_max:.1f}C outside expected Denver range [25, 40].",
                    file=sys.stderr,
                )
            if s_min < 0.0 or s_max > 1500.0:
                print(
                    "      WARNING: solar_radiation outside physical range [0, 1500] W/m2.",
                    file=sys.stderr,
                )

            print(f"[5/5] Writing {OUTPUT_PATH}...")
            OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
            with OUTPUT_PATH.open("w") as f:
                json.dump({"temperature": temp_celsius, "solar_radiation": solar}, f)
            print(f"      wrote {len(temp_celsius)} hourly samples")
            return 0

        finally:
            with contextlib.suppress(httpx.HTTPError):
                client.put(f"{boptest_url}/stop/{testid}", timeout=timeout)


if __name__ == "__main__":
    sys.exit(main())
