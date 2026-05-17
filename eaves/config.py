"""Paths, processing constants, caches, and matplotlib rcParams."""

from __future__ import annotations

import os
import warnings

import matplotlib
matplotlib.use("Agg")
import matplotlib as _mpl
import matplotlib.pyplot
import rasterio

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

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
# All path attributes (SRTM_DIR, DAMS_CSV, OUTPUT_DIR, FLOOD_DIR, etc.) are
# populated by :func:`configure` from the settings JSON — see
# :mod:`eaves.settings`. Consumers should either have settings loaded before
# reading them, or use ``getattr(_cfg, "X", None)`` for optional ones.

COUNTRY_NAME_COL = "NAME"

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

# Acceptance tolerances for per-dam terrain-based placement (stage 2/5):
#   volume error := |log(approx_vol / catalogue_capacity)|
# GOOD_ENOUGH lets the upstream-walk loop early-exit once a candidate is close
# enough; UPSTREAM_MAX_VOL_ERR is the loose fallback when no early-exit winner
# was found. FALLBACK_MIN_PIXELS is the minimum footprint size (in SRTM pixels)
# for a candidate fill to be considered in the stage-6 multi-direction fallback.
PLACEMENT_GOOD_ENOUGH_VOL_ERR = 0.26
PLACEMENT_UPSTREAM_MAX_VOL_ERR = 1.5
FALLBACK_MIN_PIXELS = 10

_PLACEMENT_BUDGET_S = 300.0

# Preprocessing (MERIT clip + segment split + dam snap).
MAX_SEG_LEN_M = 2000.0
MAX_SNAP_DISTANCE_M = 1000.0
# Buffer (degrees) applied around each dam when clipping the MERIT network.
DAM_BBOX_BUFFER_DEG = 0.3

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


# ---------------------------------------------------------------------------
# Runtime reconfiguration (for programmatic / CLI overrides)
# ---------------------------------------------------------------------------
def configure(
    *,
    output_dir: str | None = None,
    srtm_dir: str | None = None,
    dams_csv: str | None = None,
    water_extent_dir: str | None = None,
    domain_dir: str | None = None,
    merit_rivers_shp: str | None = None,
    merit_basins_shp: str | None = None,
    country_shp: str | None = None,
    target_country: str | None = None,
    country_name_col: str | None = None,
    bathymetry_eav_csv: str | None = None,
    bathymetry_dam_id: str | None = None,
    grdl_dir: str | None = None,
    sedimentation_dir: str | None = None,
    max_seg_len_m: float | None = None,
    max_snap_distance_m: float | None = None,
) -> None:
    """Override path variables after import.

    All modules that use configurable paths must reference them via
    ``eaves.config.X`` (i.e. ``_cfg.X``) rather than locally-bound names
    so that changes made here are visible everywhere.
    """
    import eaves.config as _self

    if srtm_dir is not None:
        _self.SRTM_DIR = srtm_dir
    if dams_csv is not None:
        _self.DAMS_CSV = dams_csv
    if water_extent_dir is not None:
        _self.WATER_EXTENT_DIR = water_extent_dir
    if domain_dir is not None:
        _self.DOMAIN_DIR = domain_dir
    if merit_rivers_shp is not None:
        _self.MERIT_RIVERS_SHP = merit_rivers_shp
    if merit_basins_shp is not None:
        _self.MERIT_BASINS_SHP = merit_basins_shp
    if country_shp is not None:
        _self.COUNTRY_SHP = country_shp
    if target_country is not None:
        _self.TARGET_COUNTRY = target_country
    if country_name_col is not None:
        _self.COUNTRY_NAME_COL = country_name_col
    if bathymetry_eav_csv is not None:
        _self.BATHYMETRY_EAV_CSV = bathymetry_eav_csv
    if bathymetry_dam_id is not None:
        _self.BATHYMETRY_DAM_ID = bathymetry_dam_id
    if grdl_dir is not None:
        _self.GRDL_DIR = grdl_dir
    if sedimentation_dir is not None:
        _self.SEDIMENTATION_DIR = sedimentation_dir
    if max_seg_len_m is not None:
        _self.MAX_SEG_LEN_M = float(max_seg_len_m)
    if max_snap_distance_m is not None:
        _self.MAX_SNAP_DISTANCE_M = float(max_snap_distance_m)

    if output_dir is not None:
        _self.OUTPUT_DIR = output_dir
        _self.FLOOD_DIR = os.path.join(output_dir, "0_check_dams")
        _self.CSV_DIR = os.path.join(output_dir, "1_results_csv")
        _self.EAV_DIR = os.path.join(_self.CSV_DIR, "eav_tables")
        _self.PLOT_DIR = os.path.join(output_dir, "2_results_plots")
