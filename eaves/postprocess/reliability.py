"""Physical reliability predicates for EAVES curves.

Each flag marks a geometry regime where SRTM can't reliably resolve
the reservoir (grid resolution, vertical noise, or topographic edge cases).
Flags are additive — a dam can be tagged by several at once.

Thresholds are calibrated to SRTM 1 arc-sec (~30 m grid, LE90 ~6 m vertical
accuracy, i.e. sigma ~3.6 m, ~10 m horizontal LE90).
"""

from __future__ import annotations

import numpy as np
import pandas as pd


_PIXEL_SIZE_M_DEFAULT = 30.0

_FLAGS = [
    "sub_pixel",       # footprint too small vs. pixel grid
    "narrow_valley",   # cross-section undersampled
    "height_noise",    # spillway depth comparable to SRTM vertical noise
    "flat_terrain",    # low catchment slope AND shallow depression
    "tall_narrow",     # high spillway_height / valley_width ratio
    "pre_srtm",        # built before the Feb 2000 SRTM acquisition
    "unknown_year",    # no catalog construction year: pre/post-2000 unverifiable
]

# SRTM C-band acquisition: February 2000.
SRTM_ACQUISITION_YEAR = 2000


def post_srtm_construction(df: pd.DataFrame) -> pd.Series:
    """True where construction is known to postdate the SRTM acquisition.

    Pre-2000 dams may sit on an already partially silted valley floor, and
    unknown-year dams cannot be verified either way, so regionalization
    training keeps only dams with construction_year >= 2000.
    """
    cy = pd.to_numeric(df.get("construction_year"), errors="coerce")
    return pd.Series(cy >= SRTM_ACQUISITION_YEAR, index=df.index).fillna(False)


def trusted_mask(df: pd.DataFrame) -> pd.Series:
    """The trusted-set gates: grade A/B, R^2 >= 0.98, volume ratio in
    [0.3, 5.0], at least 50 footprint pixels, and a defined exponent."""
    return (
        df["quality"].isin(["A", "B"])
        & (df["r_squared"] >= 0.98)
        & df["vol_ratio"].between(0.3, 5.0)
        & (df["n_pixels"] >= 50)
        & df["b"].notna()
    )


_MIN_TRAINING_N = 15


def training_mask(df: pd.DataFrame, min_n: int = _MIN_TRAINING_N) -> pd.Series:
    """Trusted gates AND post-SRTM construction.

    Falls back to the full trusted set when fewer than ``min_n`` dams
    remain (small regions and CI fixtures), where a handful of clean
    trainers is worse than a slightly contaminated population.
    """
    t = trusted_mask(df)
    tr = t & post_srtm_construction(df)
    return tr if int(tr.sum()) >= min_n else t


def add_uncertainty_flags(
    summary_df: pd.DataFrame,
    pixel_size_m: float = _PIXEL_SIZE_M_DEFAULT,
) -> pd.DataFrame:
    """Append ``uncertainty_flags`` and ``uncertainty_score`` columns.

    ``uncertainty_flags`` is a ``;``-joined list of active flag names (empty
    string when none apply). ``uncertainty_score`` is the number of active
    flags (0..7).
    """
    if len(summary_df) == 0:
        summary_df["uncertainty_flags"] = "-"
        summary_df["uncertainty_score"] = 0
        return summary_df

    n_pixels = summary_df.get("n_pixels")
    valley_width = summary_df.get("valley_width_m")
    spillway = summary_df.get("spillway_height_m")
    mean_slope = summary_df.get("mean_catchment_slope")
    z_range = summary_df.get("z_range")

    active = {}
    active["sub_pixel"] = (n_pixels < 30) if n_pixels is not None else pd.Series(False, index=summary_df.index)
    active["narrow_valley"] = (valley_width < 3.0 * pixel_size_m) if valley_width is not None else pd.Series(False, index=summary_df.index)
    active["height_noise"] = (spillway < 5.0) if spillway is not None else pd.Series(False, index=summary_df.index)
    if mean_slope is not None and z_range is not None:
        active["flat_terrain"] = (mean_slope < 0.005) & (z_range < 3.0)
    else:
        active["flat_terrain"] = pd.Series(False, index=summary_df.index)
    if spillway is not None and valley_width is not None:
        with np.errstate(divide="ignore", invalid="ignore"):
            aspect = spillway / valley_width.replace(0, np.nan)
        active["tall_narrow"] = aspect > 0.2
    else:
        active["tall_narrow"] = pd.Series(False, index=summary_df.index)
    # pre_srtm marks definite pre-2000 construction: the curve describes the
    # as-of-2000 valley (possibly already silted), not pristine design geometry.
    cy = pd.to_numeric(summary_df.get("construction_year"), errors="coerce")
    active["pre_srtm"] = pd.Series(cy < SRTM_ACQUISITION_YEAR, index=summary_df.index)
    # unknown_year marks dams whose pre/post-acquisition status cannot be
    # verified; like pre_srtm dams they are excluded from training.
    active["unknown_year"] = pd.Series(cy.isna(), index=summary_df.index)

    for name in _FLAGS:
        active[name] = active[name].fillna(False).astype(bool)

    mat = pd.DataFrame({name: active[name] for name in _FLAGS}, index=summary_df.index)
    summary_df["uncertainty_flags"] = mat.apply(
        lambda row: ";".join(n for n in _FLAGS if row[n]) or "-", axis=1
    )
    summary_df["uncertainty_score"] = mat.sum(axis=1).astype(int)
    return summary_df


def print_flag_tally(summary_df: pd.DataFrame) -> None:
    """Human-readable count of dams flagged by each reliability predicate."""
    if len(summary_df) == 0 or "uncertainty_flags" not in summary_df.columns:
        return
    flags_col = summary_df["uncertainty_flags"].fillna("")
    counts = {name: int(flags_col.str.contains(rf"\b{name}\b").sum()) for name in _FLAGS}
    total_flagged = int((summary_df["uncertainty_score"] > 0).sum())
    if total_flagged == 0:
        print(f"  Uncertainty flags: 0 dams flagged")
        return
    print(f"  Uncertainty flags: {total_flagged} / {len(summary_df)} dams flagged")
    for name in _FLAGS:
        if counts[name] > 0:
            print(f"    {name}: {counts[name]}")
