"""Paths, processing constants, caches, and matplotlib rcParams."""

from __future__ import annotations

import os
import warnings

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib as _mpl  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402, F401
import rasterio  # noqa: E402

warnings.filterwarnings("ignore", category=rasterio.errors.NotGeoreferencedWarning)
warnings.filterwarnings("ignore", category=RuntimeWarning)

# ---------------------------------------------------------------------------
# Nature Water figure style (Arial/Helvetica, 5-7 pt, 300 DPI)
# ---------------------------------------------------------------------------
_BASE_FS = 7
_mpl.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans", "sans-serif"],
    "font.size": _BASE_FS,
    "axes.titlesize": _BASE_FS,
    "axes.labelsize": _BASE_FS,
    "xtick.labelsize": 6,
    "ytick.labelsize": 6,
    "legend.fontsize": 6,
    "axes.linewidth": 0.6,
    "figure.dpi": 300,
})

# Nature column widths in inches
FIG_SINGLE_COL = 3.5   # 89 mm
FIG_DOUBLE_COL = 7.2    # 183 mm
FIG_MAX_HEIGHT = 6.7    # 170 mm

# Colorblind-safe palette (Nature recommended)
NATURE_COLORS = {
    "black":    "#000000",
    "orange":   "#E69F00",
    "sky_blue": "#56B4E9",
    "green":    "#009E73",
    "yellow":   "#F0E442",
    "blue":     "#0072B2",
    "vermillion": "#D55E00",
    "purple":   "#CC79A7",
}

# Quality grade colours (colorblind-safe)
GRADE_COLORS = {
    "A": NATURE_COLORS["green"],
    "B": NATURE_COLORS["blue"],
    "C": NATURE_COLORS["orange"],
    "D": NATURE_COLORS["vermillion"],
    "F": NATURE_COLORS["black"],
}

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
A01_DIR = "/home/ivanovn/ws_local/temp/RUSH/ksa/mswep/A01_domain_input"
SRTM_DIR = "/mnt/datawaha/hyex/ivanovn/download/SRTM/1_unzipped"

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

INPUT_DIR = os.path.join(REPO_DIR, "input")
GRDL_DIR = os.path.join(INPUT_DIR, "GRDL")
BAYSH_EAV_CSV = (
    "/home/ivanovn/ws_local/projects/KSA_Field_Data/data/catchments/baysh"
    "/4_bathimetry/post_processing/output/baysh_area_elev_vol.csv"
)
TRANSLIT_CSV = (
    "/home/ivanovn/ws_local/projects/KSA_flash_flood_model_experiment"
    "/assets/ksa_dams_kml/ksa_dams_transliterated.csv"
)

OUTPUT_DIR = os.path.join(REPO_DIR, "output")
FLOOD_DIR = os.path.join(OUTPUT_DIR, "0_check_dam_flood")
CSV_DIR = os.path.join(OUTPUT_DIR, "1_results_csv")
EAV_DIR = os.path.join(CSV_DIR, "eav_tables")
PLOT_DIR = os.path.join(OUTPUT_DIR, "2_results_plots")

PLACEMENT_OVERRIDES_CSV = os.path.join(INPUT_DIR, "dam_placement_overrides.csv")
A03_FILTERED_DIR = os.path.join(
    os.path.dirname(A01_DIR), "A03_dam_input", "filtered_timeseries"
)

# ---------------------------------------------------------------------------
# Processing parameters
# ---------------------------------------------------------------------------
BIN_Z = 0.5
VOID_THRESHOLD = 0.05
WALL_BUFFER_PX = 5
WALL_THICKNESS = 3
FLAT_STD_THRESH = 1.0
FLAT_MIN_PIXELS = 50

UPSTREAM_STEP_PX = 5.0
UPSTREAM_MAX_SHIFT_PX = 100.0
UPSTREAM_WALK_STEP_M = 100.0
EXTENSION_STEP_M = 25.0
EXT_SEARCH_MAX_SAMPLES = 15

MAX_CREST_FLOW_DOT = 0.74
TERRAIN_WALL_TOP_K = 18
ALIGN_WEIGHT = 2.35

_PLACEMENT_BUDGET_S = 300.0

GRDL_NAME_MAP = {
    "baish": "id_120000",
    "hali": "id_020019",
    "rabigh": "id_020018",
}

# ---------------------------------------------------------------------------
# Module-level caches (shared across workers via import)
# ---------------------------------------------------------------------------
_srtm_cache: dict = {}
_placement_overrides_cache = None
