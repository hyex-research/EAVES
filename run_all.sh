#!/usr/bin/env bash

# End-to-end EAVES run: full pipeline + validation + uncertainty propagation + panels (p1-p6 main + s1-s5 supplementary, each in PNG and PDF) + report

# Usage: ./run_all.sh [settings.json], called from the project root. The settings default to region/ksa/ksa.json

# Steps (in order):
#   1. python -m eaves --settings <X>: placement, flood-fill, power-law fit, regionalization
#   2. python -m eaves.postprocess.validation --settings <X>: LOO regionalization validation, DEM-vs-satellite area check, goodness of fit and A_cap regression diagnostics
#   3. python -m eaves.postprocess.uncertainty --settings <X>: per-dam V uncertainty propagation from b_sigma at half, quarter and tenth pool (writes validation/v_uncertainty.csv)
#   4. python -m eaves.postprocess.panels --settings <X>: renders the p1-p6 main panels and the s1 (b-clustering), s2 (uncertainty band), s3 (DEM error), s4 (threshold) and s5 (sensitivity) supplementary panels, s3 and s5 from the tables of the optional validation runs when they exist. s1 also computes the b-clustering diagnostic CSV
#   5. python -m eaves.postprocess.report --settings <X>: domain characterization CSV + Markdown report (embeds the panels)

# RUN_TESTS=1 also runs the regression test on the 15-dam fixture afterwards and stops at a failure. The golden hashes change only through the one-liner of test/README.md

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
echo "[run_all] (4/5) Panels (p1-p6 + supplementary s1-s5) --------------"
python -m eaves.postprocess.panels --settings "$SETTINGS"

echo
echo "[run_all] (5/5) Report --------------------------------------------"
# Pins --ref-year to 2026, the reference year of the sediment budget
python -m eaves.postprocess.report --settings "$SETTINGS" --ref-year 2026

if [[ "${RUN_TESTS:-0}" == "1" ]]; then
    echo
    echo "[run_all] (+) Regression test on the 15-dam fixture ------------"
    python -m pytest test/test_regression.py -m slow
fi

echo
echo "===================================================================="
echo "[run_all] DONE.  $(date)"
echo "===================================================================="
