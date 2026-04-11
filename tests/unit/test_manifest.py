"""Unit tests for the ManifestLoader.

Tests loading, querying, and validating manifest.json files.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from validator.registry.manifest import ManifestLoader

MANIFEST_PATH = Path(__file__).resolve().parents[2] / "registry" / "manifest.json"


@pytest.fixture
def loader() -> ManifestLoader:
    """Create a ManifestLoader instance."""
    return ManifestLoader()


def test_load_valid_manifest(loader: ManifestLoader) -> None:
    """Loading the real manifest.json succeeds and has expected structure."""
    manifest = loader.load(MANIFEST_PATH)
    assert "version" in manifest
    assert "test_cases" in manifest
    assert isinstance(manifest["test_cases"], list)
    assert len(manifest["test_cases"]) > 0


def test_get_test_case(loader: ManifestLoader) -> None:
    """Looking up bestest_hydronic_heat_pump returns correct fields."""
    manifest = loader.load(MANIFEST_PATH)
    tc = loader.get_test_case(manifest, "bestest_hydronic_heat_pump")
    assert tc is not None
    assert tc["id"] == "bestest_hydronic_heat_pump"
    assert tc["simplified_model_type"] == "rc_network"
    assert tc["parameter_count"] == 6
    assert "zone_air_temperature_C" in tc["scoring_outputs"]
    assert "total_heating_energy_kWh" in tc["scoring_outputs"]


def test_get_missing_test_case(loader: ManifestLoader) -> None:
    """Looking up a nonexistent test case returns None."""
    manifest = loader.load(MANIFEST_PATH)
    tc = loader.get_test_case(manifest, "nonexistent_test_case_xyz")
    assert tc is None


def test_validate_manifest_valid(loader: ManifestLoader) -> None:
    """Real manifest passes validation with no errors."""
    manifest = loader.load(MANIFEST_PATH)
    errors = loader.validate_manifest(manifest)
    assert errors == []


def test_validate_manifest_missing_fields(loader: ManifestLoader) -> None:
    """Manifest with missing required fields returns errors."""
    bad_manifest = {
        "version": "v0.0.1",
        "test_cases": [{"id": "incomplete_case"}],
    }
    errors = loader.validate_manifest(bad_manifest)
    assert len(errors) > 0
    field_names_in_errors = " ".join(errors)
    assert "simplified_model_type" in field_names_in_errors
    assert "parameter_count" in field_names_in_errors
    assert "scoring_outputs" in field_names_in_errors


def test_validate_manifest_missing_version(loader: ManifestLoader) -> None:
    """Manifest without version key is flagged."""
    bad_manifest: dict[str, list[object]] = {"test_cases": []}
    errors = loader.validate_manifest(bad_manifest)
    assert any("version" in e for e in errors)


def test_validate_manifest_invalid_types(loader: ManifestLoader) -> None:
    """Manifest with wrong types returns errors."""
    bad_manifest = {
        "version": "v0.0.1",
        "test_cases": [
            {
                "id": "bad_types",
                "simplified_model_type": "rc_network",
                "parameter_count": "six",
                "scoring_outputs": "not_a_list",
            }
        ],
    }
    errors = loader.validate_manifest(bad_manifest)
    assert any("parameter_count" in e and "integer" in e for e in errors)
    assert any("scoring_outputs" in e and "list" in e for e in errors)


def test_load_missing_file(loader: ManifestLoader) -> None:
    """Loading a nonexistent file raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        loader.load(Path("/nonexistent/manifest.json"))


def test_load_invalid_json(loader: ManifestLoader) -> None:
    """Loading invalid JSON raises json.JSONDecodeError."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        f.write("not valid json {{{")
        f.flush()
        with pytest.raises(json.JSONDecodeError):
            loader.load(Path(f.name))
