"""Math helpers, override loaders, SRTM / UTM utilities."""

from __future__ import annotations

import os

import numpy as np
import pandas as pd
from scipy.optimize import curve_fit

from .config import (
    UPSTREAM_STEP_PX,
    UPSTREAM_MAX_SHIFT_PX,
)
import eaves.config as _cfg


# ---------------------------------------------------------------------------
# Placement-override loaders
# ---------------------------------------------------------------------------

def _load_placement_overrides():
    """Load ``dam_placement_overrides.csv`` once; keyed by dam_id.

    Path is read from ``_cfg.PLACEMENT_OVERRIDES_CSV`` if set (see settings);
    silently skipped otherwise.
    """
    if _cfg._placement_overrides_cache is not None:
        return _cfg._placement_overrides_cache
    _cfg._placement_overrides_cache = {}
    overrides_csv = getattr(_cfg, "PLACEMENT_OVERRIDES_CSV", None)
    if not overrides_csv or not os.path.isfile(overrides_csv):
        return _cfg._placement_overrides_cache
    try:
        df = pd.read_csv(overrides_csv, comment="#")
    except Exception:
        return _cfg._placement_overrides_cache
    df.columns = [str(c).strip() for c in df.columns]
    id_col = "dam_id" if "dam_id" in df.columns else "csv_id"
    if id_col not in df.columns:
        return _cfg._placement_overrides_cache
    for _, row in df.iterrows():
        cid = str(row[id_col]).strip()
        if not cid or cid.lower() in ("nan", "none"):
            continue
        _cfg._placement_overrides_cache[cid] = row.to_dict()
    return _cfg._placement_overrides_cache


def _get_placement_override(dam_id):
    return _load_placement_overrides().get(str(dam_id).strip(), {})


def _ov_float(ov, key, default=None):
    if not ov or key not in ov:
        return default
    v = ov[key]
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return default
    try:
        x = float(v)
        return x
    except (TypeError, ValueError):
        return default


def _ov_bool(ov, key, default=False):
    if not ov or key not in ov:
        return default
    v = ov[key]
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return default
    if isinstance(v, (bool, np.bool_)):
        return bool(v)
    try:
        fv = float(v)
        if fv == 1.0:
            return True
        if fv == 0.0:
            return False
    except (TypeError, ValueError):
        pass
    s = str(v).strip().lower()
    return s in ("1", "true", "yes", "y")


def _ov_int(ov, key, default=None):
    if not ov or key not in ov:
        return default
    v = ov[key]
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return default
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return default


def _ov_preferred_crest_angles_deg(ov):
    """Comma/semicolon-separated integers in [0, 180), tried first for wall orientation."""
    if not ov:
        return []
    v = ov.get("preferred_crest_angle_deg")
    if v is None:
        return []
    s = str(v).strip()
    if not s or s.lower() == "nan":
        return []
    out = []
    for part in s.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            a = int(round(float(part))) % 180
            out.append(a)
        except (TypeError, ValueError):
            continue
    return out


# ---------------------------------------------------------------------------
# Upstream walk distances
# ---------------------------------------------------------------------------

def _upstream_sample_distances_m(pixel_size_m, max_shift_px=None):
    """Distances (m) along the valley walk at which we try a wall."""
    if pixel_size_m <= 0 or not np.isfinite(pixel_size_m):
        return np.array([0.0], dtype=float)
    mx_px = float(UPSTREAM_MAX_SHIFT_PX if max_shift_px is None else max_shift_px)
    max_m = mx_px * pixel_size_m
    step_m = float(UPSTREAM_STEP_PX) * pixel_size_m
    arr = np.arange(0.0, max_m + 1e-9, step_m)
    out = list(arr)
    if len(out) == 0:
        return np.array([0.0], dtype=float)
    if abs(out[-1] - max_m) > 0.5 * pixel_size_m:
        out.append(max_m)
    return np.array(out, dtype=float)


# ---------------------------------------------------------------------------
# Coordinate / tile helpers
# ---------------------------------------------------------------------------

def utm_epsg_from_lon(lon):
    zone = int((lon + 180) / 6) + 1
    return 32600 + zone


def srtm_tile_name(lat, lon):
    ns = "N" if lat >= 0 else "S"
    ew = "E" if lon >= 0 else "W"
    return f"{ns}{abs(int(np.floor(lat))):02d}{ew}{abs(int(np.floor(lon))):03d}.hgt"


# ---------------------------------------------------------------------------
# Power-law fit
# ---------------------------------------------------------------------------

def power_law_2p(area, c, b):
    return c * np.power(area, b)


def fit_power_law(area_m2, vol_m3):
    mask = (area_m2 > 0) & (vol_m3 > 0)
    if mask.sum() < 3:
        return np.nan, np.nan, np.nan
    a = area_m2[mask]
    v = vol_m3[mask]
    try:
        popt, _ = curve_fit(power_law_2p, a, v, p0=[0.1, 1.3], maxfev=20000)
        c, b = popt
        v_pred = power_law_2p(a, c, b)
        ss_res = np.sum((v - v_pred) ** 2)
        ss_tot = np.sum((v - np.mean(v)) ** 2)
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
        return c, b, r2
    except Exception:
        return np.nan, np.nan, np.nan


# ---------------------------------------------------------------------------
# Misc helpers
# ---------------------------------------------------------------------------

def interpolate_nans(data):
    from scipy.ndimage import distance_transform_edt
    mask = np.isnan(data)
    if not mask.any():
        return data
    _, idx = distance_transform_edt(mask, return_indices=True)
    out = data.copy()
    out[mask] = data[tuple(idx[:, mask])]
    return out


def buffer_deg_for_dam(capacity_m3):
    capacity_mcm = capacity_m3 / 1e6
    if capacity_mcm > 100:
        return 0.12
    elif capacity_mcm > 30:
        return 0.08
    elif capacity_mcm > 5:
        return 0.05
    else:
        return 0.03


def _approx_cone_volume_m3(n_px, pixel_area, spillway_height_m):
    """Crude prismatoid volume for comparing fills without full EAV integration."""
    return float(n_px) * float(pixel_area) * float(spillway_height_m) / 3.0


def _bresenham(r0, c0, r1, c1):
    dr = abs(r1 - r0)
    dc = abs(c1 - c0)
    sr = 1 if r0 < r1 else -1
    sc = 1 if c0 < c1 else -1
    err = dr - dc
    while True:
        yield (r0, c0)
        if r0 == r1 and c0 == c1:
            break
        e2 = 2 * err
        if e2 > -dc:
            err -= dc
            r0 += sr
        if e2 < dr:
            err += dr
            c0 += sc


def _classify_failure(reason):
    if "bad_fill_auto" in reason:
        return "bad_fill_auto"
    if "srtm_voids" in reason:
        return "srtm_voids"
    if "placement_failed" in reason:
        return "placement_failed"
    if "leak" in reason.lower():
        return "flood_fill_leak"
    if "seed" in reason.lower() or "fill" in reason.lower():
        return "flood_fill_failed"
    if "NaN" in reason or "nan" in reason.lower():
        return "insufficient_pixels"
    if "no srtm" in reason.lower() or "tiles" in reason.lower():
        return "no_srtm_tiles"
    if "missing" in reason.lower():
        return "missing_attributes"
    return "processing_error"
