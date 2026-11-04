"""Validation of EAV parameter assignment.

Default diagnostics (cheap, run unless skipped), all mirroring the logic in
:mod:`regionalization`:

* :func:`loo_regionalization_eval`: leave-one-out evaluation of the
  regionalization procedure on the training dams (trusted SRTM fits built
  after the SRTM acquisition). For each training dam, it hides the SRTM
  curve, re-runs the regionalization step
  (regional-median ``b``, the selected multi-feature LR anchor for
  ``A_cap``, plus the satellite 95th-percentile and log-log anchors for
  comparison, to back-solve ``c``) using the other training dams as
  training data, then
  compares the predicted volumes with the SRTM-derived reference curve at
  full, half and tenth pool (100%, 50% and 10% of ``A_DEM``).

* :func:`dem_vs_sat_area_check`: per-dam comparison of the DEM-derived
  full-pool area ``footprint_area_km2`` against the satellite 95th
  percentile ``water_area_km2``. Flags dams whose satellite 95th-percentile
  water area departs from the full-pool area by a factor of three or more.
  The observed pools rarely approach the design pool, so a much smaller
  satellite area is the common case.

* :func:`goodness_of_fit_check`: absolute fractional volume residual of
  every released curve at each fitted level, reported alongside
  ``r_squared``, with its medians by fill level, its value at the
  typical satellite extent and the residual of a two-segment fit.

* :func:`eaves.postprocess.regionalization.acap_regression_diagnostics`:
  collinearity and incremental leave-one-out skill of the ``A_cap`` regression
  features.

Opt-in diagnostics (expensive and off by default, each re-runs the real
flood-fill many times and is enabled by its own flag):

* ``--sensitivity``: :mod:`eaves.postprocess.sensitivity`. Perturbs five
  placement and acceptance constants (the two placement-scoring constants,
  the internal void-fraction threshold and the two constants of the drainage
  rule) and reports how the trusted-set size, grade distribution and median
  ``b`` move.

* ``--dem-mc``: :mod:`eaves.postprocess.dem_error`. SRTM vertical-error
  Monte-Carlo that propagates DEM noise into recovered volumes and ``b`` over a
  trusted-dam sample.

All write CSVs into ``OUTPUT_DIR/1_results_csv/validation/`` and print a
summary. None modifies ``eaves_params.csv`` or any existing released artifact.

Run with (cheap defaults only)::

    python -m eaves.postprocess.validation --settings region/ksa/ksa.json

Add the expensive steps explicitly when needed::

    python -m eaves.postprocess.validation --settings region/ksa/ksa.json \\
        --sensitivity --dem-mc
"""

from __future__ import annotations

import argparse
import os

import geopandas as gpd
import numpy as np
import pandas as pd
from numpy.polynomial.polynomial import polyfit

import eaves.config as _cfg

from ..cli import _build_dam_data_list, _load_translit_map
from ..settings import load_settings
from ..utils import dams_with_fill, round_released_columns
from .dem_error import dem_error_montecarlo
from .regionalization import (
    _REGIONAL_FEATURES,
    _fit_multi_anchor_lr,
    _predict_multi_anchor_lr,
    acap_regression_diagnostics,
)
from .reliability import training_mask, trusted_mask
from .sensitivity import sensitivity_sweep


def _read_sat_p95(water_extent_dir: str, dam_id: str) -> tuple[float, int]:
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
    return polyfit(log_cap[valid], log_area[valid], 1)


def loo_regionalization_eval(
    summary_csv: str,
    water_extent_dir: str,
    out_dir: str,
    *,
    test_area_fractions: tuple[float, ...] = (1.0, 0.5, 0.1),
) -> pd.DataFrame:
    """Leave-one-out validation of the regionalization procedure.

    Parameters
    ----------
    summary_csv : path to ``eaves_summary.csv``.
    water_extent_dir : per-dam ``{dam_id}_ts_filtered.csv`` directory.
    out_dir : directory to write ``regionalization_loo.csv`` into.
    test_area_fractions : evaluate V at these fractions of A_DEM.

    Returns the per-dam result DataFrame.
    """
    df = dams_with_fill(pd.read_csv(summary_csv))
    # The LOO runs on the training population (trusted and post-2000, with the small-population fallback), the dams the procedure is trained on
    df["training"] = training_mask(df)
    trusted = df[df["training"]].copy().reset_index(drop=True)
    if len(trusted) == 0:
        raise RuntimeError("No training dams in summary, nothing to validate.")

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

        # Builds the three anchors: current_sat (satellite P95 anchor), alt_loglog (capacity-only log-log), multi_lr (selected)
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
    round_released_columns(out).to_csv(out_path, index=False)

    _print_loo_summary(out, test_area_fractions, out_path)
    return out


def _print_loo_summary(out: pd.DataFrame, fracs, out_path: str) -> None:
    print("\n" + "=" * 70)
    print("  LOO REGIONALIZATION EVALUATION")
    print("=" * 70)
    print(f"  Dams evaluated: {len(out)}")
    for recipe in ("current", "alt", "multi"):
        print(f"\n  Recipe: {recipe}")
        print("    Source breakdown:")
        for src, n in out[f"{recipe}_source"].value_counts().items():
            print(f"      {src}: {n}")
        print("    Errors (signed log10 ratio of regionalized / SRTM):")
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
    df = dams_with_fill(pd.read_csv(summary_csv))
    df["reliable"] = trusted_mask(df)
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
    round_released_columns(out).to_csv(out_path, index=False)

    print("\n" + "=" * 70)
    print("  DEM FULL-POOL AREA vs SATELLITE P95 WATER AREA (trusted dams)")
    print("=" * 70)
    paired = out["sat_over_dem"].dropna()
    print(f"  Trusted dams:                {len(out)}")
    print(f"  With satellite data:         {len(paired)}")
    if len(paired) > 0:
        print(f"  median A_sat / A_DEM:        {paired.median():.2f}")
        print(f"  log10 ratio: median={out['log10_ratio'].median():+.3f}, "
              f"1-sigma={(out['log10_ratio'].quantile(0.84) - out['log10_ratio'].quantile(0.16))/2.0:.3f} log10 units")
    print("  Flag breakdown:")
    for flag, n in out["flag"].value_counts(dropna=False).items():
        flag_label = flag if flag else f"(within {flag_ratio:.0f}x)"
        print(f"    {flag_label}: {n}")
    print(f"\n  Saved: {out_path}")
    print("=" * 70)
    return out


_MIN_SEGMENT_LEVELS = 3

_AREA_BANDS = (
    ("upper_half", 0.5, 1.01),
    ("quarter_to_half", 0.25, 0.5),
    ("tenth_to_quarter", 0.1, 0.25),
    ("below_tenth", 0.0, 0.1),
)


def _two_segment_rms(log_a, log_v, v, upper):
    """RMS fractional residual of the best two-segment straight-line fit in log space, over every level and over the upper levels.

    The break runs over every split that leaves at least ``_MIN_SEGMENT_LEVELS``
    levels in each segment, and the split with the smallest log-space sum of
    squares is kept. Returns NaN pairs when the levels are too few.
    """
    n = len(log_a)
    if n < 2 * _MIN_SEGMENT_LEVELS:
        return np.nan, np.nan
    best_sse = np.inf
    best_pred = None
    for k in range(_MIN_SEGMENT_LEVELS, n - _MIN_SEGMENT_LEVELS + 1):
        lower = np.polyfit(log_a[:k], log_v[:k], 1)
        higher = np.polyfit(log_a[k:], log_v[k:], 1)
        pred = np.concatenate([np.polyval(lower, log_a[:k]), np.polyval(higher, log_a[k:])])
        sse = float(np.sum((log_v - pred) ** 2))
        if sse < best_sse:
            best_sse, best_pred = sse, pred
    frac = np.abs(np.exp(best_pred) - v) / v
    return float(np.sqrt(np.mean(frac ** 2))), float(np.sqrt(np.mean(frac[upper] ** 2)))


def _typical_extent_frac(out_dir: str) -> float:
    """Median satellite 95th-percentile extent over the full-pool area, from ``dem_vs_sat_area.csv`` of ``out_dir`` when it exists."""
    path = os.path.join(out_dir, "dem_vs_sat_area.csv")
    if not os.path.isfile(path):
        return np.nan
    ratio = pd.read_csv(path)["sat_over_dem"].dropna()
    return float(ratio.median()) if len(ratio) else np.nan


def goodness_of_fit_check(
    summary_csv: str,
    params_csv: str,
    eav_tables_dir: str,
    out_dir: str,
    typical_extent_frac: float = np.nan,
) -> pd.DataFrame:
    """Fractional volume residual of every released EAV curve at each fitted level.

    The reported ``r_squared`` is computed on the untransformed volumes, so
    the fit and its R² emphasize the upper levels, where most storage lies,
    and a high R² can mask larger relative errors at low storage. This
    routine re-reads each per-dam EAV table and reports the residual
    *alongside* (not replacing) ``r_squared``:

    * ``max_frac_resid``: the maximum absolute fractional volume residual
      max_i |c * A_i^b - V_i| / V_i over the fitted elevation levels.
    * ``rms_frac_resid``: the root-mean-square of the same per-level
      fractional residual.
    * ``abs_frac_resid_full_pool``: the residual at the top fitted level.
    * ``median_abs_frac_resid_<band>``: the median residual over the levels
      whose area is in a band of the top fitted area, the upper half, a
      quarter to a half, a tenth to a quarter and below a tenth.
    * ``abs_frac_dev_typical_extent``: the departure |c * a^b / V(a) - 1| at
      the area ``a`` that is ``typical_extent_frac`` of the top area, with
      V(a) interpolated in the EAV table. ``typical_extent_frac`` is the
      domain median of the satellite 95th-percentile extent over the
      full-pool area, from ``dem_vs_sat_area.csv``.
    * ``rms_frac_resid_upper_volume``: the root-mean-square residual over
      the levels holding at least a tenth of the maximum fitted volume.
    * ``rms_frac_resid_two_segment`` and
      ``rms_frac_resid_two_segment_upper_volume``: the same two statistics
      for the best two-segment straight-line fit in log space, the
      alternative to the single power law.

    All are evaluated in the A→V direction of the released curves over
    exactly the levels the power law was fit on: levels above
    ``srtm_water_level_m`` for the ``partial`` curves, all
    positive-area/positive-volume levels otherwise (mirroring
    :mod:`eaves.pipeline.curves`). This is a diagnostic CSV only.
    It neither alters the grade gates nor the trusted-set filter, and writes
    nothing back into ``eaves_summary.csv``.

    Writes ``goodness_of_fit.csv`` and prints a distribution summary over the
    trusted set.
    """
    summary = dams_with_fill(pd.read_csv(summary_csv))
    params = pd.read_csv(params_csv).set_index("dam_id")
    summary["trusted"] = trusted_mask(summary)
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
            "abs_frac_resid_full_pool": np.nan,
            **{f"median_abs_frac_resid_{band}": np.nan for band, _, _ in _AREA_BANDS},
            "abs_frac_dev_typical_extent": np.nan,
            "rms_frac_resid_upper_volume": np.nan,
            "rms_frac_resid_two_segment": np.nan,
            "rms_frac_resid_two_segment_upper_volume": np.nan,
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
                rec["abs_frac_resid_full_pool"] = float(frac[-1])
                area_ratio = Af / Af.max()
                for band, lo, hi in _AREA_BANDS:
                    in_band = (area_ratio >= lo) & (area_ratio < hi)
                    if in_band.any():
                        rec[f"median_abs_frac_resid_{band}"] = float(np.median(frac[in_band]))
                if np.isfinite(typical_extent_frac):
                    a_typ = typical_extent_frac * A[-1]
                    v_typ = float(np.interp(a_typ, A, V))
                    if v_typ > 0:
                        rec["abs_frac_dev_typical_extent"] = float(abs(c * a_typ ** b / v_typ - 1.0))
                upper = Vf >= 0.1 * Vf.max()
                rec["rms_frac_resid_upper_volume"] = float(np.sqrt(np.mean(frac[upper] ** 2)))
                rec["rms_frac_resid_two_segment"], rec["rms_frac_resid_two_segment_upper_volume"] = (
                    _two_segment_rms(np.log(Af), np.log(Vf), Vf, upper))
        rows.append(rec)

    out = pd.DataFrame(rows)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "goodness_of_fit.csv")
    round_released_columns(out).to_csv(out_path, index=False)

    print("\n" + "=" * 70)
    print("  GOODNESS-OF-FIT (fractional volume residual per fitted level)")
    print("=" * 70)
    trusted = out[out["is_trusted"] & out["max_frac_resid"].notna()]
    print(f"  Dams with a curve:           {int(out['max_frac_resid'].notna().sum())}")
    print(f"  Trusted dams:                {len(trusted)}")
    if len(trusted) > 0:
        for col, label in (("r_squared", "R^2"),
                           ("max_frac_resid", "max |dV|/V"),
                           ("rms_frac_resid", "RMS |dV|/V"),
                           ("rms_frac_resid_upper_volume", "RMS, V>=0.1 Vmax"),
                           ("rms_frac_resid_two_segment", "RMS two-seg"),
                           ("rms_frac_resid_two_segment_upper_volume", "two-seg, V>=0.1 Vmax"),
                           ("abs_frac_resid_full_pool", "|dV|/V full pool"),
                           ("median_abs_frac_resid_upper_half", "median, A>=0.5 Amax"),
                           ("median_abs_frac_resid_below_tenth", "median, A<0.1 Amax"),
                           ("abs_frac_dev_typical_extent", "|dV|/V typical ext")):
            s = trusted[col].dropna()
            if len(s) == 0:
                continue
            print(f"  {label:<22s} median={s.median():.3f}  "
                  f"P16={s.quantile(0.16):.3f}  P84={s.quantile(0.84):.3f}  "
                  f"P95={s.quantile(0.95):.3f}  max={s.max():.3f}")
        if np.isfinite(typical_extent_frac):
            print(f"  typical extent = {typical_extent_frac:.4f} of the full-pool area")
    print(f"\n  Saved: {out_path}")
    print("=" * 70)
    return out


def _resolve_paths(settings_json: str | None) -> tuple[str, str, str]:
    """Returns (summary_csv, water_extent_dir, out_dir)."""
    if settings_json is not None:
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
        help="Skip the A_DEM vs A_sat^P95 area comparison.",
    )
    p.add_argument(
        "--skip-gof", action="store_true",
        help="Skip the fractional-volume-residual goodness-of-fit check.",
    )
    p.add_argument(
        "--skip-acap", action="store_true",
        help="Skip the A_cap regression diagnostics.",
    )
    # ---- Opt-in expensive steps, off by default ----
    p.add_argument(
        "--sensitivity", action="store_true",
        help="OPT-IN: run the sensitivity sweep of the five placement/acceptance "
        "constants, drainage rule included (eaves.postprocess.sensitivity). "
        "Expensive, off by default.",
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
        "(eaves.postprocess.dem_error). Expensive, off by default.",
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
        goodness_of_fit_check(summary_csv, params_csv, eav_tables_dir, out_dir,
                              typical_extent_frac=_typical_extent_frac(out_dir))
    if not args.skip_acap:
        acap_regression_diagnostics(dams_with_fill(pd.read_csv(summary_csv)), out_dir)

    if args.sensitivity:
        dam_data_list, gdf_rivers = _load_dams_and_rivers()
        sensitivity_sweep(
            summary_csv, out_dir,
            dam_data_list=dam_data_list, gdf_rivers=gdf_rivers,
            n_dams=args.sensitivity_n_dams, seed=args.sensitivity_seed,
        )

    if args.dem_mc:
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
