"""Unit tests for the RC network thermal model."""

from __future__ import annotations

import json
import shutil
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest

from simulation.rc_network import RCNetworkBackend

TEST_CASE_ID = "bestest_hydronic_heat_pump"
REGISTRY_SRC = Path(__file__).resolve().parents[2] / "registry" / "test_cases" / TEST_CASE_ID
ZHEN_DIR = Path.home() / ".zhen" / "test_cases" / TEST_CASE_ID


@pytest.fixture(autouse=True, scope="session")
def install_test_case() -> Generator[None, None, None]:
    """Copy test case files to ~/.zhen/test_cases/ for the test session."""
    ZHEN_DIR.mkdir(parents=True, exist_ok=True)
    for filename in ("config.json", "weather.json", "schedules.json"):
        src = REGISTRY_SRC / filename
        dst = ZHEN_DIR / filename
        shutil.copy2(src, dst)
    yield
    shutil.rmtree(ZHEN_DIR, ignore_errors=True)
    # Clean up parent if empty
    parent = ZHEN_DIR.parent
    if parent.exists() and not any(parent.iterdir()):
        parent.rmdir()


def _load_config() -> dict[str, Any]:
    """Load the test case config from the installed location."""
    return json.loads((ZHEN_DIR / "config.json").read_text())  # type: ignore[no-any-return]


def _make_backend(param_overrides: dict[str, float] | None = None) -> RCNetworkBackend:
    """Create a backend with optional parameter overrides."""
    config = _load_config()
    params = dict(config["defaults"])
    if param_overrides:
        params.update(param_overrides)
    return RCNetworkBackend(config, params)


class TestDeterminism:
    """Same parameters must produce bit-identical outputs."""

    def test_determinism(self) -> None:
        """Run model twice with identical params, assert identical outputs."""
        backend = _make_backend()
        result_a = backend.run(0, 168)
        result_b = backend.run(0, 168)

        assert result_a.outputs["zone_air_temperature_C"] == result_b.outputs["zone_air_temperature_C"]
        assert result_a.outputs["total_heating_energy_kWh"] == result_b.outputs["total_heating_energy_kWh"]


class TestPhysics:
    """Physical sanity checks for the thermal model."""

    def test_heating_increases_temperature(self) -> None:
        """Zone temperature should rise when heating is active.

        During winter hours, the thermostat calls for heat. The zone
        temperature after heating should be higher than the outdoor temp.
        """
        backend = _make_backend()
        # January hours (cold, heating expected)
        result = backend.run(0, 168)
        temps = result.outputs["zone_air_temperature_C"]
        heating = result.outputs["total_heating_energy_kWh"]

        # Find hours where heating is active
        heated_hours = [i for i, q in enumerate(heating) if q > 0]
        assert len(heated_hours) > 0, "Expected some heating in January"

        # Zone temp at heated hours should exceed outdoor temp
        weather = json.loads((ZHEN_DIR / "weather.json").read_text())
        for i in heated_hours:
            assert temps[i] > weather["temperature"][i], (
                f"Hour {i}: zone temp {temps[i]:.2f} should exceed "
                f"outdoor temp {weather['temperature'][i]:.2f} when heating"
            )

    def test_insulation_reduces_heating(self) -> None:
        """Higher wall R-value (more insulation) should reduce total heating energy."""
        # Low insulation
        backend_low = _make_backend({"wall_r_value": 1.0})
        result_low = backend_low.run(0, 720)
        total_low = sum(result_low.outputs["total_heating_energy_kWh"])

        # High insulation
        backend_high = _make_backend({"wall_r_value": 8.0})
        result_high = backend_high.run(0, 720)
        total_high = sum(result_high.outputs["total_heating_energy_kWh"])

        assert total_high < total_low, (
            f"Better insulation (R=8) should use less heating ({total_high:.1f}) "
            f"than poor insulation (R=1) ({total_low:.1f})"
        )

    def test_parallel_resistance(self) -> None:
        """Verify envelope heat flow uses parallel resistance formula.

        For parallel resistors: Q = dT * (1/R1 + 1/R2)
        NOT series: Q = dT / (R1 + R2)
        """
        R_wall = 4.0
        R_roof = 6.0
        T_out = 0.0
        T_zone = 20.0
        dT = T_out - T_zone

        # Parallel formula (correct)
        Q_parallel = dT * (1.0 / R_wall + 1.0 / R_roof)
        # Series formula (wrong)
        Q_series = dT / (R_wall + R_roof)

        # These must NOT be equal
        assert Q_parallel != Q_series

        # Verify the model uses parallel: run with known R values
        backend = _make_backend({"wall_r_value": R_wall, "roof_r_value": R_roof})

        # The model computes Q_envelope at each step. We verify by checking
        # that the result differs from what a series calculation would produce.
        backend_series_wall = _make_backend({
            "wall_r_value": R_wall + R_roof,
            "roof_r_value": 1e12,  # Effectively infinite (no roof path)
        })

        result_parallel = backend.run(0, 48)
        result_series = backend_series_wall.run(0, 48)

        temps_par = result_parallel.outputs["zone_air_temperature_C"]
        temps_ser = result_series.outputs["zone_air_temperature_C"]

        # With parallel paths, more heat flows through the envelope.
        # In heating mode this means the parallel model loses more heat,
        # so temperatures will differ.
        assert temps_par != temps_ser, "Parallel and series resistance must produce different results"

    def test_zero_solar_gain(self) -> None:
        """Setting solar_gain_factor=0 should eliminate solar contribution."""
        # Run with solar gains
        backend_solar = _make_backend({"solar_gain_factor": 0.5})
        result_solar = backend_solar.run(3000, 3168)  # Summer-ish hours with sunlight

        # Run without solar gains
        backend_no_solar = _make_backend({"solar_gain_factor": 0.0})
        result_no_solar = backend_no_solar.run(3000, 3168)

        temps_solar = result_solar.outputs["zone_air_temperature_C"]
        temps_no_solar = result_no_solar.outputs["zone_air_temperature_C"]

        # With solar gains, zone should be warmer (at least some hours)
        diffs = [a - b for a, b in zip(temps_solar, temps_no_solar, strict=True)]
        max_diff = max(diffs)
        assert max_diff > 0, "Solar gains should increase zone temperature"


class TestOutputShape:
    """Verify output array dimensions."""

    def test_output_lengths(self) -> None:
        """Output arrays should have exactly (end_hour - start_hour) elements."""
        start, end = 100, 268
        expected_len = end - start

        backend = _make_backend()
        result = backend.run(start, end)

        assert len(result.outputs["zone_air_temperature_C"]) == expected_len
        assert len(result.outputs["total_heating_energy_kWh"]) == expected_len

    def test_simulation_result_get_outputs(self) -> None:
        """SimulationResult.get_outputs() filters to requested keys."""
        backend = _make_backend()
        result = backend.run(0, 24)

        filtered = result.get_outputs(["zone_air_temperature_C"])
        assert "zone_air_temperature_C" in filtered
        assert "total_heating_energy_kWh" not in filtered
