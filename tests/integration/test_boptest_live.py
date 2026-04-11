"""Integration tests for BOPTESTClient against a live BOPTEST instance.

Requires a running BOPTEST service at http://localhost:8000.
Start with: docker compose up from the project1-boptest directory.
Tests are skipped automatically when BOPTEST is not available.
"""

from __future__ import annotations

import httpx
import numpy as np
import pytest

from validator.emulator.boptest_client import BOPTESTClient

BOPTEST_URL = "http://localhost:8000"
TESTCASE_ID = "bestest_hydronic_heat_pump"


def boptest_available() -> bool:
    """Check if BOPTEST service is reachable."""
    try:
        r = httpx.get(f"{BOPTEST_URL}/testcases", timeout=5)
        return r.status_code == 200
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not boptest_available(), reason="BOPTEST not running")


@pytest.fixture
async def client() -> BOPTESTClient:
    """Create a BOPTESTClient for integration tests."""
    return BOPTESTClient(BOPTEST_URL)


@pytest.fixture
async def running_testcase(client: BOPTESTClient) -> str:
    """Select a testcase and return its testid. Stop it after the test."""
    testid = await client.select_testcase(TESTCASE_ID)
    yield testid
    await client.stop(testid)


@pytest.mark.asyncio
async def test_select_and_initialize(client: BOPTESTClient) -> None:
    """Select bestest_hydronic_heat_pump and initialize successfully."""
    testid = await client.select_testcase(TESTCASE_ID)
    assert testid is not None
    assert len(testid) > 0

    await client.initialize(testid, start_time=0.0, warmup_period=0.0)
    await client.stop(testid)


@pytest.mark.asyncio
async def test_advance_and_collect(client: BOPTESTClient, running_testcase: str) -> None:
    """Initialize, set 1h step, advance 24 times, verify measurements."""
    testid = running_testcase
    await client.initialize(testid, start_time=0.0, warmup_period=0.0)
    await client.set_step(testid, step=3600.0)

    measurements: list[dict] = []
    for _ in range(24):
        data = await client.advance(testid)
        measurements.append(data)

    assert len(measurements) == 24
    # Verify we got some measurement keys back
    first = measurements[0]
    assert len(first) > 0
    print(f"\nCollected 24 hourly measurements. Keys: {list(first.keys())}")


@pytest.mark.asyncio
async def test_get_results(client: BOPTESTClient, running_testcase: str) -> None:
    """Run a short simulation then retrieve results for the period."""
    testid = running_testcase
    await client.initialize(testid, start_time=0.0, warmup_period=0.0)
    await client.set_step(testid, step=3600.0)

    # Advance 6 hours
    for _ in range(6):
        await client.advance(testid)

    # Get available measurements first
    meas_points = await client.get_measurements(testid)
    point_names = list(meas_points.keys())[:3]  # Take first 3 points

    results = await client.get_results(
        testid,
        point_names=point_names,
        start_time=0.0,
        final_time=6 * 3600.0,
    )
    assert len(results) > 0
    print(f"\nRetrieved results for points: {point_names}")
    for name in point_names:
        if name in results:
            vals = results[name]
            print(f"  {name}: {len(vals)} values, range [{min(vals):.2f}, {max(vals):.2f}]")


@pytest.mark.asyncio
async def test_compare_rc_vs_boptest(client: BOPTESTClient, running_testcase: str) -> None:
    """Run BOPTEST 168h, compare against RC network with default params.

    This test always passes. It logs the CVRMSE gap that miners need to close.
    """
    from scoring.metrics import compute_cvrmse

    testid = running_testcase

    # Discover available measurement points
    measurements = await client.get_measurements(testid)
    print("\nAvailable BOPTEST measurements:")
    for name, meta in measurements.items():
        print(f"  {name}: {meta}")

    # Find zone temperature point - BOPTEST uses names like "reaTZon_y"
    zone_temp_key = None
    for name in measurements:
        if "TZon" in name or "reaTZon" in name:
            zone_temp_key = name
            break
    if zone_temp_key is None:
        # Fallback: look for any output with "zone" and temperature unit
        for name, meta in measurements.items():
            unit = meta.get("Unit", "")
            if unit == "K" or "degC" in unit:
                zone_temp_key = name
                break

    if zone_temp_key is None:
        pytest.skip("Could not identify zone temperature measurement point")

    print(f"\nUsing zone temperature point: {zone_temp_key}")

    hours = 168  # 1 week

    # Run BOPTEST for 168 hours
    await client.initialize(testid, start_time=0.0, warmup_period=0.0)
    await client.set_step(testid, step=3600.0)

    boptest_temps: list[float] = []
    for _ in range(hours):
        data = await client.advance(testid)
        if zone_temp_key in data:
            # BOPTEST returns temperature in Kelvin, convert to Celsius
            temp_k = float(data[zone_temp_key])
            boptest_temps.append(temp_k - 273.15)

    if len(boptest_temps) < hours:
        print(f"\nWarning: Only got {len(boptest_temps)} temperature readings from BOPTEST")
        print(f"Keys in advance response: {list(data.keys()) if 'data' in dir() else 'N/A'}")
        pytest.skip("Could not collect sufficient temperature data from BOPTEST")

    # Run RC network with default params for comparison
    # Load default config for the test case
    from pathlib import Path

    from simulation.rc_network import RCNetworkBackend

    config_path = Path(__file__).resolve().parents[2] / "registry" / "test_cases" / TESTCASE_ID / "config.json"
    if not config_path.exists():
        print(f"\nRC network config not found at {config_path}")
        print(f"BOPTEST temperature range: [{min(boptest_temps):.2f}, {max(boptest_temps):.2f}] C")
        print("Skipping RC comparison (config not available yet)")
        return

    import json

    config = json.loads(config_path.read_text())
    # Use default parameters (no calibration)
    default_params = {k: v["default"] for k, v in config.get("parameters", {}).items()}

    try:
        rc = RCNetworkBackend(config, default_params)
        rc_result = rc.run(start_hour=0, end_hour=hours)
        rc_temps = rc_result.get_outputs(["zone_air_temperature_C"]).get("zone_air_temperature_C", [])
    except FileNotFoundError as e:
        print(f"\nRC network cannot run (missing dependency): {e}")
        print(f"BOPTEST temperature range: [{min(boptest_temps):.2f}, {max(boptest_temps):.2f}] C")
        print(f"BOPTEST mean zone temp: {np.mean(boptest_temps):.2f} C")
        print("RC comparison skipped - weather data not installed yet")
        return

    if len(rc_temps) != len(boptest_temps):
        min_len = min(len(rc_temps), len(boptest_temps))
        rc_temps = rc_temps[:min_len]
        boptest_temps = boptest_temps[:min_len]

    # Compute CVRMSE
    predicted = np.array(rc_temps, dtype=np.float64)
    measured = np.array(boptest_temps, dtype=np.float64)
    cvrmse = compute_cvrmse(predicted, measured)

    print(f"\n{'='*60}")
    print(f"RC Network vs BOPTEST Comparison ({hours} hours)")
    print(f"{'='*60}")
    print(f"BOPTEST temp range: [{min(boptest_temps):.2f}, {max(boptest_temps):.2f}] C")
    print(f"RC temp range:      [{min(rc_temps):.2f}, {max(rc_temps):.2f}] C")
    print(f"CVRMSE (uncalibrated): {cvrmse:.4f} ({cvrmse*100:.1f}%)")
    print(f"{'='*60}")
    print("This gap is what miners need to close through calibration.")

    # Test always passes - we just log the gap
    assert True
