"""End-to-end regression check: run the 15-dam fixture and compare every
emitted CSV against the committed SHA256 golden hashes.

Marked ``slow`` because it invokes the full pipeline (~5 min on a workstation).
Run with:
    pytest -m slow
    pytest -m "not slow"     # skip this test (default for fast pushes)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from .conftest import sha256


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
