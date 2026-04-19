"""Schema tests for weather.json files under registry/test_cases/.

Asserts shape and plausibility (length, numeric ranges) of every test case's
weather file. Climate-specific content checks (e.g. Denver vs Brussels TMY)
live in the per-case regeneration scripts, not here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REGISTRY_ROOT = Path(__file__).resolve().parents[2] / "registry" / "test_cases"
TEST_CASES = ["bestest_air", "bestest_hydronic", "bestest_hydronic_heat_pump"]
HOURS_PER_YEAR = 8760

TEMP_MIN_C = -40.0
TEMP_MAX_C = 50.0
SOLAR_MIN_W_M2 = 0.0
SOLAR_MAX_W_M2 = 1500.0


@pytest.mark.parametrize("test_case", TEST_CASES)
def test_weather_file_parses_as_json(test_case: str) -> None:
    """weather.json loads as a dict without error."""
    path = REGISTRY_ROOT / test_case / "weather.json"
    data = json.loads(path.read_text())
    assert isinstance(data, dict)


@pytest.mark.parametrize("test_case", TEST_CASES)
def test_weather_file_schema(test_case: str) -> None:
    """weather.json contains exactly the expected two keys with 8760 samples each."""
    path = REGISTRY_ROOT / test_case / "weather.json"
    data = json.loads(path.read_text())

    assert set(data.keys()) == {"temperature", "solar_radiation"}

    temperature = data["temperature"]
    solar = data["solar_radiation"]

    assert isinstance(temperature, list)
    assert isinstance(solar, list)
    assert len(temperature) == HOURS_PER_YEAR
    assert len(solar) == HOURS_PER_YEAR


@pytest.mark.parametrize("test_case", TEST_CASES)
def test_weather_values_within_plausible_ranges(test_case: str) -> None:
    """Temperature stays in [-40, 50] C and solar stays in [0, 1500] W/m^2."""
    path = REGISTRY_ROOT / test_case / "weather.json"
    data = json.loads(path.read_text())

    for t in data["temperature"]:
        assert isinstance(t, float)
        assert TEMP_MIN_C <= t <= TEMP_MAX_C, f"{test_case}: temperature {t} outside [{TEMP_MIN_C}, {TEMP_MAX_C}]"

    for s in data["solar_radiation"]:
        assert isinstance(s, float)
        assert SOLAR_MIN_W_M2 <= s <= SOLAR_MAX_W_M2, (
            f"{test_case}: solar {s} outside [{SOLAR_MIN_W_M2}, {SOLAR_MAX_W_M2}]"
        )
