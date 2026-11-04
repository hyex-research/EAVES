"""Shared pytest fixtures for the EAVES test suite."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = REPO_ROOT / "test" / "fixture"
TEST_SETTINGS = FIXTURE_DIR / "settings.json"
LOCAL_TEST_SETTINGS = FIXTURE_DIR / "settings_local.json"
GOLDEN_HASHES = REPO_ROOT / "test" / "golden_hashes.json"


@pytest.fixture(scope="session")
def test_settings_path() -> Path:
    """The fixture settings, or the untracked ``settings_local.json`` beside them when it exists."""
    return LOCAL_TEST_SETTINGS if LOCAL_TEST_SETTINGS.is_file() else TEST_SETTINGS


@pytest.fixture(scope="session")
def golden_hashes() -> dict:
    return json.loads(GOLDEN_HASHES.read_text())


@pytest.fixture(scope="session")
def fixture_output(test_settings_path: Path) -> Path:
    """Run the 15-dam fixture through the pipeline into ``test/fixture/output/`` once per session.

    The run leaves out ``--panels`` and writes the tables under ``1_results_csv/`` and the
    per-dam flood maps under ``0_check_dams/``. Its CSV files are byte-stable across runs,
    and the regression test hashes only them.
    """
    out = FIXTURE_DIR / "output"
    out.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable, str(REPO_ROOT / "run_eaves.py"),
        "--settings", str(test_settings_path),
    ]
    result = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        pytest.fail(
            f"Pipeline failed (exit {result.returncode}).\n"
            f"stdout tail:\n{result.stdout[-2000:]}\n"
            f"stderr tail:\n{result.stderr[-2000:]}"
        )
    return out


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
