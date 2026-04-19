"""Unit tests for the RC network thermal model."""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable, Generator
from pathlib import Path
from typing import Any

import pytest

from simulation.rc_network import RCNetworkBackend

TEST_CASE_ID = "bestest_hydronic_heat_pump"
REGISTRY_SRC = Path(__file__).resolve().parents[2] / "registry" / "test_cases" / TEST_CASE_ID
ZHEN_DIR = Path.home() / ".zhen" / "test_cases" / TEST_CASE_ID


def _write_cooling_test_case(
    tmp_path: Path,
    weather_temp: float = 30.0,
    cool_setpoint: float = 24.0,
    heat_setpoint: float = 20.0,
    *,
    with_cooling_setpoint: bool = True,
    with_cooling_cop: bool = True,
    n_hours: int = 48,
) -> tuple[dict[str, Any], dict[str, float], Path]:
    """Write a minimal test case with cooling-enabled schedule for RC tests.

    Files land under ~/.zhen/test_cases/cooling_rc_<tmp_path.name>/ so the
    RCNetworkBackend can resolve them via its config["test_case_id"] lookup.
    Returns (config, params, tc_dir); callers must remove tc_dir on teardown.

    Args:
        tmp_path: Pytest tmp_path; its name supplies a unique test_case_id.
        weather_temp: Constant outdoor temperature (C) for every hour.
        cool_setpoint: Cooling setpoint (C) when with_cooling_setpoint is True.
        heat_setpoint: Heating setpoint (C) for every hour.
        with_cooling_setpoint: Include cooling_setpoint in schedules.json.
        with_cooling_cop: Include hvac_cop_cooling in both params and defaults.
        n_hours: Length of the weather and schedule arrays.
    """
    tc_id = f"cooling_rc_{tmp_path.name}"
    tc_dir = Path.home() / ".zhen" / "test_cases" / tc_id
    tc_dir.mkdir(parents=True, exist_ok=True)

    weather = {
        "temperature": [weather_temp] * n_hours,
        "solar_radiation": [0.0] * n_hours,
    }
    (tc_dir / "weather.json").write_text(json.dumps(weather))

    schedules: dict[str, list[float]] = {
        "internal_gains": [0.0] * n_hours,
        "heating_setpoint": [heat_setpoint] * n_hours,
    }
    if with_cooling_setpoint:
        schedules["cooling_setpoint"] = [cool_setpoint] * n_hours
    (tc_dir / "schedules.json").write_text(json.dumps(schedules))

    defaults: dict[str, float] = {
        "wall_r_value": 3.5,
        "roof_r_value": 5.0,
        "zone_capacitance": 200000.0,
        "infiltration_ach": 0.5,
        "hvac_cop": 3.5,
        "solar_gain_factor": 0.4,
    }
    if with_cooling_cop:
        defaults["hvac_cop_cooling"] = 3.0

    config: dict[str, Any] = {
        "test_case_id": tc_id,
        "defaults": defaults,
    }
    (tc_dir / "config.json").write_text(json.dumps(config))

    params = dict(defaults)
    return config, params, tc_dir


@pytest.fixture
def cooling_tc(
    tmp_path: Path,
) -> Generator[Callable[..., tuple[dict[str, Any], dict[str, float]]], None, None]:
    """Factory fixture that writes cooling-enabled test cases and cleans up.

    Yields a callable accepting the same kwargs as _write_cooling_test_case
    (except tmp_path, which is bound from the fixture). Each created test
    case directory is removed during teardown.
    """
    created: list[Path] = []

    def _factory(**kwargs: Any) -> tuple[dict[str, Any], dict[str, float]]:
        config, params, tc_dir = _write_cooling_test_case(tmp_path, **kwargs)
        created.append(tc_dir)
        return config, params

    yield _factory

    for p in created:
        shutil.rmtree(p, ignore_errors=True)


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
        backend_series_wall = _make_backend(
            {
                "wall_r_value": R_wall + R_roof,
                "roof_r_value": 1e12,  # Effectively infinite (no roof path)
            }
        )

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


class TestCooling:
    """Coverage for the dual-mode thermostat and the has_cooling gate."""

    def test_cooling_mode_activates_when_configured(
        self,
        cooling_tc: Callable[..., tuple[dict[str, Any], dict[str, float]]],
    ) -> None:
        """Warm weather with cooling setpoint and cop produces non-zero cooling energy."""
        config, params = cooling_tc(weather_temp=30.0, cool_setpoint=24.0)
        backend = RCNetworkBackend(config, params)
        result = backend.run(0, 48)

        cooling = result.outputs["total_cooling_energy_kWh"]
        assert any(q > 0 for q in cooling), "Expected some cooling energy at 30C outdoor"

    def test_heating_still_works_with_cooling_capable_config(
        self,
        cooling_tc: Callable[..., tuple[dict[str, Any], dict[str, float]]],
    ) -> None:
        """Cold weather with cooling-capable config still triggers heating, never cooling."""
        config, params = cooling_tc(weather_temp=5.0, cool_setpoint=24.0)
        backend = RCNetworkBackend(config, params)
        result = backend.run(0, 48)

        heating = result.outputs["total_heating_energy_kWh"]
        cooling = result.outputs["total_cooling_energy_kWh"]

        assert any(q > 0 for q in heating), "Expected heating at 5C outdoor"
        assert all(q == 0 for q in cooling), "Cooling must stay at zero when zone is below heat setpoint"

    def test_idle_in_deadband(
        self,
        cooling_tc: Callable[..., tuple[dict[str, Any], dict[str, float]]],
    ) -> None:
        """Zone initialized inside the deadband remains idle for both HVAC modes."""
        config, params = cooling_tc(weather_temp=22.0, cool_setpoint=24.0, heat_setpoint=20.0)
        backend = RCNetworkBackend(config, params)
        result = backend.run(0, 48)

        heating = result.outputs["total_heating_energy_kWh"]
        cooling = result.outputs["total_cooling_energy_kWh"]

        assert all(q == 0 for q in heating), "Heating must be zero in deadband"
        assert all(q == 0 for q in cooling), "Cooling must be zero in deadband"

    def test_backward_compat_missing_cooling_setpoint(self) -> None:
        """Existing heating-only schedule with a cooling cop param still runs heating-only."""
        config = _load_config()
        params = dict(config["defaults"])
        params["hvac_cop_cooling"] = 3.0  # cop provided, but schedule has no cooling_setpoint

        backend = RCNetworkBackend(config, params)
        result = backend.run(0, 168)

        assert backend.has_cooling is False
        cooling = result.outputs["total_cooling_energy_kWh"]
        assert all(q == 0 for q in cooling)

    def test_backward_compat_missing_cooling_cop_param(
        self,
        cooling_tc: Callable[..., tuple[dict[str, Any], dict[str, float]]],
    ) -> None:
        """Schedule with cooling_setpoint but no hvac_cop_cooling falls back to heating-only."""
        config, params = cooling_tc(weather_temp=30.0, with_cooling_cop=False)
        # Helper omits hvac_cop_cooling from defaults when with_cooling_cop is False;
        # params was built from defaults so it also lacks the key.
        assert "hvac_cop_cooling" not in config["defaults"]
        assert "hvac_cop_cooling" not in params

        backend = RCNetworkBackend(config, params)
        result = backend.run(0, 48)

        assert backend.has_cooling is False
        cooling = result.outputs["total_cooling_energy_kWh"]
        assert all(q == 0 for q in cooling)

    def test_cooling_energy_reported_as_positive(
        self,
        cooling_tc: Callable[..., tuple[dict[str, Any], dict[str, float]]],
    ) -> None:
        """Cooling energy is reported as absolute consumption (never negative)."""
        config, params = cooling_tc(weather_temp=30.0, cool_setpoint=24.0)
        backend = RCNetworkBackend(config, params)
        result = backend.run(0, 48)

        cooling = result.outputs["total_cooling_energy_kWh"]
        assert all(q >= 0 for q in cooling)

    def test_simulation_result_always_contains_five_outputs(self) -> None:
        """Heating-only configs still expose all five output keys (cooling as zeros)."""
        backend = _make_backend()
        result = backend.run(0, 24)

        assert set(result.outputs.keys()) == {
            "zone_air_temperature_C",
            "total_heating_energy_kWh",
            "total_heating_thermal_kWh",
            "total_cooling_energy_kWh",
            "total_cooling_thermal_kWh",
        }
        assert all(q == 0 for q in result.outputs["total_cooling_energy_kWh"])
        assert all(q == 0 for q in result.outputs["total_cooling_thermal_kWh"])

    def test_thermal_and_electrical_heating_differ_by_cop(
        self,
        cooling_tc: Callable[..., tuple[dict[str, Any], dict[str, float]]],
    ) -> None:
        """During heating, thermal equals electrical times COP; idle steps are zero."""
        config, params = cooling_tc(weather_temp=5.0, cool_setpoint=24.0)
        params["hvac_cop"] = 3.0
        backend = RCNetworkBackend(config, params)
        result = backend.run(0, 48)

        electrical = result.outputs["total_heating_energy_kWh"]
        thermal = result.outputs["total_heating_thermal_kWh"]

        active_steps = [i for i, q in enumerate(electrical) if q > 0]
        assert active_steps, "Expected some active heating steps at 5C outdoor"

        for i in active_steps:
            assert thermal[i] == pytest.approx(electrical[i] * 3.0)

        for i, q in enumerate(electrical):
            if q == 0:
                assert thermal[i] == 0

    def test_thermal_and_electrical_cooling_differ_by_cop(
        self,
        cooling_tc: Callable[..., tuple[dict[str, Any], dict[str, float]]],
    ) -> None:
        """During cooling, thermal equals electrical times cooling COP; idle steps are zero."""
        config, params = cooling_tc(weather_temp=30.0, cool_setpoint=24.0)
        params["hvac_cop_cooling"] = 2.5
        backend = RCNetworkBackend(config, params)
        result = backend.run(0, 48)

        electrical = result.outputs["total_cooling_energy_kWh"]
        thermal = result.outputs["total_cooling_thermal_kWh"]

        active_steps = [i for i, q in enumerate(electrical) if q > 0]
        assert active_steps, "Expected some active cooling steps at 30C outdoor"

        for i in active_steps:
            assert thermal[i] == pytest.approx(electrical[i] * 2.5)

        for i, q in enumerate(electrical):
            if q == 0:
                assert thermal[i] == 0

    def test_thermal_outputs_always_present(
        self,
        cooling_tc: Callable[..., tuple[dict[str, Any], dict[str, float]]],
    ) -> None:
        """Both thermal output keys exist regardless of whether the mode was active."""
        # Heating-only (existing registry fixture)
        heating_result = _make_backend().run(0, 24)
        assert "total_heating_thermal_kWh" in heating_result.outputs
        assert "total_cooling_thermal_kWh" in heating_result.outputs

        # Cooling-enabled
        config, params = cooling_tc(weather_temp=30.0, cool_setpoint=24.0)
        cooling_result = RCNetworkBackend(config, params).run(0, 48)
        assert "total_heating_thermal_kWh" in cooling_result.outputs
        assert "total_cooling_thermal_kWh" in cooling_result.outputs

    def test_thermal_outputs_non_negative(
        self,
        cooling_tc: Callable[..., tuple[dict[str, Any], dict[str, float]]],
    ) -> None:
        """Thermal arrays hold absolute magnitudes and must never be negative."""
        config, params = cooling_tc(weather_temp=30.0, cool_setpoint=24.0)
        result = RCNetworkBackend(config, params).run(0, 48)
        assert all(q >= 0 for q in result.outputs["total_heating_thermal_kWh"])
        assert all(q >= 0 for q in result.outputs["total_cooling_thermal_kWh"])

    @pytest.mark.parametrize(
        ("with_cooling_cop", "with_cooling_setpoint", "expected"),
        [
            (True, True, True),
            (True, False, False),
            (False, True, False),
            (False, False, False),
        ],
    )
    def test_has_cooling_flag_gates_correctly(
        self,
        cooling_tc: Callable[..., tuple[dict[str, Any], dict[str, float]]],
        with_cooling_cop: bool,
        with_cooling_setpoint: bool,
        expected: bool,
    ) -> None:
        """has_cooling is True only when both the cop param and the schedule entry exist."""
        config, params = cooling_tc(
            with_cooling_cop=with_cooling_cop,
            with_cooling_setpoint=with_cooling_setpoint,
        )
        backend = RCNetworkBackend(config, params)
        assert backend.has_cooling is expected
