"""Module-level configuration shared by every pipeline stage.

Processing constants (elevation interval, placement tolerances, acceptance gates),
the module-level tile cache shared across workers, and the path attributes
populated from the settings JSON by :func:`configure` (see
:mod:`eaves.settings`).
"""

from __future__ import annotations

import os
import sys
import warnings

import matplotlib as _mpl
import rasterio

_mpl.use("Agg")

warnings.filterwarnings("ignore", category=rasterio.errors.NotGeoreferencedWarning)
warnings.filterwarnings("ignore", category=RuntimeWarning)

# ---- Paths, populated by configure() from the settings JSON (see eaves.settings) ----

COUNTRY_NAME_COL = "NAME"

# ---- Processing parameters ----
BIN_Z = 0.5
B_LOWER_BOUND = 1.0  # Lower bound of the released exponent of V = c * A^b, no upper bound applies
LEVEL_MERGE_M = 0.01  # A regular level this close below the spillway or the capped level gives way to it
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

# Stage-2/5 early-exit tolerance on the volume error |log(approx_vol / capacity_m3)|
PLACEMENT_GOOD_ENOUGH_VOL_ERR = 0.26
# Loose fallback tolerance when no early-exit candidate wins the upstream walk
PLACEMENT_UPSTREAM_MAX_VOL_ERR = 1.5
# Minimum footprint pixels for a stage-6 multi-direction fallback fill
FALLBACK_MIN_PIXELS = 10

# Share of the capacity-level pool that must drain out next to the wall for a fill to count as the reservoir
DRAIN_MIN_SHARE = 0.5
# Distance past the half wall (m) within which the outlet of a pool counts as next to the wall
DRAIN_WALL_TOLERANCE_M = 1000.0
# Largest position of the outlets along the capacity-level pool, 0 at the dam cell and 1 at its farthest cell
DRAIN_MAX_OUTLET_POSITION = 0.65
# Capacity-level pools smaller than this many pixels are too small to judge and pass
DRAIN_MIN_PIXELS = 30
# Share of a pool that must lie down the river reach from the dam cell for the pool to count as downstream of the wall
DOWNSTREAM_POOL_RIVER_SHARE = 0.9
# Share of the same pool that must also lie down the terrain slope from the dam cell
DOWNSTREAM_POOL_SLOPE_SHARE = 0.5
# Distance past the dam cell (pixels) beyond which a pool cell counts as downstream
DOWNSTREAM_POOL_BUFFER_PX = 4.0

_PLACEMENT_BUDGET_S = 300.0

# Significant digits kept by a floating-point value in the released tables
RELEASE_SIGNIFICANT_DIGITS = 4
# Decimals a floating-point value in the released tables always keeps, large values such as elevations included
RELEASE_MIN_DECIMALS = 2
# Columns that keep a fixed number of decimals, where the entry of b also covers the columns named after the exponent, such as b_reg and ref_b
RELEASE_DECIMALS = {"capacity_mcm": 4, "b": 4}
# Coordinates and dam dimensions, written as they come from the catalog
RELEASE_VERBATIM = ("lat", "lon", "latitude", "longitude", "dam_height_m", "spillway_height_m", "dam_length_m")

# Longest reach part and largest snap distance (m) of the preprocessing, which clips the MERIT-Basins reaches, subdivides the longer reaches into equal parts and snaps the dams
MAX_SEG_LEN_M = 2000.0
MAX_SNAP_DISTANCE_M = 1000.0
# Buffer (degrees) applied around each dam when clipping the MERIT-Basins network
DAM_BBOX_BUFFER_DEG = 0.3

GRDL_NAME_MAP = {
    "baish": "id_120000",
    "hali": "id_020019",
    "rabigh": "id_020018",
}

# ---- Module-level cache (shared across workers via import) ----
_srtm_cache: dict = {}


# ---- Runtime reconfiguration (programmatic / CLI overrides) ----
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
    bathymetry_survey_date: str | None = None,
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
    _self = sys.modules[__name__]

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
    if bathymetry_survey_date is not None:
        _self.BATHYMETRY_SURVEY_DATE = bathymetry_survey_date
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
