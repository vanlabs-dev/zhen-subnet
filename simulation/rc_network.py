"""Resistance-Capacitance thermal network model.

Grey-box building energy model that represents the building as a circuit
of thermal resistors (walls, windows, infiltration) and capacitors (zone
thermal mass). Solves the thermal ODE using forward Euler with 1-hour timestep.
Used as the simplified model backend.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np


@dataclass
class SimulationResult:
    """Container for simulation outputs."""

    outputs: dict[str, list[float]] = field(default_factory=dict)

    def get_outputs(self, names: list[str]) -> dict[str, list[float]]:
        """Return predicted values for the specified scoring output names."""
        return {name: self.outputs[name] for name in names if name in self.outputs}


class RCNetworkBackend:
    """Resistance-Capacitance thermal network model.

    Models a building as a circuit of thermal resistors (walls, roof, infiltration)
    and capacitors (zone thermal mass). Solves the ODE system using forward Euler
    integration with a 1-hour timestep.

    The thermostat supports both heating and cooling behind a has_cooling gate.
    Cooling is active only when the test case declares both hvac_cop_cooling
    (in params or defaults) and cooling_setpoint (in schedules.json); configs
    missing either fall back to heating-only with zero cooling energy output.
    The total_cooling_energy_kWh output is always present in SimulationResult
    (populated with zeros in heating-only mode) so downstream consumers can
    assume a stable output signature.
    """

    def __init__(self, config: dict[str, Any], params: dict[str, float]) -> None:
        """Initialize the RC network backend.

        Args:
            config: Test case configuration dict (from config.json).
            params: Calibratable parameter values from the miner. Falls back
                to config defaults for any missing parameter.
        """
        self.dt: int = 3600  # 1-hour timestep in seconds
        self.weather = self._load_weather(config)
        self.schedules = self._load_schedules(config)

        defaults: dict[str, float] = config["defaults"]
        self.R_wall: np.float64 = np.float64(params.get("wall_r_value", defaults["wall_r_value"]))
        self.R_roof: np.float64 = np.float64(params.get("roof_r_value", defaults["roof_r_value"]))
        self.C_zone: np.float64 = np.float64(params.get("zone_capacitance", defaults["zone_capacitance"]))
        self.ach: np.float64 = np.float64(params.get("infiltration_ach", defaults["infiltration_ach"]))
        self.cop: np.float64 = np.float64(params.get("hvac_cop", defaults["hvac_cop"]))
        self.solar_gain: np.float64 = np.float64(params.get("solar_gain_factor", defaults["solar_gain_factor"]))
        self.cop_cooling: np.float64 | None = (
            np.float64(params["hvac_cop_cooling"])
            if "hvac_cop_cooling" in params
            else np.float64(defaults["hvac_cop_cooling"])
            if "hvac_cop_cooling" in defaults
            else None
        )
        self.has_cooling: bool = self.cop_cooling is not None and "cooling_setpoint" in self.schedules

    def _load_weather(self, config: dict[str, Any]) -> dict[str, np.ndarray[Any, np.dtype[np.float64]]]:
        """Load weather data from the test case directory."""
        test_case_dir = Path.home() / ".zhen" / "test_cases" / config["test_case_id"]
        weather_path = test_case_dir / "weather.json"
        raw = json.loads(weather_path.read_text())
        return {
            "temperature": np.array(raw["temperature"], dtype=np.float64),
            "solar_radiation": np.array(raw["solar_radiation"], dtype=np.float64),
        }

    def _load_schedules(self, config: dict[str, Any]) -> dict[str, np.ndarray[Any, np.dtype[np.float64]]]:
        """Load occupancy and HVAC schedules from the test case directory."""
        test_case_dir = Path.home() / ".zhen" / "test_cases" / config["test_case_id"]
        schedules_path = test_case_dir / "schedules.json"
        raw = json.loads(schedules_path.read_text())
        out: dict[str, np.ndarray[Any, np.dtype[np.float64]]] = {
            "internal_gains": np.array(raw["internal_gains"], dtype=np.float64),
            "heating_setpoint": np.array(raw["heating_setpoint"], dtype=np.float64),
        }
        if "cooling_setpoint" in raw:
            out["cooling_setpoint"] = np.array(raw["cooling_setpoint"], dtype=np.float64)
        return out

    def run(self, start_hour: int, end_hour: int) -> SimulationResult:
        """Solve the thermal ODE for the specified period using forward Euler.

        Args:
            start_hour: First hour of the simulation window (inclusive).
            end_hour: Last hour of the simulation window (exclusive).

        Returns:
            SimulationResult with zone_air_temperature_C, total_heating_energy_kWh,
            and total_cooling_energy_kWh arrays. The cooling array is populated
            with zeros when has_cooling is False.
        """
        n_steps = end_hour - start_hour
        T_zone = np.zeros(n_steps, dtype=np.float64)
        Q_heating = np.zeros(n_steps, dtype=np.float64)
        Q_cooling = np.zeros(n_steps, dtype=np.float64)

        # Initialize zone temperature from outdoor temp at start hour
        T_zone[0] = self.weather["temperature"][start_hour]

        for i in range(1, n_steps):
            hour = start_hour + i
            T_out = self.weather["temperature"][hour]
            Q_solar = self.weather["solar_radiation"][hour] * self.solar_gain
            Q_internal = self.schedules["internal_gains"][hour]

            # Infiltration heat exchange
            # Note: self.ach is an effective infiltration coefficient (W/K),
            # not true ACH. It absorbs building volume into the calibratable
            # parameter. The optimizer finds the correct effective value.
            Q_infiltration = np.float64(1200.0) * self.ach * (T_out - T_zone[i - 1]) / np.float64(3600.0)

            # Heat flow through envelope (walls and roof in PARALLEL)
            # Parallel: Q = dT * (1/R_wall + 1/R_roof), NOT dT / (R_wall + R_roof)
            Q_envelope = (T_out - T_zone[i - 1]) * (np.float64(1.0) / self.R_wall + np.float64(1.0) / self.R_roof)

            Q_total = Q_envelope + Q_solar + Q_internal + Q_infiltration

            T_heat_setpoint = self.schedules["heating_setpoint"][hour]
            Q_hvac = np.float64(0.0)

            if T_zone[i - 1] < T_heat_setpoint:
                # Heating mode: deliver enough heat to reach heating setpoint
                Q_hvac = (T_heat_setpoint - T_zone[i - 1]) * self.C_zone / np.float64(self.dt)
                Q_heating[i] = Q_hvac / self.cop / np.float64(1000.0)
            elif self.has_cooling and self.cop_cooling is not None:
                T_cool_setpoint = self.schedules["cooling_setpoint"][hour]
                if T_zone[i - 1] > T_cool_setpoint:
                    # Cooling mode: extract heat to reach cooling setpoint. Q_hvac
                    # is negative (heat leaves the zone). Q_cooling stores absolute
                    # energy consumption.
                    Q_hvac = -(T_zone[i - 1] - T_cool_setpoint) * self.C_zone / np.float64(self.dt)
                    Q_cooling[i] = abs(Q_hvac) / self.cop_cooling / np.float64(1000.0)
            # else: idle (deadband or cooling unavailable); Q_hvac stays 0

            dT = (Q_total + Q_hvac) * np.float64(self.dt) / self.C_zone
            T_zone[i] = T_zone[i - 1] + dT

        return SimulationResult(
            outputs={
                "zone_air_temperature_C": T_zone.tolist(),
                "total_heating_energy_kWh": Q_heating.tolist(),
                "total_cooling_energy_kWh": Q_cooling.tolist(),
            }
        )
