"""Worked-example dam helpers — shared by p3 (Baish DEM/A-V) and p4 (validation).

The dam id is read from ``eaves.config.BATHYMETRY_DAM_ID`` and resolves to the
reservoir whose sonar bathymetry is shipped with the descriptor (Baish in KSA).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

import eaves.config as _cfg


def example_dam_id() -> str:
    dam_id = getattr(_cfg, "BATHYMETRY_DAM_ID", None)
    if not dam_id:
        raise RuntimeError(
            "BATHYMETRY_DAM_ID not configured. Load a settings file (e.g. "
            "region/ksa/ksa.json) before generating the worked-example panels."
        )
    return dam_id


def example_paths() -> tuple[Path, Path]:
    eav_csv = Path(_cfg.EAV_DIR) / f"{example_dam_id()}_eav.csv"
    summary_csv = Path(_cfg.CSV_DIR) / "eaves_summary.csv"
    return eav_csv, summary_csv


def example_summary_row() -> pd.Series:
    _, summary_csv = example_paths()
    summary = pd.read_csv(summary_csv)
    row = summary[summary["dam_id"] == example_dam_id()]
    if row.empty:
        raise RuntimeError(f"Dam {example_dam_id()!r} not found in {summary_csv}")
    return row.iloc[0]
