"""Clean the KSA dams catalogue CSV and emit a removal audit.

KSA-specific data preparation. Lives alongside the KSA input bundle so that
region-specific curation stays out of the generic EAVES package. Run this
whenever the source catalogue is updated. The pipeline then reads the
cleaned CSV directly.

Removes the following categories:
  - ``no_capacity``: ``storage_capacity_m3`` missing or ≤ 0.
  - ``no_dam_length``: ``dam_length_m`` missing or ≤ 0, which leaves no crest to
    anchor the reservoir footprint.
  - ``subsurface``: dams typed ``subsurface`` in the catalogue, infiltration
    structures with no surface reservoir, and entries with no wall at the
    coordinate on satellite imagery, which the catalogue types the same way.
  - ``no_satellite_records``: dam has no ``{dam_id}_ts_filtered.csv`` in the
    ``water_extent_ts/`` sibling directory. Regionalization cannot anchor
    A_cap without a satellite time series.

Dams with missing ``construction_year`` are KEPT. In the KSA catalogue they
represent post-2000 incomplete records, not invalid entries.

Restates ``dam_height_m`` above the riverbed where the catalogue measures it
from another datum (``_HEIGHT_ABOVE_RIVERBED_M``). The riverbed is the datum
of ``spillway_height_m`` and of the EAVES wall, which stands on the SRTM
valley floor at the dam. Hali (``id_020019``) is catalogued at 87 m with a
47 m spillway, a 40 m freeboard. Its published height is 57 m above the
thalweg (Saudipedia, "Wadi Hali Dam") and 95 m above the foundation
(Wikipedia, "Hali Dam"), so the catalogue's 87 m is not a riverbed height.

Reproducible. Re-running on an already-cleaned CSV is a no-op (produces an
empty audit).

Usage:
    python input/ksa_dams/clean_catalogue.py

Inputs (relative to this script's directory):
  - ksa_dams_transliterated.csv
  - water_extent_ts/

Outputs:
  - ksa_dams_transliterated.csv  (overwritten, cleaned)
  - ksa_dams_excluded.csv        (audit: dam_id, dam_name, reason)
"""

from __future__ import annotations

import os
import pandas as pd


_HEIGHT_ABOVE_RIVERBED_M = {"id_020019": 57.0}


def _dams_with_water_extent(ts_dir: str) -> set[str]:
    if not os.path.isdir(ts_dir):
        return set()
    return {
        fn.replace("_ts_filtered.csv", "")
        for fn in os.listdir(ts_dir)
        if fn.startswith("id_") and fn.endswith("_ts_filtered.csv")
    }


def clean_catalogue(csv_path: str, audit_path: str, ts_dir: str) -> None:
    df = pd.read_csv(csv_path, dtype=str)
    n_before = len(df)
    have_ts = _dams_with_water_extent(ts_dir)

    restated = df["dam_id"].isin(_HEIGHT_ABOVE_RIVERBED_M.keys())
    df.loc[restated, "dam_height_m"] = df.loc[restated, "dam_id"].map(lambda d: f"{_HEIGHT_ABOVE_RIVERBED_M[d]:.1f}")

    reasons_per_dam: dict[str, list[str]] = {}

    for _, row in df.iterrows():
        dam_id = row["dam_id"]
        cap = row.get("storage_capacity_m3")
        if pd.isna(cap) or float(cap) <= 0:
            reasons_per_dam.setdefault(dam_id, []).append("no_capacity")
        length = row.get("dam_length_m")
        if pd.isna(length) or float(length) <= 0:
            reasons_per_dam.setdefault(dam_id, []).append("no_dam_length")
        if row.get("dam_type") == "subsurface":
            reasons_per_dam.setdefault(dam_id, []).append("subsurface")
        if dam_id not in have_ts:
            reasons_per_dam.setdefault(dam_id, []).append("no_satellite_records")

    excluded_rows = []
    for dam_id, reasons in reasons_per_dam.items():
        name = df.loc[df["dam_id"] == dam_id, "dam_name"].iloc[0]
        excluded_rows.append({
            "dam_id": dam_id,
            "dam_name": name,
            "reason": ";".join(reasons),
        })
    audit_df = pd.DataFrame(excluded_rows, columns=["dam_id", "dam_name", "reason"])
    audit_df = audit_df.sort_values("dam_id").reset_index(drop=True)
    audit_df.to_csv(audit_path, index=False)

    keep_mask = ~df["dam_id"].isin(reasons_per_dam.keys())
    cleaned = df[keep_mask].reset_index(drop=True)
    cleaned.to_csv(csv_path, index=False)

    print(f"Input catalogue:  {n_before} dams")
    print(f"Height restated:  {int(restated.sum())} dams")
    print(f"Removed:          {len(audit_df)} dams")
    for reason, count in audit_df["reason"].value_counts().items():
        print(f"  {reason}: {count}")
    print(f"Kept:             {len(cleaned)} dams")
    print(f"Audit written:    {audit_path}")


def main() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    csv_path = os.path.join(here, "ksa_dams_transliterated.csv")
    audit_path = os.path.join(here, "ksa_dams_excluded.csv")
    ts_dir = os.path.join(here, "water_extent_ts")
    clean_catalogue(csv_path, audit_path, ts_dir)


if __name__ == "__main__":
    main()
