"""Test case manifest management.

Loads, validates, and queries the versioned manifest.json that defines
the test case library (test case IDs, model types, Docker images, and
scoring configurations).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REQUIRED_TEST_CASE_FIELDS = frozenset({"id", "simplified_model_type", "parameter_count", "scoring_outputs"})


class ManifestLoader:
    """Loads and queries the test case manifest."""

    def load(self, manifest_path: Path) -> dict[str, Any]:
        """Load and parse a manifest.json file.

        Args:
            manifest_path: Path to the manifest.json file.

        Returns:
            Parsed manifest dict with version and test_cases keys.

        Raises:
            FileNotFoundError: If manifest_path does not exist.
            json.JSONDecodeError: If the file is not valid JSON.
            ManifestError: If required top-level keys are missing.
        """
        text = manifest_path.read_text(encoding="utf-8")
        manifest = json.loads(text)

        if "version" not in manifest:
            raise ManifestError("Manifest missing required field: version")
        if "test_cases" not in manifest:
            raise ManifestError("Manifest missing required field: test_cases")

        # Duplicate test_case ids would make selection non-deterministic and
        # let one entry shadow another in lookups; refuse to load.
        test_case_ids = [tc["id"] for tc in manifest["test_cases"] if isinstance(tc, dict) and "id" in tc]
        if len(test_case_ids) != len(set(test_case_ids)):
            duplicates = {tid for tid in test_case_ids if test_case_ids.count(tid) > 1}
            raise ManifestError(f"Duplicate test_case IDs in manifest: {sorted(duplicates)}")

        return dict(manifest)

    def get_test_case(self, manifest: dict[str, Any], test_case_id: str) -> dict[str, Any] | None:
        """Look up a test case by ID.

        Args:
            manifest: Parsed manifest dict.
            test_case_id: The test case identifier to find.

        Returns:
            The test case dict if found, None otherwise.
        """
        for tc in manifest.get("test_cases", []):
            if tc.get("id") == test_case_id:
                return dict(tc)
        return None

    def validate_manifest(self, manifest: dict[str, Any]) -> list[str]:
        """Validate manifest structure and return a list of errors.

        Checks for required top-level fields and required fields on each
        test case entry.

        Args:
            manifest: Parsed manifest dict to validate.

        Returns:
            List of validation error strings. Empty list means valid.
        """
        errors: list[str] = []

        if "version" not in manifest:
            errors.append("Missing top-level field: version")
        if "test_cases" not in manifest:
            errors.append("Missing top-level field: test_cases")
            return errors

        if not isinstance(manifest["test_cases"], list):
            errors.append("test_cases must be a list")
            return errors

        for i, tc in enumerate(manifest["test_cases"]):
            if not isinstance(tc, dict):
                errors.append(f"test_cases[{i}] is not a dict")
                continue
            for field_name in REQUIRED_TEST_CASE_FIELDS:
                if field_name not in tc:
                    tc_id = tc.get("id", f"index {i}")
                    errors.append(f"test_cases[{i}] ({tc_id}) missing required field: {field_name}")

            if "parameter_count" in tc and not isinstance(tc["parameter_count"], int):
                tc_id = tc.get("id", f"index {i}")
                errors.append(f"test_cases[{i}] ({tc_id}) parameter_count must be an integer")

            if "scoring_outputs" in tc and not isinstance(tc["scoring_outputs"], list):
                tc_id = tc.get("id", f"index {i}")
                errors.append(f"test_cases[{i}] ({tc_id}) scoring_outputs must be a list")

        return errors


class ManifestError(Exception):
    """Raised when manifest loading or validation fails."""
