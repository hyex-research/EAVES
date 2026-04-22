"""Clean the KSA dams catalogue CSV and emit a removal audit.

KSA-specific data preparation. Lives alongside the KSA input bundle so that
region-specific curation stays out of the generic EAVES package. Run this
whenever the source catalogue is updated; the pipeline then reads the
cleaned CSV directly.

Removes four categories:
  - ``zero_capacity``: ``storage_capacity_m3`` missing or ≤ 0.
  - ``zero_dam_length``: ``dam_length_m`` missing or ≤ 0 — no crest to
    anchor the reservoir footprint.
  - ``groundwater_dam`` / ``non_existing``: groundwater-recharge dams
    (intentional infiltration structures, no surface reservoir) and
    catalogue non-sites.
  - ``no_water_extent``: dam has no ``{dam_id}_ts_filtered.csv`` in the
    ``water_extent_ts/`` sibling directory — regionalization cannot anchor
    A_cap without a satellite time series.

Dams with missing ``construction_year`` are KEPT — in the KSA catalogue they
represent post-2000 incomplete records, not invalid entries.

Reproducible: re-running on an already-cleaned CSV is a no-op (produces an
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


_RECHARGE_DAM_IDS = [
    "id_020016", "id_080011", "id_020022", "id_120001", "id_070011",
    "id_120004", "id_130001", "id_080004", "id_080008", "id_080014",
    "id_080006", "id_070015", "id_080000",
]
_NONSITE_DAM_IDS = [
    "id_080001", "id_110003", "id_060010", "id_070115", "id_110001",
    "id_030013", "id_070071", "id_040011",
]
EXCLUDED = set(_RECHARGE_DAM_IDS + _NONSITE_DAM_IDS)


def _dams_with_water_extent(ts_dir: str) -> set[str]:
    if not os.path.isdir(ts_dir):
        return set()
    return {
        fn.replace("_ts_filtered.csv", "")
        for fn in os.listdir(ts_dir)
        if fn.startswith("id_") and fn.endswith("_ts_filtered.csv")
    }


def clean_catalogue(csv_path: str, audit_path: str, ts_dir: str) -> None:
    df = pd.read_csv(csv_path)
    n_before = len(df)
    have_ts = _dams_with_water_extent(ts_dir)

    reasons_per_dam: dict[str, list[str]] = {}

    for _, row in df.iterrows():
        dam_id = row["dam_id"]
        cap = row.get("storage_capacity_m3")
        if pd.isna(cap) or float(cap) <= 0:
            reasons_per_dam.setdefault(dam_id, []).append("zero_capacity")
        length = row.get("dam_length_m")
        if pd.isna(length) or float(length) <= 0:
            reasons_per_dam.setdefault(dam_id, []).append("zero_dam_length")
        if dam_id in EXCLUDED:
            kind = "groundwater_dam" if dam_id in _RECHARGE_DAM_IDS else "non_existing"
            reasons_per_dam.setdefault(dam_id, []).append(kind)
        if dam_id not in have_ts:
            reasons_per_dam.setdefault(dam_id, []).append("no_water_extent")

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
