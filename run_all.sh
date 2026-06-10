#!/usr/bin/env bash
#
# End-to-end EAVES run: full pipeline + validation + uncertainty
# propagation + panels (p1-p5 main + s1/s2/s3 supplementary, each in PNG
# and PDF) + report.
#
# Usage:
#   ./run_all.sh [settings.json]
#
# Defaults to region/ksa/ksa.json. Run from the project root.
#
# Steps (in order):
#   1. python -m eaves --settings <X>
#        Placement, flood-fill, power-law fit, regionalization.
#   2. python -m eaves.postprocess.validation --settings <X>
#        LOO regionalization validation + DEM-vs-satellite area diagnostics.
#   3. python -m eaves.postprocess.uncertainty --settings <X>
#        Per-dam V uncertainty propagation from b_sigma at half/quarter/
#        tenth pool (writes validation/v_uncertainty.csv).
#   4. python -m eaves.postprocess.panels --settings <X>
#        Render p1-p5 main panels and s1 (b-clustering) + s2 (threshold)
#        + s3 (uncertainty band) supplementary panels. s1 also computes
#        the b-clustering diagnostic CSV on first invocation.
#   5. python -m eaves.postprocess.report --settings <X>
#        Domain characterization CSV + Markdown report (embeds the panels).
#
# Set RUN_TESTS=1 to also rebuild the 15-dam fixture and refresh
# test/golden_hashes.json afterwards.

set -euo pipefail

SETTINGS="${1:-region/ksa/ksa.json}"

if [[ ! -f "$SETTINGS" ]]; then
    echo "[run_all] settings file not found: $SETTINGS" >&2
    exit 1
fi

echo "===================================================================="
echo "[run_all] Settings: $SETTINGS"
echo "[run_all] Started:  $(date)"
echo "===================================================================="

echo
echo "[run_all] (1/5) Full pipeline -------------------------------------"
python -m eaves --settings "$SETTINGS"

echo
echo "[run_all] (2/5) Validation ----------------------------------------"
python -m eaves.postprocess.validation --settings "$SETTINGS"

echo
echo "[run_all] (3/5) Uncertainty propagation ---------------------------"
python -m eaves.postprocess.uncertainty --settings "$SETTINGS"

echo
echo "[run_all] (4/5) Panels (p1-p5 + supplementary s1, s2, s3) ---------"
python -m eaves.postprocess.panels --settings "$SETTINGS"

echo
echo "[run_all] (5/5) Report --------------------------------------------"
# --ref-year pinned so the sediment budget is reproducible (paper states 2026).
python -m eaves.postprocess.report --settings "$SETTINGS" --ref-year 2026

if [[ "${RUN_TESTS:-0}" == "1" ]]; then
    echo
    echo "[run_all] (+) Rebuilding 15-dam fixture and goldens -------------"
    python -m pytest test/test_regression.py -m slow || true
    python -c "
import hashlib, json
from pathlib import Path
out = Path('test/fixture/output')
h = {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest()
     for p in sorted((out / '1_results_csv').rglob('*.csv'))}
Path('test/golden_hashes.json').write_text(json.dumps(h, indent=2, sort_keys=True))
print(f'wrote test/golden_hashes.json with {len(h)} entries')
"
fi

echo
echo "===================================================================="
echo "[run_all] DONE.  $(date)"
echo "===================================================================="
