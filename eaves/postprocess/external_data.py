"""Optional external per-dam attributes merged into ``eaves_summary.csv``.

Currently supports:
- ``sedimentation_yield.csv`` -> ``sed_yield_t_ha_yr``
- ``owe_annual_mean.csv``     -> ``owe_mm_year`` (open-water evaporation)

Both files live under ``SEDIMENTATION_DIR`` and are keyed by ``dam_id``.
Columns stay ``NaN`` for dams absent from the source file.

Note: ``upstream_area_km2`` is also sourced from ``sedimentation_yield.csv``
but is attached upstream of this step -- the worker reads it from the
``dam_data`` dict (populated by :func:`cli._load_upstream_area_lookup`)
so that placement-failed dams already carry the column in
``failed_dams.csv``. This module no longer touches that column.
"""

from __future__ import annotations

import os
import pandas as pd


_MANAGED_COLS = (
    "sed_yield_t_ha_yr",
    "owe_mm_year",
)


def add_sedimentation_columns(summary_df: pd.DataFrame, sedimentation_dir: str | None) -> pd.DataFrame:
    if not sedimentation_dir or not os.path.isdir(sedimentation_dir):
        return summary_df

    summary_df = summary_df.drop(
        columns=[c for c in _MANAGED_COLS if c in summary_df.columns]
    )

    sed_path = os.path.join(sedimentation_dir, "sedimentation_yield.csv")
    if os.path.isfile(sed_path):
        sed = pd.read_csv(sed_path)[["dam_id", "sed_yield_t_ha_yr"]]
        summary_df = summary_df.merge(sed, on="dam_id", how="left")

    owe_path = os.path.join(sedimentation_dir, "owe_annual_mean.csv")
    if os.path.isfile(owe_path):
        owe = pd.read_csv(owe_path)[["dam_id", "owe_mm_year"]]
        summary_df = summary_df.merge(owe, on="dam_id", how="left")

    return summary_df
