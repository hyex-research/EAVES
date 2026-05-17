"""Validation of EAV parameter assignment.

Two diagnostics, both mirroring the logic in :mod:`regionalization`:

* :func:`loo_regionalization_eval` -- leave-one-out evaluation of the
  regionalization recipe on the "trusted" SRTM-derived dams. For each
  trusted dam, hide its SRTM curve, re-run the regionalization step
  (regional-median ``b``, satellite-anchored or fallback ``A_cap`` to
  back-solve ``c``) using the other trusted dams as training data, then
  compare the regionalized curve against the SRTM "truth".

* :func:`dem_vs_sat_area_check` -- per-dam comparison of the DEM-derived
  full-pool area ``footprint_area_km2`` against the satellite 95th
  percentile ``water_area_km2``. Flags placement / satellite disagreement.

Both write CSVs into ``OUTPUT_DIR/1_results_csv/validation/`` and print a
summary. Neither modifies ``eaves_params.csv`` or any existing artefact.

Run with:
    python -m eaves.postprocess.validation \\
        --settings region/ksa/ksa.json
"""

from __future__ import annotations

import argparse
import os
from typing import Tuple

import numpy as np
import pandas as pd

import eaves.config as _cfg
from .regionalization import (
    _REGIONAL_FEATURES,
    _fit_multi_anchor_lr,
    _predict_multi_anchor_lr,
)


def _reliable_mask(df: pd.DataFrame) -> pd.Series:
    """Same definition as regionalization.run_regionalization step A."""
    return (
        df["quality"].isin(["A", "B"])
        & (df["r_squared"] >= 0.98)
        & df["vol_ratio"].between(0.3, 5.0)
        & (df["n_pixels"] >= 50)
        & df["b"].notna()
    )


def _read_sat_p95(water_extent_dir: str, dam_id: str) -> Tuple[float, int]:
    """Return (A_cap_P95_km2, n_obs). NaN, 0 if unavailable / insufficient."""
    path = os.path.join(water_extent_dir, f"{dam_id}_ts_filtered.csv")
    if not os.path.isfile(path):
        return np.nan, 0
    try:
        df = pd.read_csv(path)
    except Exception:
        return np.nan, 0
    if "water_area_km2" not in df.columns:
        return np.nan, 0
    areas = df["water_area_km2"].dropna()
    n = int(len(areas))
    if n <= 5:
        return np.nan, n
    return float(areas.quantile(0.95)), n


def _fit_a_cap_fallback(train: pd.DataFrame):
    """log A_cap = alpha + beta * log capacity_mcm, fit on training set."""
    log_cap = np.log(train["capacity_mcm"].values)
    log_area = np.log(train["footprint_area_km2"].values)
    valid = np.isfinite(log_cap) & np.isfinite(log_area)
    if valid.sum() < 10:
        return None
    from numpy.polynomial.polynomial import polyfit
    return polyfit(log_cap[valid], log_area[valid], 1)


def loo_regionalization_eval(
    summary_csv: str,
    water_extent_dir: str,
    out_dir: str,
    *,
    test_area_fractions: Tuple[float, ...] = (1.0, 0.5, 0.1),
) -> pd.DataFrame:
    """Leave-one-out validation of the regionalization recipe.

    Parameters
    ----------
    summary_csv : path to ``eaves_summary.csv``.
    water_extent_dir : per-dam ``{dam_id}_ts_filtered.csv`` directory.
    out_dir : directory to write ``regionalization_loo.csv`` into.
    test_area_fractions : evaluate V at these fractions of A_DEM.

    Returns the per-dam result DataFrame.
    """
    df = pd.read_csv(summary_csv)
    df["reliable"] = _reliable_mask(df)
    trusted = df[df["reliable"]].copy().reset_index(drop=True)
    if len(trusted) == 0:
        raise RuntimeError("No reliable dams in summary -- nothing to validate.")

    rows = []
    for i, row in trusted.iterrows():
        dam_id = row["dam_id"]
        capacity_m3 = float(row["capacity_mcm"]) * 1e6
        if capacity_m3 <= 0:
            continue
        a_dem_km2 = float(row["footprint_area_km2"])
        if not np.isfinite(a_dem_km2) or a_dem_km2 <= 0:
            continue
        c_srtm = float(row["c"])
        b_srtm = float(row["b"])

        train = trusted.drop(index=i)
        b_reg = float(train["b"].median())
        c_median = float(train["c"].median())
        fallback = _fit_a_cap_fallback(train)
        multi_coef = _fit_multi_anchor_lr(train)

        a_sat_p95, n_obs = _read_sat_p95(water_extent_dir, dam_id)

        # ---- Three recipes evaluated for every dam ----
        # current_sat : satellite P95 anchor; fall back to log-log only if
        #               satellite is missing (mirrors the historical recipe).
        # alt_loglog  : single-feature log-log A_cap(capacity) anchor.
        # multi_lr    : multi-feature linear regression on log features --
        #               the recipe shipped in regionalization.py.
        anchors: dict[str, tuple[float, str]] = {}

        a_curr = np.nan
        src_curr = "current_sat_no_anchor"
        if np.isfinite(a_sat_p95) and a_sat_p95 > 0:
            a_curr, src_curr = a_sat_p95, "current_sat_p95"
        elif fallback is not None:
            a_curr = float(np.exp(fallback[0] + fallback[1] * np.log(capacity_m3 / 1e6)))
            src_curr = "current_sat_fallback"
        anchors["current"] = (a_curr, src_curr)

        a_alt = np.nan
        src_alt = "alt_loglog_no_fit"
        if fallback is not None:
            a_alt = float(np.exp(fallback[0] + fallback[1] * np.log(capacity_m3 / 1e6)))
            src_alt = "alt_loglog_primary"
        anchors["alt"] = (a_alt, src_alt)

        a_multi = np.nan
        src_multi = "multi_no_fit"
        feat_row = {f: row.get(f) for f in _REGIONAL_FEATURES}
        a_multi_km2 = _predict_multi_anchor_lr(feat_row, multi_coef)
        if a_multi_km2 is not None and np.isfinite(a_multi_km2) and a_multi_km2 > 0:
            a_multi = float(a_multi_km2)
            src_multi = "multi_lr_primary"
        elif fallback is not None:
            a_multi = float(np.exp(fallback[0] + fallback[1] * np.log(capacity_m3 / 1e6)))
            src_multi = "multi_loglog_fallback"
        anchors["multi"] = (a_multi, src_multi)

        a_dem_m2 = a_dem_km2 * 1e6
        rec = {
            "dam_id": dam_id,
            "capacity_mcm": float(row["capacity_mcm"]),
            "A_DEM_km2": a_dem_km2,
            "A_sat_P95_km2": a_sat_p95,
            "n_sat_obs": n_obs,
            "c_srtm": c_srtm,
            "b_srtm": b_srtm,
            "b_reg": b_reg,
            "delta_b": b_reg - b_srtm,
        }

        for recipe, (a_cap_km2, src) in anchors.items():
            a_cap_m2 = a_cap_km2 * 1e6 if np.isfinite(a_cap_km2) else np.nan
            c_reg = np.nan
            if np.isfinite(a_cap_m2) and a_cap_m2 > 0 and np.isfinite(b_reg):
                c_reg = capacity_m3 / (a_cap_m2 ** b_reg)
            if not (np.isfinite(c_reg) and c_reg > 0):
                c_reg = c_median
                src = src + "+median_c"
            rec[f"{recipe}_source"] = src
            rec[f"{recipe}_A_cap_km2"] = a_cap_km2
            rec[f"{recipe}_c"] = c_reg
            rec[f"{recipe}_log10_c_ratio"] = (
                np.log10(c_reg / c_srtm) if c_srtm > 0 and c_reg > 0 else np.nan
            )
            for frac in test_area_fractions:
                a_test_m2 = frac * a_dem_m2
                v_srtm = c_srtm * (a_test_m2 ** b_srtm)
                v_reg = c_reg * (a_test_m2 ** b_reg)
                rec[f"{recipe}_V_at_{int(frac*100):03d}pct_m3"] = v_reg
                rec[f"V_srtm_at_{int(frac*100):03d}pct_m3"] = v_srtm
                if v_srtm > 0 and v_reg > 0:
                    rec[f"{recipe}_log10_V_ratio_at_{int(frac*100):03d}pct"] = np.log10(v_reg / v_srtm)
                else:
                    rec[f"{recipe}_log10_V_ratio_at_{int(frac*100):03d}pct"] = np.nan
        rows.append(rec)

    out = pd.DataFrame(rows)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "regionalization_loo.csv")
    out.to_csv(out_path, index=False)

    _print_loo_summary(out, test_area_fractions, out_path)
    return out


def _print_loo_summary(out: pd.DataFrame, fracs, out_path: str) -> None:
    print("\n" + "=" * 70)
    print("  LOO REGIONALIZATION EVALUATION")
    print("=" * 70)
    print(f"  Dams evaluated: {len(out)}")
    for recipe in ("current", "alt", "multi"):
        print(f"\n  Recipe: {recipe}")
        print(f"    Source breakdown:")
        for src, n in out[f"{recipe}_source"].value_counts().items():
            print(f"      {src}: {n}")
        print(f"    Errors (signed log10 ratio of regionalized / SRTM):")
        print(f"      median log10(c_reg/c_srtm) = "
              f"{out[f'{recipe}_log10_c_ratio'].median():+.3f}")
        for frac in fracs:
            col = f"{recipe}_log10_V_ratio_at_{int(frac*100):03d}pct"
            v = out[col].dropna()
            if len(v) == 0:
                continue
            bias = v.median()
            spread = (v.quantile(0.84) - v.quantile(0.16)) / 2.0
            within_factor2 = float(((v.abs() <= np.log10(2.0)).mean()) * 100)
            within_factor3 = float(((v.abs() <= np.log10(3.0)).mean()) * 100)
            print(
                f"      V at {int(frac*100):3d}% A_DEM: "
                f"median={bias:+.3f} (factor {10**bias:.2f}x), "
                f"1-sigma={spread:.3f} dex, "
                f"|err|<=2x: {within_factor2:.0f}%, "
                f"|err|<=3x: {within_factor3:.0f}%"
            )
    print(f"\n  Saved: {out_path}")
    print("=" * 70)


def dem_vs_sat_area_check(
    summary_csv: str,
    water_extent_dir: str,
    out_dir: str,
    *,
    flag_ratio: float = 3.0,
) -> pd.DataFrame:
    """For each trusted dam, compare DEM full-pool area against satellite P95.

    Writes ``dem_vs_sat_area.csv`` and prints a summary.
    """
    df = pd.read_csv(summary_csv)
    df["reliable"] = _reliable_mask(df)
    trusted = df[df["reliable"]].copy().reset_index(drop=True)

    rows = []
    for _, row in trusted.iterrows():
        a_dem = float(row["footprint_area_km2"])
        a_sat, n_obs = _read_sat_p95(water_extent_dir, row["dam_id"])
        if not np.isfinite(a_dem) or a_dem <= 0:
            continue
        rec = {
            "dam_id": row["dam_id"],
            "dam_name": row.get("dam_name", ""),
            "capacity_mcm": float(row["capacity_mcm"]),
            "A_DEM_km2": a_dem,
            "A_sat_P95_km2": a_sat,
            "n_sat_obs": n_obs,
            "quality": row.get("quality", ""),
        }
        if np.isfinite(a_sat) and a_sat > 0:
            ratio = a_sat / a_dem
            rec["sat_over_dem"] = ratio
            rec["log10_ratio"] = np.log10(ratio)
            if ratio >= flag_ratio:
                rec["flag"] = "sat_much_larger"
            elif ratio <= 1.0 / flag_ratio:
                rec["flag"] = "sat_much_smaller"
            else:
                rec["flag"] = ""
        else:
            rec["sat_over_dem"] = np.nan
            rec["log10_ratio"] = np.nan
            rec["flag"] = "no_sat"
        rows.append(rec)

    out = pd.DataFrame(rows)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "dem_vs_sat_area.csv")
    out.to_csv(out_path, index=False)

    print("\n" + "=" * 70)
    print("  DEM vs SATELLITE FULL-POOL AREA CHECK (trusted dams)")
    print("=" * 70)
    paired = out["sat_over_dem"].dropna()
    print(f"  Trusted dams:                {len(out)}")
    print(f"  With satellite data:         {len(paired)}")
    if len(paired) > 0:
        print(f"  median A_sat / A_DEM:        {paired.median():.2f}")
        print(f"  log10 ratio: median={out['log10_ratio'].median():+.3f}, "
              f"1-sigma={(out['log10_ratio'].quantile(0.84) - out['log10_ratio'].quantile(0.16))/2.0:.3f} dex")
    print(f"  Flag breakdown:")
    for flag, n in out["flag"].value_counts(dropna=False).items():
        flag_label = flag if flag else "(within {0:.0f}x)".format(flag_ratio)
        print(f"    {flag_label}: {n}")
    print(f"\n  Saved: {out_path}")
    print("=" * 70)
    return out


def _resolve_paths(settings_json: str | None) -> Tuple[str, str, str]:
    """Returns (summary_csv, water_extent_dir, out_dir)."""
    if settings_json is not None:
        from eaves.settings import load_settings
        load_settings(settings_json)
    summary_csv = os.path.join(_cfg.CSV_DIR, "eaves_summary.csv")
    water_extent_dir = _cfg.WATER_EXTENT_DIR
    out_dir = os.path.join(_cfg.CSV_DIR, "validation")
    return summary_csv, water_extent_dir, out_dir


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--settings", required=True,
        help="Path to region settings JSON (e.g. region/ksa/ksa.json).",
    )
    p.add_argument(
        "--skip-loo", action="store_true",
        help="Skip the LOO regionalization eval.",
    )
    p.add_argument(
        "--skip-area-check", action="store_true",
        help="Skip the A_DEM vs A_sat^P95 consistency check.",
    )
    args = p.parse_args(argv)

    summary_csv, water_extent_dir, out_dir = _resolve_paths(args.settings)

    if not args.skip_loo:
        loo_regionalization_eval(summary_csv, water_extent_dir, out_dir)
    if not args.skip_area_check:
        dem_vs_sat_area_check(summary_csv, water_extent_dir, out_dir)


if __name__ == "__main__":
    main()
