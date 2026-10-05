"""End-to-end regression check that runs the 15-dam fixture and compares every
emitted CSV against the committed SHA256 golden hashes. A second test reads the
summary of the same run and checks that it holds every dam of the parameter
table, and a third reruns a copy of the tables through ``--plot-only`` and
through a single-dam ``--only`` and checks that they come out unchanged.

Marked ``slow`` because it invokes the full pipeline (about 80 s on a 112-core
workstation).
Run with:
    pytest -m slow
    pytest -m "not slow"     # skip this test (default for fast pushes)
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

from .conftest import REPO_ROOT, sha256


@pytest.mark.slow
def test_fixture_outputs_match_golden(fixture_output: Path, golden_hashes: dict):
    mismatches = []
    missing = []
    for rel, expected in golden_hashes.items():
        f = fixture_output / rel
        if not f.is_file():
            missing.append(rel)
            continue
        actual = sha256(f)
        if actual != expected:
            mismatches.append(f"  {rel}\n    expected: {expected}\n    actual:   {actual}")

    if missing or mismatches:
        msg = []
        if missing:
            msg.append(f"Missing files ({len(missing)}):\n  " + "\n  ".join(missing))
        if mismatches:
            msg.append(f"Hash mismatches ({len(mismatches)}):\n" + "\n".join(mismatches))
        msg.append(
            "\nIf the change was intentional, regenerate the goldens with:\n"
            "  pytest -m slow  # rebuilds test/fixture/output/\n"
            "  python -c 'import hashlib,json; from pathlib import Path; "
            "out=Path(\"test/fixture/output/1_results_csv\"); "
            "h={str(p.relative_to(\"test/fixture/output\")): hashlib.sha256(p.read_bytes()).hexdigest() "
            "for p in sorted(out.rglob(\"*.csv\"))}; "
            "open(\"test/golden_hashes.json\",\"w\").write(json.dumps(h,indent=2,sort_keys=True))'"
        )
        pytest.fail("\n\n".join(msg))


@pytest.mark.slow
def test_summary_holds_every_dam_of_the_parameter_table(fixture_output: Path):
    """``eaves_summary.csv`` lists the dams of ``eaves_params.csv``, and a dam without a flood fill keeps its attributes beside empty fill and fit cells."""
    csv_dir = fixture_output / "1_results_csv"
    summary = pd.read_csv(csv_dir / "eaves_summary.csv")
    params = pd.read_csv(csv_dir / "eaves_params.csv")
    failed = pd.read_csv(csv_dir / "failed_dams.csv")
    assert list(summary["dam_id"]) == list(params["dam_id"])

    unfilled = summary[summary["n_pixels"].isna()]
    assert len(unfilled) > 0
    assert set(unfilled["dam_id"]) <= set(failed["dam_id"])
    assert unfilled[["placement_method", "quality", "c", "b", "footprint_area_km2", "uncertainty_flags"]].isna().all().all()
    assert unfilled[["capacity_mcm", "upstream_area_km2", "valley_width_m", "lat", "lon", "sed_yield_t_ha_yr"]].notna().all().all()


@pytest.mark.slow
@pytest.mark.parametrize(
    "flags",
    [["--plot-only"], ["--only", "id_010007"], ["--only", "id_020002"]],
    ids=["plot-only", "only-dam-without-fill", "only-dam-with-fill"],
)
def test_partial_runs_reproduce_the_tables(fixture_output: Path, test_settings_path: Path, tmp_path: Path, flags):
    """``--plot-only`` and a single-dam ``--only`` run leave the tables of the full run unchanged."""
    shutil.copytree(fixture_output / "1_results_csv", tmp_path / "1_results_csv")
    cmd = [
        sys.executable, str(REPO_ROOT / "run_eaves.py"),
        "--settings", str(test_settings_path),
        "--output-dir", str(tmp_path), *flags,
    ]
    result = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr[-2000:]
    for name in ("eaves_summary.csv", "eaves_params.csv", "failed_dams.csv", "threshold_analysis.csv"):
        rerun = (tmp_path / "1_results_csv" / name).read_bytes()
        assert rerun == (fixture_output / "1_results_csv" / name).read_bytes(), name
