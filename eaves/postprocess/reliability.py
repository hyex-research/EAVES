"""Physical reliability predicates for EAVES curves.

Each flag marks a geometry regime where SRTM can't reliably resolve
the reservoir (grid resolution, vertical noise, or topographic edge cases).
Flags are additive — a dam can be tagged by several at once.

Thresholds are calibrated to SRTM 1 arc-sec (~30 m grid, ~2 m vertical noise,
~10 m horizontal LE90).
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
]


def add_uncertainty_flags(
    summary_df: pd.DataFrame,
    pixel_size_m: float = _PIXEL_SIZE_M_DEFAULT,
) -> pd.DataFrame:
    """Append ``uncertainty_flags`` and ``uncertainty_score`` columns.

    ``uncertainty_flags`` is a ``;``-joined list of active flag names (empty
    string when none apply). ``uncertainty_score`` is the number of active
    flags (0..5).
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
