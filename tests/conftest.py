"""Shared test fixtures.

Automatically installs test case data files from the repo's registry/
into ~/.zhen/test_cases/ so tests work on CI and fresh machines.
"""

from __future__ import annotations

import shutil
from pathlib import Path

# Install test case files before any tests run
_REGISTRY_DIR = Path(__file__).resolve().parent.parent / "registry" / "test_cases"
_ZHEN_DIR = Path.home() / ".zhen" / "test_cases"


def pytest_configure(config: object) -> None:
    """Copy test case files from registry/ to ~/.zhen/ at session start."""
    if not _REGISTRY_DIR.exists():
        return

    for test_case_dir in _REGISTRY_DIR.iterdir():
        if not test_case_dir.is_dir():
            continue
        dst = _ZHEN_DIR / test_case_dir.name
        dst.mkdir(parents=True, exist_ok=True)
        for f in test_case_dir.iterdir():
            if f.is_file():
                shutil.copy2(f, dst / f.name)
