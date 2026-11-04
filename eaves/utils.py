"""Shared helpers.

Coordinate and tile helpers (UTM EPSG selection, buffer sizing), the
canonical power-law fit, the precision of the released tables and the typed
reading of their cells, and the selection of the summary rows with a flood
fill.
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import curve_fit

import eaves.config as _cfg

# ---- Coordinate / tile helpers ----

def utm_epsg_from_lon(lon):
    zone = int((lon + 180) / 6) + 1
    return 32600 + zone


def srtm_tile_name(lat, lon):
    ns = "N" if lat >= 0 else "S"
    ew = "E" if lon >= 0 else "W"
    return f"{ns}{abs(int(np.floor(lat))):02d}{ew}{abs(int(np.floor(lon))):03d}.hgt"


# ---- Power-law fit ----

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


# ---- Released precision ----

def _released_decimals(column):
    if column in _cfg.RELEASE_DECIMALS:
        return _cfg.RELEASE_DECIMALS[column]
    if "b" in str(column).split("_"):
        return _cfg.RELEASE_DECIMALS["b"]
    return None


def round_released_value(column, value):
    """Round one value of ``column`` to the precision of the released tables.

    A floating-point value keeps ``RELEASE_SIGNIFICANT_DIGITS`` significant
    digits and never fewer than ``RELEASE_MIN_DECIMALS`` decimals. The columns
    of ``RELEASE_DECIMALS`` keep a fixed number of decimals. The columns of
    ``RELEASE_VERBATIM`` and every value that is not a float pass unchanged.
    """
    if column in _cfg.RELEASE_VERBATIM or not isinstance(value, (float, np.floating)) or not np.isfinite(value):
        return value
    value = float(value)
    decimals = _released_decimals(column)
    if decimals is None:
        digits = _cfg.RELEASE_SIGNIFICANT_DIGITS
        exponent = int(f"{value:.{digits - 1}e}".split("e")[1])
        decimals = max(_cfg.RELEASE_MIN_DECIMALS, digits - 1 - exponent)
    return round(value, decimals)


def round_released_columns(df):
    """Round the floating-point columns of ``df`` in place to the precision of the released tables."""
    for column in df.columns:
        if df[column].dtype.kind == "f":
            df[column] = df[column].map(lambda value, column=column: round_released_value(column, value))
    return df


def typed_value(text):
    """Return a cell of a released table read as text, as a bool, an int or a float where it reads as one, None where it is empty or not finite, else the text itself."""
    if text is None or text == "":
        return None
    if text in ("True", "False"):
        return text == "True"
    try:
        return int(text)
    except ValueError:
        pass
    try:
        value = float(text)
    except ValueError:
        return text
    return value if np.isfinite(value) else None


# ---- Summary rows ----

_FILL_DTYPES = {"n_pixels": "int64", "uncertainty_score": "int64", "capped": "bool"}


def dams_with_fill(df):
    """Return the rows of a summary table whose dam has a flood fill.

    ``eaves_summary.csv`` holds every dam of ``eaves_params.csv``. A dam
    without a flood fill leaves the cells of its fill and of its fit empty,
    and such a row has no ``n_pixels``. The count and flag columns of the
    remaining rows return to their integer and boolean types, so the result
    reads as a table of fills alone.
    """
    if "n_pixels" not in df.columns:
        return df
    out = df[df["n_pixels"].notna()].reset_index(drop=True)
    return out.astype({column: dtype for column, dtype in _FILL_DTYPES.items() if column in out.columns})


# ---- Misc helpers ----

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
