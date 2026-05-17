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
GOLDEN_HASHES = REPO_ROOT / "test" / "golden_hashes.json"


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def test_settings_path() -> Path:
    return TEST_SETTINGS


@pytest.fixture(scope="session")
def golden_hashes() -> dict:
    return json.loads(GOLDEN_HASHES.read_text())


@pytest.fixture(scope="session")
def fixture_output() -> Path:
    """Run the test-fixture pipeline into ``test/fixture/output/``.

    Session-scoped so the ~5 min run happens once per pytest invocation.
    The output tree is committed as publication reference; CSV content is
    byte-stable across runs, so re-runs leave the CSVs unchanged.
    PNG timestamps may diff after a run — that is expected.

    ``--panels`` is intentionally NOT passed: most publication panels need
    production-only inputs (bathymetry CSV, country shapefile, GRDL data,
    validation outputs) that the 15-dam fixture does not ship. The pipeline
    only writes per-dam flood maps under ``0_check_dams/``; nothing lands
    in ``2_results_plots/`` for the fixture run.
    """
    out = FIXTURE_DIR / "output"
    out.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable, str(REPO_ROOT / "run_eaves.py"),
        "--settings", str(TEST_SETTINGS),
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
