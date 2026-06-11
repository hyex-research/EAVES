"""Validation of EAV parameter assignment.

Default diagnostics (cheap, run unless skipped), all mirroring the logic in
:mod:`regionalization`:

* :func:`loo_regionalization_eval` -- leave-one-out evaluation of the
  regionalization recipe on the training dams (trusted SRTM fits built
  after the SRTM acquisition). For each training dam, hide its SRTM
  curve, re-run the regionalization step
  (regional-median ``b``; the shipped multi-feature LR anchor for
  ``A_cap``, plus the retired satellite and log-log anchors for
  comparison, to back-solve ``c``) using the other training dams as
  training data, then
  compare the regionalized curve against the SRTM "truth".

* :func:`dem_vs_sat_area_check` -- per-dam comparison of the DEM-derived
  full-pool area ``footprint_area_km2`` against the satellite 95th
  percentile ``water_area_km2``. Flags placement / satellite disagreement.

* :func:`goodness_of_fit_check` -- deployed-direction fractional volume
  residual of every fitted curve, reported alongside ``r_squared``.

Opt-in diagnostics (expensive, OFF by default; each re-runs the real
flood-fill many times and is enabled by its own flag):

* ``--sensitivity`` -- :mod:`eaves.postprocess.sensitivity`. Perturbs the three
  hand-tuned placement/acceptance constants and reports how the trusted-set
  size, grade distribution and median ``b`` move (theme T6).

* ``--dem-mc`` -- :mod:`eaves.postprocess.dem_error`. SRTM vertical-error
  Monte-Carlo: propagates DEM noise into recovered volumes and ``b`` over a
  trusted-dam sample (DEM reviewer #1).

All write CSVs into ``OUTPUT_DIR/1_results_csv/validation/`` and print a
summary. None modifies ``eaves_params.csv`` or any existing released artefact.

Run with (cheap defaults only)::

    python -m eaves.postprocess.validation --settings region/ksa/ksa.json

Add the expensive steps explicitly when needed::

    python -m eaves.postprocess.validation --settings region/ksa/ksa.json \\
        --sensitivity --dem-mc
"""

from __future__ import annotations

import argparse
import os
from typing import Tuple

import numpy as np
import pandas as pd

import eaves.config as _cfg
from .reliability import training_mask
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
    # The LOO runs on the training population (trusted AND post-2000, with
    # the small-population fallback), the dams the recipe is trained on.
    df["training"] = training_mask(df)
    trusted = df[df["training"]].copy().reset_index(drop=True)
    if len(trusted) == 0:
        raise RuntimeError("No training dams in summary -- nothing to validate.")

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

        # Recipes: current_sat (P95 anchor), alt_loglog (single-feature), multi_lr (shipped).
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
                f"1-sigma={spread:.3f} log10 units, "
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
              f"1-sigma={(out['log10_ratio'].quantile(0.84) - out['log10_ratio'].quantile(0.16))/2.0:.3f} log10 units")
    print(f"  Flag breakdown:")
    for flag, n in out["flag"].value_counts(dropna=False).items():
        flag_label = flag if flag else "(within {0:.0f}x)".format(flag_ratio)
        print(f"    {flag_label}: {n}")
    print(f"\n  Saved: {out_path}")
    print("=" * 70)
    return out


def goodness_of_fit_check(
    summary_csv: str,
    params_csv: str,
    eav_tables_dir: str,
    out_dir: str,
) -> pd.DataFrame:
    """Non-mechanical goodness-of-fit for every fitted EAV curve.

    The reported ``r_squared`` is a least-squares fit on the cumulative
    volume integral, so it is close to unity by construction (an
    integral-vs-integrand artefact) and tells us little about how faithfully
    the deployed curve $V = c\\,A^{b}$ reproduces the hypsometry. This routine
    re-reads each per-dam EAV table and reports two fit-direction metrics
    *alongside* (not replacing) ``r_squared``:

    * ``max_frac_resid`` -- the maximum absolute fractional volume residual
      $\\max_i |c A_i^b - V_i| / V_i$ over the fitted elevation bins.
    * ``rms_frac_resid`` -- the root-mean-square of the same per-bin
      fractional residual.

    Both are evaluated in the **deployed** A$\\to$V direction over exactly the
    bins the power law was fit on: bins above ``srtm_water_level_m`` for the
    ``partial`` curves, all positive-area/positive-volume bins otherwise
    (mirroring :func:`eaves.pipeline.curves` ). This is a diagnostic CSV only;
    it neither alters the grade gates nor the trusted-set filter, and writes
    nothing back into ``eaves_summary.csv``.

    Writes ``goodness_of_fit.csv`` and prints a distribution summary over the
    trusted set.
    """
    summary = pd.read_csv(summary_csv)
    params = pd.read_csv(params_csv).set_index("dam_id")
    summary["trusted"] = _reliable_mask(summary)
    summary["in_training"] = training_mask(summary)

    rows = []
    for _, row in summary.iterrows():
        dam_id = row["dam_id"]
        table_path = os.path.join(eav_tables_dir, f"{dam_id}_eav.csv")
        rec = {
            "dam_id":        dam_id,
            "source":        params.at[dam_id, "source"] if dam_id in params.index else "",
            "quality":       row.get("quality", ""),
            "r_squared":     float(row["r_squared"]) if np.isfinite(row.get("r_squared", np.nan)) else np.nan,
            "is_trusted":    bool(row["trusted"]),
            "in_training":   bool(row["in_training"]),
            "n_fit_bins":    0,
            "max_frac_resid": np.nan,
            "rms_frac_resid": np.nan,
        }
        if dam_id in params.index and os.path.isfile(table_path):
            c = float(params.at[dam_id, "c"])
            b = float(params.at[dam_id, "b"])
            tab = pd.read_csv(table_path)
            A = tab["area_m2"].to_numpy(dtype=float)
            V = tab["volume_m3"].to_numpy(dtype=float)
            z = tab["elevation_m"].to_numpy(dtype=float)
            base = (A > 0) & (V > 0)
            ct = str(row.get("curve_type", ""))
            wl = row.get("srtm_water_level_m", np.nan)
            if ct == "partial" and np.isfinite(wl):
                fit_mask = base & (z >= wl)
            else:
                fit_mask = base
            if (fit_mask.sum() >= 1 and np.isfinite(c) and np.isfinite(b)
                    and c > 0 and b > 0):
                Af = A[fit_mask]
                Vf = V[fit_mask]
                v_pred = c * np.power(Af, b)
                frac = np.abs(v_pred - Vf) / Vf
                rec["n_fit_bins"]     = int(fit_mask.sum())
                rec["max_frac_resid"] = float(np.max(frac))
                rec["rms_frac_resid"] = float(np.sqrt(np.mean(frac ** 2)))
        rows.append(rec)

    out = pd.DataFrame(rows)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "goodness_of_fit.csv")
    out.to_csv(out_path, index=False)

    print("\n" + "=" * 70)
    print("  GOODNESS-OF-FIT (deployed A->V fractional volume residual)")
    print("=" * 70)
    trusted = out[out["is_trusted"] & out["max_frac_resid"].notna()]
    print(f"  Dams with a curve:           {int(out['max_frac_resid'].notna().sum())}")
    print(f"  Trusted dams:                {len(trusted)}")
    if len(trusted) > 0:
        for col, label in (("r_squared", "R^2"),
                           ("max_frac_resid", "max |dV|/V"),
                           ("rms_frac_resid", "RMS |dV|/V")):
            s = trusted[col].dropna()
            print(f"  {label:<12s} median={s.median():.3f}  "
                  f"P16={s.quantile(0.16):.3f}  P84={s.quantile(0.84):.3f}  "
                  f"P95={s.quantile(0.95):.3f}  max={s.max():.3f}")
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


def _load_dams_and_rivers():
    """Build the worker dam-dict list and the split river network.

    Shared setup for the two opt-in steps (sensitivity, DEM-MC), which both
    re-run the real flood-fill. Reuses the production CLI helpers so the dam
    inputs are byte-identical to a normal pipeline run.
    """
    import geopandas as gpd
    from eaves.cli import _load_translit_map, _build_dam_data_list

    translit = _load_translit_map()
    gdf_dams = gpd.read_file(os.path.join(_cfg.DOMAIN_DIR, "dams_snapped.geojson"))
    dam_data_list = _build_dam_data_list(gdf_dams, translit)
    rivers_path = os.path.join(_cfg.DOMAIN_DIR, "rivers_split.geojson")
    gdf_rivers = gpd.read_file(rivers_path) if os.path.isfile(rivers_path) else None
    return dam_data_list, gdf_rivers


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
    p.add_argument(
        "--skip-gof", action="store_true",
        help="Skip the deployed-direction goodness-of-fit check.",
    )
    # --- Opt-in expensive steps (OFF by default; each re-runs the flood-fill) ---
    p.add_argument(
        "--sensitivity", action="store_true",
        help="OPT-IN: run the placement/acceptance constant sensitivity sweep "
        "(eaves.postprocess.sensitivity). Expensive -- off by default.",
    )
    p.add_argument(
        "--sensitivity-n-dams", type=int, default=60,
        help="Trusted-dam sample size for --sensitivity.",
    )
    p.add_argument(
        "--sensitivity-seed", type=int, default=7,
        help="RNG seed for the --sensitivity sample draw.",
    )
    p.add_argument(
        "--dem-mc", action="store_true",
        help="OPT-IN: run the SRTM vertical-error Monte-Carlo "
        "(eaves.postprocess.dem_error). Expensive -- off by default.",
    )
    p.add_argument(
        "--dem-mc-n-dams", type=int, default=36,
        help="Trusted-dam sample size for --dem-mc.",
    )
    p.add_argument(
        "--dem-mc-n-real", type=int, default=32,
        help="Perturbed realizations drawn per dam for --dem-mc.",
    )
    p.add_argument(
        "--dem-mc-sigma-m", type=float, default=3.6,
        help="Point sigma of SRTM vertical noise for --dem-mc (LE90 6 m / 1.6449).",
    )
    p.add_argument(
        "--dem-mc-corr-px", type=float, default=2.0,
        help="Spatial correlation length in SRTM pixels for --dem-mc.",
    )
    p.add_argument(
        "--dem-mc-seed", type=int, default=12345,
        help="Master RNG seed for --dem-mc (sample draw + per-dam seeds).",
    )
    p.add_argument(
        "--dem-mc-budget-s", type=float, default=600.0,
        help="Max wall-clock seconds per dam's realizations for --dem-mc.",
    )
    p.add_argument(
        "--dem-mc-workers", type=int, default=8,
        help="Parallel dam workers for --dem-mc (1 = serial).",
    )
    p.add_argument(
        "--dem-mc-fresh", action="store_true",
        help="Ignore any existing dem_error_montecarlo.csv and start over "
        "(default: resume, skipping dams already in the CSV).",
    )
    args = p.parse_args(argv)

    summary_csv, water_extent_dir, out_dir = _resolve_paths(args.settings)

    if not args.skip_loo:
        loo_regionalization_eval(summary_csv, water_extent_dir, out_dir)
    if not args.skip_area_check:
        dem_vs_sat_area_check(summary_csv, water_extent_dir, out_dir)
    if not args.skip_gof:
        params_csv = os.path.join(_cfg.CSV_DIR, "eaves_params.csv")
        eav_tables_dir = os.path.join(_cfg.CSV_DIR, "eav_tables")
        goodness_of_fit_check(summary_csv, params_csv, eav_tables_dir, out_dir)

    if args.sensitivity:
        from .sensitivity import sensitivity_sweep
        dam_data_list, gdf_rivers = _load_dams_and_rivers()
        sensitivity_sweep(
            summary_csv, _cfg.DOMAIN_DIR, out_dir,
            dam_data_list=dam_data_list, gdf_rivers=gdf_rivers,
            n_dams=args.sensitivity_n_dams, seed=args.sensitivity_seed,
        )

    if args.dem_mc:
        from .dem_error import dem_error_montecarlo
        dam_data_list, gdf_rivers = _load_dams_and_rivers()
        dem_error_montecarlo(
            summary_csv, args.settings, _cfg.DOMAIN_DIR, out_dir,
            dam_data_list=dam_data_list, gdf_rivers=gdf_rivers,
            n_dams=args.dem_mc_n_dams, n_real=args.dem_mc_n_real,
            sigma_m=args.dem_mc_sigma_m, corr_px=args.dem_mc_corr_px,
            seed=args.dem_mc_seed, per_dam_budget_s=args.dem_mc_budget_s,
            workers=args.dem_mc_workers, fresh=args.dem_mc_fresh,
        )


if __name__ == "__main__":
    main()
