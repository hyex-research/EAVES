"""Domain characterization and pipeline report.

Reads the EAVES pipeline outputs (``eaves_summary.csv``, ``eaves_params.csv``,
``failed_dams.csv``, ``validation/regionalization_loo.csv``,
``validation/dem_vs_sat_area.csv``) plus the auxiliary water-extent and
sedimentation inputs, computes a characterization of the reservoir
population in the configured region, and emits two artifacts:

1. ``<CSV_DIR>/domain_characterization.csv``
   Machine-readable key/value table of every statistic computed below, with
   its JSON twin ``domain_characterization.json`` beside it, the same
   statistics with typed values.
2. ``<OUTPUT_DIR>/report.md``
   Prose Markdown report covering the pipeline, the physics behind the
   power-law area-volume relation, domain characterization (catalog
   demographics, operational fill behavior, sediment budget, geometry
   distribution), the regionalization method and its accuracy, and the
   region-independent vs region-specific parts of the workflow.

Sections of the report degrade gracefully if validation CSVs are absent.
For a complete document run ``./run_all.sh``, which chains the validation,
uncertainty and panels steps before the report.

Usage:
    python -m eaves.postprocess.report --settings region/<region>/<region>.json
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import eaves.config as _cfg

from ..settings import load_settings
from ..utils import dams_with_fill, round_released_value, typed_value
from .panels.p6 import load_grdl_comparisons
from .panels.s1 import CLUSTER_FEATURES
from .regionalization import choose_reliability_threshold
from .reliability import training_mask, trusted_mask

# ---- Inputs ----

def _load_inputs() -> dict:
    csv_dir = Path(_cfg.CSV_DIR)
    paths = {
        "summary":         csv_dir / "eaves_summary.csv",
        "params":          csv_dir / "eaves_params.csv",
        "failed":          csv_dir / "failed_dams.csv",
        "threshold":       csv_dir / "threshold_analysis.csv",
        "validation_loo":     csv_dir / "validation" / "regionalization_loo.csv",
        "validation_area":    csv_dir / "validation" / "dem_vs_sat_area.csv",
        "validation_gof":     csv_dir / "validation" / "goodness_of_fit.csv",
        "b_clustering_diag":  csv_dir / "validation" / "b_clustering_diagnostic.csv",
    }
    out: dict[str, pd.DataFrame | None] = {}
    for k, p in paths.items():
        out[k] = pd.read_csv(p) if p.exists() else None
    # The statistics of the fill and of the fit describe the dams with a flood fill, and the catalog statistics every dam
    out["summary_all"] = out["summary"]
    if out["summary"] is not None:
        out["summary"] = dams_with_fill(out["summary"])
    return out


# ---- Characterization ----

_TRUSTED_FILTER_DOC = (
    "grade A or B, R² ≥ 0.98 and an active footprint of at least "
    "50 grid cells"
)


def _q(s: pd.Series, q: float) -> float:
    return float(s.quantile(q))


def compute_characterization(data: dict, ref_year: int | None = None,
                              sediment_sdr: float | None = None,
                              sediment_bulk_density: float = 1.3) -> dict:
    """Compute a complete domain characterization as a flat ``dict``.

    ``sed_yield_t_ha_yr`` is delivered yield (Dash et al. 2025,
    https://doi.org/10.1016/j.jenvman.2025.127199, RUSLE times an area-dependent delivery ratio
    applied at source) and takes no further delivery ratio, and
    ``sediment_sdr`` is a constant factor for gross-erosion inputs.
    """
    if ref_year is None:
        ref_year = datetime.now(UTC).year

    stats: dict[str, Any] = {}
    stats["region"] = getattr(_cfg, "TARGET_COUNTRY", "unknown")
    stats["reference_year"] = int(ref_year)

    summary = data["summary"]
    params = data["params"]
    failed = data["failed"]
    # Every dam of the summary, for the statistics that need no flood fill (construction year, dam height, sediment budget)
    catalog = data.get("summary_all")
    if catalog is None:
        catalog = summary

    if summary is not None:
        stats["n_dams_summary"] = int(len(summary))
    if failed is not None:
        stats["n_dams_failed_pipeline"] = int(len(failed))
    if params is not None:
        stats["n_dams_with_params"] = int(len(params))
        src = params["source"].value_counts().to_dict()
        for k, v in src.items():
            stats[f"n_params_source_{k}"] = int(v)
        regi_b = params.loc[params["source"] == "regi_multi", "b"].dropna()
        if len(regi_b):
            stats["b_regionalized"] = float(regi_b.median())

    # Capacity, year, dam height and sediment statistics span the released catalog
    cap_src = params if (params is not None and "capacity_mcm" in params.columns) else summary
    if cap_src is not None and "capacity_mcm" in cap_src.columns:
        cap = cap_src["capacity_mcm"].dropna()
        stats["capacity_total_mcm"]   = float(cap.sum())
        stats["capacity_median_mcm"]  = float(cap.median())
        stats["capacity_p05_mcm"]     = _q(cap, 0.05)
        stats["capacity_p95_mcm"]     = _q(cap, 0.95)
        stats["capacity_max_mcm"]     = float(cap.max())
        stats["n_cap_above_5mcm"]     = int((cap >= 5).sum())
        stats["n_cap_above_25mcm"]    = int((cap >= 25).sum())
        stats["n_cap_above_100mcm"]   = int((cap >= 100).sum())
        stats["n_cap_below_1mcm"]     = int((cap < 1).sum())

    if catalog is not None:
        if "construction_year" in catalog.columns:
            cy = catalog["construction_year"].dropna()
            stats["construction_year_min"]    = int(cy.min())
            stats["construction_year_median"] = int(cy.median())
            stats["construction_year_max"]    = int(cy.max())
            stats["n_pre_1980"]               = int((cy < 1980).sum())
            stats["n_1980_2000"]              = int(((cy >= 1980) & (cy < 2000)).sum())
            stats["n_2000_2010"]              = int(((cy >= 2000) & (cy < 2010)).sum())
            stats["n_post_2010"]              = int((cy >= 2010).sum())
            # Counts the dams without a year, which the era counts exclude
            stats["n_year_unknown"]           = int(catalog["construction_year"].isna().sum())

        if "dam_height_m" in catalog.columns:
            dh = catalog["dam_height_m"].dropna()
            stats["dam_height_median_m"] = float(dh.median())
            stats["dam_height_max_m"]    = float(dh.max())

    # Trusted-set geometry distribution
    if summary is not None and "b" in summary.columns:
        T = summary[trusted_mask(summary)].copy()
        b = T["b"].dropna()
        stats["n_trusted"] = int(len(T))
        if len(b) > 0:
            stats["b_median"]   = float(b.median())
            stats["b_p16"]      = _q(b, 0.16)
            stats["b_p84"]      = _q(b, 0.84)
            stats["b_sigma"]    = (stats["b_p84"] - stats["b_p16"]) / 2.0
            stats["b_p05"]      = _q(b, 0.05)
            stats["b_p95"]      = _q(b, 0.95)
            stats["b_min"]      = float(b.min())
            stats["b_max"]      = float(b.max())

        # Training set, the trusted dams built after the SRTM acquisition, which trains the regionalization and sets b_sigma
        TR = summary[training_mask(summary)].copy()
        bt = TR["b"].dropna()
        stats["n_training"] = int(len(TR))
        if len(bt) > 0:
            stats["b_median_training"] = float(bt.median())
            stats["b_p16_training"]    = _q(bt, 0.16)
            stats["b_p84_training"]    = _q(bt, 0.84)
            stats["b_sigma_training"]  = (stats["b_p84_training"]
                                          - stats["b_p16_training"]) / 2.0
            stats["b_p05_training"]    = _q(bt, 0.05)
            stats["b_p95_training"]    = _q(bt, 0.95)
            stats["b_min_training"]    = float(bt.min())
            stats["b_max_training"]    = float(bt.max())

        # Computes the strongest rank correlation of b with one feature on the regression basis, the training dams at or above the reliability threshold with every feature present
        thr = data.get("threshold")
        chosen = choose_reliability_threshold(thr) if thr is not None else None
        feats = ["valley_ratio", "channel_slope", "mean_catchment_slope", "dam_height_m"]
        if chosen is not None and set(feats).issubset(TR.columns):
            basis = TR[TR["capacity_mcm"] >= chosen].dropna(subset=feats + ["b"])
            basis = basis[(basis[feats] > 0).all(axis=1)]
            if len(basis) >= 10:
                rhos = {f: abs(float(basis["b"].corr(basis[f], method="spearman"))) for f in feats}
                f_max = max(rhos, key=rhos.get)
                stats["reliability_threshold_mcm"] = float(chosen)
                stats["n_regression_basis"] = int(len(basis))
                stats["b_feature_rho_max"] = rhos[f_max]
                stats["b_feature_rho_max_feature"] = f_max

        # Computes the strongest rank correlation of b with one clustering feature on the clustering basis, every training dam with the clustering features present
        if set(CLUSTER_FEATURES).issubset(TR.columns):
            cbasis = TR.dropna(subset=list(CLUSTER_FEATURES) + ["b"])
            cbasis = cbasis[(cbasis[CLUSTER_FEATURES] > 0).all(axis=1)]
            if len(cbasis) >= 10:
                rhos_c = {f: abs(float(cbasis["b"].corr(cbasis[f], method="spearman"))) for f in CLUSTER_FEATURES}
                f_max_c = max(rhos_c, key=rhos_c.get)
                stats["n_cluster_basis"] = int(len(cbasis))
                stats["b_feature_rho_max_cluster"] = rhos_c[f_max_c]
                stats["b_feature_rho_max_cluster_feature"] = f_max_c

        # Log-log area-capacity fit on the training set, the capacity-only anchor
        if {"capacity_mcm", "footprint_area_km2"}.issubset(TR.columns):
            mask = (TR["capacity_mcm"] > 0) & (TR["footprint_area_km2"] > 0)
            x = np.log10(TR.loc[mask, "capacity_mcm"].values)
            y = np.log10(TR.loc[mask, "footprint_area_km2"].values)
            if len(x) >= 10:
                slope, intercept = np.polyfit(x, y, 1)
                resid = y - (slope * x + intercept)
                stats["loglog_n"]         = int(len(x))
                stats["loglog_alpha"]     = float(intercept)
                stats["loglog_beta"]      = float(slope)
                stats["loglog_resid_rms"] = float(np.sqrt(np.mean(resid ** 2)))

    # Operational fill behavior: A_sat_P95 / A_DEM
    va = data["validation_area"]
    if va is not None:
        d = va.dropna(subset=["sat_over_dem"])
        stats["fill_n"]        = int(len(d))
        stats["fill_median"]   = float(d["sat_over_dem"].median())
        stats["fill_p16"]      = _q(d["sat_over_dem"], 0.16)
        stats["fill_p84"]      = _q(d["sat_over_dem"], 0.84)
        stats["fill_p95"]      = _q(d["sat_over_dem"], 0.95)
        stats["fill_n_above_half"] = int((d["sat_over_dem"] >= 0.5).sum())

    # Residuals of the released power-law curves against the SRTM-derived tables, from the goodness-of-fit table
    gof = data.get("validation_gof")
    if gof is not None and "rms_frac_resid" in gof.columns:
        r2 = gof["r_squared"].dropna()
        stats["fit_n_converged"] = int(len(r2))
        if len(r2) > 0:
            stats["fit_r_squared_median"] = float(r2.median())
        tg = gof[gof["is_trusted"].astype(bool) & gof["rms_frac_resid"].notna()]
        stats["fit_n_trusted_resid"] = int(len(tg))
        if len(tg) > 0:
            rms = tg["rms_frac_resid"]
            stats["fit_rms_frac_resid_median"] = float(rms.median())
            stats["fit_rms_frac_resid_p10"] = _q(rms, 0.10)
            stats["fit_rms_frac_resid_p90"] = _q(rms, 0.90)
            for col in ("abs_frac_resid_full_pool", "median_abs_frac_resid_upper_half",
                        "median_abs_frac_resid_quarter_to_half", "median_abs_frac_resid_tenth_to_quarter",
                        "median_abs_frac_resid_below_tenth", "abs_frac_dev_typical_extent",
                        "rms_frac_resid_upper_volume", "rms_frac_resid_two_segment",
                        "rms_frac_resid_two_segment_upper_volume"):
                if col in tg.columns and tg[col].notna().any():
                    stats[f"fit_{col}_median"] = float(tg[col].median())

    # Sediment budget from delivered yield with no additional delivery ratio. The reported loss is min(uncapped, 1), the trap saturation that caps a dam at 100% of its storage
    if catalog is not None and {"sed_yield_t_ha_yr", "upstream_area_km2",
                                 "capacity_mcm", "construction_year"
                                 }.issubset(catalog.columns):
        m = catalog.dropna(subset=["sed_yield_t_ha_yr", "upstream_area_km2",
                                    "capacity_mcm", "construction_year"])
        m = m[(m["capacity_mcm"] > 0) & (m["upstream_area_km2"] > 0)].copy()
        years = ref_year - m["construction_year"]
        if sediment_sdr is None:
            sdr = 1.0
            stats["sediment_sdr_model"]   = "none_yield_is_delivered"
        else:
            sdr = float(sediment_sdr)
            stats["sediment_sdr_model"]   = "constant"
            stats["sediment_sdr"]         = float(sediment_sdr)
        V_sed = (m["sed_yield_t_ha_yr"] * (m["upstream_area_km2"] * 100.0) * years
                 * sdr / sediment_bulk_density / 1e6)
        frac_uncapped = V_sed / m["capacity_mcm"]
        frac = frac_uncapped.clip(upper=1.0)   # trap saturation at 100%
        stats["sediment_n"]              = int(len(m))
        stats["sediment_bulk_density"]   = float(sediment_bulk_density)
        stats["sediment_loss_median"]    = float(frac.median())
        stats["sediment_loss_p16"]       = _q(frac, 0.16)
        stats["sediment_loss_p84"]       = _q(frac, 0.84)
        stats["sediment_n_loss_above_50pct"] = int((frac > 0.5).sum())
        # Counts the dams whose uncapped budget reaches 100% of capacity
        stats["sediment_n_fully_silted"] = int((frac_uncapped >= 1.0).sum())
        # Counts the dams whose uncapped budget exceeds capacity
        stats["sediment_n_filled_in"]    = int((frac_uncapped > 1.0).sum())

    # LOO validation per anchor
    loo = data["validation_loo"]
    if loo is not None:
        recipes = [("current", "sat_anchor"),
                   ("alt", "loglog_anchor"),
                   ("multi", "multi_anchor")]
        for prefix, label in recipes:
            col = f"{prefix}_log10_V_ratio_at_100pct"
            if col not in loo.columns:
                continue
            r = loo[col].dropna()
            if len(r) == 0:
                continue
            stats[f"loo_{label}_n"]            = int(len(r))
            stats[f"loo_{label}_median_log10"] = float(r.median())
            stats[f"loo_{label}_p16_log10"]    = _q(r, 0.16)
            stats[f"loo_{label}_p84_log10"]    = _q(r, 0.84)
            stats[f"loo_{label}_sigma_log10"]  = (stats[f"loo_{label}_p84_log10"]
                                                   - stats[f"loo_{label}_p16_log10"]) / 2.0
            stats[f"loo_{label}_mae_log10"]    = float(r.abs().mean())
            stats[f"loo_{label}_rmse_log10"]   = float(np.sqrt((r ** 2).mean()))
            stats[f"loo_{label}_within_2x_frac"]  = float((r.abs() <= np.log10(2.0)).mean())
            stats[f"loo_{label}_within_3x_frac"]  = float((r.abs() <= np.log10(3.0)).mean())
            stats[f"loo_{label}_within_10x_frac"] = float((r.abs() <= np.log10(10.0)).mean())
            # Median bias and shares within a factor of two and three at half and tenth pool
            for level in ("050pct", "010pct"):
                col_l = f"{prefix}_log10_V_ratio_at_{level}"
                if col_l in loo.columns:
                    r_l = loo[col_l].dropna()
                    if len(r_l):
                        stats[f"loo_{label}_median_log10_{level}"]   = float(r_l.median())
                        stats[f"loo_{label}_within_2x_frac_{level}"] = float((r_l.abs() <= np.log10(2.0)).mean())
                        stats[f"loo_{label}_within_3x_frac_{level}"] = float((r_l.abs() <= np.log10(3.0)).mean())
            # MedAPE and relRMSE of the selected multi anchor, from e = V_pred/V_SRTM - 1 = 10**(log10 ratio) - 1
            if label == "multi_anchor":
                rel_err = (10.0 ** r) - 1.0
                stats[f"loo_{label}_medape_frac"] = float(rel_err.abs().median())
                stats[f"loo_{label}_relrmse_frac"] = float(
                    np.sqrt((rel_err ** 2).mean()))

    # Supplementary b-clustering diagnostic (silhouette + LOO sigma(delta_b))
    bcd = data.get("b_clustering_diag")
    if bcd is not None and len(bcd) > 0:
        stats["b_cluster_baseline_sigma"] = float(bcd["loo_sigma_baseline"].iloc[0])
        stats["b_cluster_silhouette_max"] = float(bcd["silhouette"].max())
        stats["b_cluster_silhouette_max_k"] = int(bcd.loc[bcd["silhouette"].idxmax(), "k"])
        stats["b_cluster_silhouette_min"] = float(bcd["silhouette"].min())
        loo = bcd.dropna(subset=["loo_sigma_delta_b"])
        if len(loo) > 0:
            best = loo.loc[loo["loo_sigma_delta_b"].idxmin()]
            stats["b_cluster_best_set"]     = str(best["feature_set"])
            stats["b_cluster_best_k"]       = int(best["k"])
            stats["b_cluster_best_sigma"]   = float(best["loo_sigma_delta_b"])
            stats["b_cluster_best_gain_pct"] = float(best["loo_relative_gain_pct"])
            if "loo_r2" in best.index:
                stats["b_cluster_best_loo_r2"] = float(best["loo_r2"])
        # Variance shares of the first two principal components of the clustering features and the rank correlation of b with the first
        for col in ("pc1_var_share", "pc2_var_share", "pc1_spearman_b"):
            if col in bcd.columns:
                stats[f"b_cluster_{col}"] = float(bcd[col].iloc[0])

    return stats


def write_characterization_csv(stats: dict, out_path: Path) -> None:
    rows = [{"statistic": k, "value": round_released_value(k, v)} for k, v in stats.items()]
    df = pd.DataFrame(rows)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)


def read_characterization(csv_path: Path) -> dict[str, Any]:
    """Return the statistics of a domain characterization CSV by name in the order of its rows, each value typed as its text reads."""
    with open(csv_path, newline="", encoding="utf-8") as fh:
        return {row["statistic"]: typed_value(row["value"]) for row in csv.DictReader(fh)}


def write_characterization_json(csv_path: Path) -> Path:
    """Write the JSON twin of a domain characterization CSV beside it, the same statistics with typed values, and return its path."""
    json_path = Path(csv_path).with_suffix(".json")
    json_path.write_text(json.dumps(read_characterization(csv_path), indent=2, allow_nan=False) + "\n")
    return json_path


# Advisory sediment-risk bands on the capped silt fraction
_SILT_RISK_BANDS = (
    (0.10, "low"),        # < 10% capacity lost
    (0.25, "moderate"),   # 10-25%
    (0.50, "high"),       # 25-50%
    (1.00, "severe"),     # 50-100%
)


def _silt_risk_label(frac: float) -> str:
    if not np.isfinite(frac):
        return "unknown"
    if frac >= 1.0:
        return "fully_silted"
    for hi, label in _SILT_RISK_BANDS:
        if frac < hi:
            return label
    return "severe"


def augment_summary_with_sediment_risk(summary, summary_path: Path,
                                       ref_year: int | None,
                                       sediment_sdr: float | None,
                                       sediment_bulk_density: float) -> None:
    """Add ``predicted_silt_fraction`` and ``sediment_risk`` to the summary CSV.

    ``predicted_silt_fraction`` is the trap-saturated (capped at 1.0) ratio of
    deposited sediment volume to catalog capacity. The yield input is
    delivered yield (see ``compute_characterization``), so no additional delivery ratio
    is applied unless ``sediment_sdr`` is given. ``sediment_risk`` is a
    categorical band (``low``/``moderate``/``high``/``severe``/
    ``fully_silted``/``unknown``). Columns are appended in place to
    ``eaves_summary.csv``. The (c, b) parameters live in ``eaves_params.csv``
    and are not touched.
    """
    if summary is None or not summary_path.exists():
        return
    need = {"sed_yield_t_ha_yr", "upstream_area_km2", "capacity_mcm",
            "construction_year"}
    df = pd.read_csv(summary_path)
    if not need.issubset(df.columns):
        return
    if ref_year is None:
        ref_year = datetime.now(UTC).year

    A = df["upstream_area_km2"].to_numpy(dtype=float)
    yld = df["sed_yield_t_ha_yr"].to_numpy(dtype=float)
    cap = df["capacity_mcm"].to_numpy(dtype=float)
    cy = df["construction_year"].to_numpy(dtype=float)
    years = ref_year - cy
    if sediment_sdr is None:
        sdr = np.ones_like(A)
    else:
        sdr = np.full_like(A, float(sediment_sdr))

    with np.errstate(invalid="ignore", divide="ignore"):
        V_sed_mcm = yld * (A * 100.0) * years * sdr / sediment_bulk_density / 1e6
        frac = np.where((cap > 0), V_sed_mcm / cap, np.nan)
    capped = np.clip(frac, 0.0, 1.0)
    risk = [_silt_risk_label(f) for f in frac]

    # Appends the two columns as text, which keeps the serialization of the existing columns
    lines = summary_path.read_text().splitlines()
    if lines and lines[0].endswith(",predicted_silt_fraction,sediment_risk"):
        # A rerun finds both columns at the end of each row and cuts them as text
        lines = [ln.rsplit(",", 2)[0] for ln in lines]
        df = df.drop(columns=["predicted_silt_fraction", "sediment_risk"])
    elif "predicted_silt_fraction" in df.columns or "sediment_risk" in df.columns:
        df = df.drop(columns=[c for c in ("predicted_silt_fraction",
                                          "sediment_risk") if c in df.columns])
        df.to_csv(summary_path, index=False)
        lines = summary_path.read_text().splitlines()
    if len(lines) - 1 != len(df):
        # Rewrites the whole table when the row count does not match
        df["predicted_silt_fraction"] = [
            "" if not np.isfinite(v) else repr(round_released_value("predicted_silt_fraction", float(v))) for v in capped]
        df["sediment_risk"] = risk
        df.to_csv(summary_path, index=False)
        return
    out = [lines[0] + ",predicted_silt_fraction,sediment_risk"]
    for ln, v, r in zip(lines[1:], capped, risk):
        cell = "" if not np.isfinite(v) else repr(round_released_value("predicted_silt_fraction", float(v)))
        out.append(f"{ln},{cell},{r}")
    summary_path.write_text("\n".join(out) + "\n")


# ---- Markdown report ----

def _fmt(x, prec: int = 2) -> str:
    """Compact number format that handles ``None`` / non-numerics."""
    if x is None or (isinstance(x, float) and (np.isnan(x) or not np.isfinite(x))):
        return "n/a"
    if isinstance(x, (int, np.integer)):
        return f"{int(x):,}"
    if isinstance(x, float):
        if abs(x) >= 1000:
            return f"{x:,.0f}"
        if abs(x) >= 10:
            return f"{x:.1f}"
        return f"{x:.{prec}f}"
    return str(x)


def _pctfmt(f) -> str:
    """Format a decimal fraction for display.

    Percentages are stored as decimal fractions (0.29 = 29%, 1.32 = 132%).
    A fraction ``f <= 1.0`` prints as a percentage (``f"{f*100:.0f}%"``). A
    fraction ``f > 1.0`` (> 100%) prints as the multiplicative factor 1 + f (e.g. ``2.3×``).
    """
    if f is None or (isinstance(f, float) and (np.isnan(f) or not np.isfinite(f))):
        return "n/a"
    f = float(f)
    if f <= 1.0:
        pct = f * 100
        # A share short of 100% that would round to it keeps one decimal
        if f < 1.0 and pct >= 99.5:
            return f"{pct:.1f}%"
        return f"{pct:.0f}%"
    return f"{f + 1.0:.1f}×"


def _updown(up: float, down: float) -> str:
    """Upper and lower relative width of a band from decimal fractions, the sign only on a percentage."""
    up_s = _pctfmt(up)
    up_s = f"+{up_s}" if up_s.endswith("%") else up_s
    return f"{up_s} / -{_pctfmt(down)}"


def _relfmt(log10_val, signed: bool = False) -> str:
    """A base-10 log ratio shown in the relative convention (percent / factor).

    Below 100% it prints as a percentage, at or above 100% as a multiplicative
    factor. log10 is the computation space only and is never shown.
    """
    if log10_val is None or (
        isinstance(log10_val, float) and (np.isnan(log10_val) or not np.isfinite(log10_val))
    ):
        return "n/a"
    rel = 10.0 ** float(log10_val) - 1.0
    if signed and 0.0 <= rel <= 1.0:
        return f"+{_pctfmt(rel)}"
    if signed and -1.0 < rel < 0.0:
        return f"−{_pctfmt(abs(rel))}"
    return _pctfmt(rel)


def _bandfmt(sigma_log10: float) -> str:
    """Upper and lower relative width of a one-sigma band given in log10 units."""
    return f"+{(10.0 ** sigma_log10 - 1.0) * 100:.0f}%/-{(1.0 - 10.0 ** -sigma_log10) * 100:.0f}%"


def _yr(x) -> str:
    """Year format: no thousands separator."""
    if x is None or (isinstance(x, float) and (np.isnan(x) or not np.isfinite(x))):
        return "n/a"
    return f"{int(x)}"


def _embed_figure(filename: str, alt: str, caption: str) -> list[str]:
    """Markdown block for an embedded figure if the file exists.

    Returns an empty list when the figure is missing so a partial output set
    just drops figures rather than producing broken image links.
    """
    plot_dir = Path(_cfg.PLOT_DIR)
    fig_path = plot_dir / filename
    if not fig_path.exists():
        return []
    rel = Path("2_results_plots") / filename
    return [
        "",
        f"![{alt}]({rel.as_posix()})",
        "",
        f"_{caption}_",
    ]


def _and_join(items: list[str]) -> str:
    """Joins ``items`` as an English list, the last two with "and"."""
    return (", ".join(items[:-1]) + " and " + items[-1]) if len(items) > 1 else "".join(items)


def _grdl_mean_abs_differences() -> list[tuple[str, float]]:
    """Mean absolute relative volume difference of EAVES from GRDL at equal area, per reference dam.

    The EAVES volume is interpolated at each nonzero GRDL area and compared with
    the GRDL volume at that area as (V_EAVES - V_GRDL) / V_GRDL. Returns an empty list
    when the GRDL curves or the EAV tables are missing.
    """
    try:
        comps = load_grdl_comparisons()
    except (RuntimeError, OSError):
        return []
    out = []
    for comp in comps:
        area = comp["grdl_area_km2"]
        wet = area > 0
        v_eaves = np.interp(area[wet], comp["eaves_area_km2"], comp["eaves_vol_mcm"])
        rel = v_eaves / comp["grdl_vol_mcm"][wet] - 1.0
        out.append((comp["dam_name"], float(np.mean(np.abs(rel)))))
    return out


def _example_dam() -> dict | None:
    """The reservoir with a sonar survey named in the settings, with its name and its predicted silt fraction.

    Returns None when the settings name no such dam. The name and the fraction
    come from ``eaves_summary.csv``, after the sediment columns are appended.
    """
    dam_id = getattr(_cfg, "BATHYMETRY_DAM_ID", None)
    if not dam_id:
        return None
    out = {"id": dam_id, "name": dam_id, "silt_fraction": None, "construction_year": None,
           "survey_year": None, "survey_loss": None}
    path = Path(_cfg.CSV_DIR) / "eaves_summary.csv"
    if path.exists():
        row = pd.read_csv(path).query("dam_id == @dam_id")
        if len(row):
            name = row["dam_name"].iloc[0] if "dam_name" in row.columns else None
            if isinstance(name, str) and name:
                out["name"] = name
            frac = row["predicted_silt_fraction"].iloc[0] if "predicted_silt_fraction" in row.columns else np.nan
            if np.isfinite(frac):
                out["silt_fraction"] = float(frac)
            year = row["construction_year"].iloc[0] if "construction_year" in row.columns else np.nan
            if np.isfinite(year):
                out["construction_year"] = float(year)
    # The survey date as a decimal year and the capacity loss the survey records at the top of the design table
    date = getattr(_cfg, "BATHYMETRY_SURVEY_DATE", None)
    if isinstance(date, str) and len(date) == 7:
        out["survey_year"] = int(date[:4]) + (int(date[5:7]) - 0.5) / 12.0
    bathy = getattr(_cfg, "BATHYMETRY_EAV_CSV", None)
    if bathy and Path(bathy).exists():
        tab = pd.read_csv(bathy)
        if {"volume_m3_design", "volume_m3_integrated_dem"}.issubset(tab.columns) and len(tab):
            top = tab.loc[tab["volume_m3_design"].idxmax()]
            if top["volume_m3_design"] > 0:
                out["survey_loss"] = float(1.0 - top["volume_m3_integrated_dem"] / top["volume_m3_design"])
    return out


def _count_word(n: int) -> str:
    """Spells a small count the way the prose names it."""
    words = ["no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
    return words[n] if 0 <= n < len(words) else str(n)


def render_report_md(stats: dict, generated_at: str) -> str:
    ex = _example_dam()
    exname = ex["name"] if ex else "the example reservoir"
    region = stats.get("region", "unknown")

    L: list[str] = []
    A = L.append

    # ---- Header ----
    A(f"# EAVES domain report: {region}")
    A("")
    A(f"Generated: {generated_at}")
    A("")
    A("Source code: `eaves/` package. This report: `eaves.postprocess.report`.")
    A("")
    A("This document characterizes the reservoir population in the configured "
      "region and explains the EAVES pipeline that produced its "
      "elevation-area-volume (EAV) curves. It covers the physics of the "
      "power-law parameterization, the DEM-based fitting procedure used for "
      "trusted dams, the regionalization procedure used for the remainder, and "
      "the leave-one-out evaluation behind the accuracy figures reported in "
      "the panel set. Every number quoted below is regenerated from the "
      "pipeline outputs at runtime, so figures and prose move together as the "
      "catalog or methodology evolves.")
    A("")

    # ---- Executive summary ----
    A("## Executive summary")
    A("")
    n_total = stats.get("n_dams_with_params")
    n_srtm = stats.get("n_params_source_srtm_derived")
    n_regi = stats.get("n_params_source_regi_multi")
    n_failed = stats.get("n_dams_failed_pipeline")

    A(f"- **Catalog**: {_fmt(n_total)} dams with assigned EAV "
      "parameters.")
    A(f"- **SRTM-derived curves**: {_fmt(n_srtm)} dams "
      "have curves fitted directly to their SRTM flood fills (the trusted "
      "set).")
    A(f"- **Regionalized curves**: {_fmt(n_regi)} dams "
      "without a trusted SRTM-derived fit receive parameters from a "
      "two-component, regionally calibrated empirical procedure. Of these, "
      f"{_fmt(n_failed)} are dams whose wall placement, fill acceptance or "
      "power-law fit fails, regionalized with the topographic features "
      "recorded when processing stopped.")
    if "fill_median" in stats:
        A(f"- **Operational fill behavior**: across the "
          f"{_fmt(stats.get('fill_n'))} trusted dams with a nonzero "
          "95th-percentile satellite-observed water extent, that extent "
          f"reaches a median {_fmt(stats['fill_median']*100)}% of the "
          "DEM-derived full-pool footprint. This is the central fact behind "
          "the choice of the regionalization anchor below.")
    if "sediment_loss_median" in stats:
        if stats.get("sediment_sdr_model") == "none_yield_is_delivered":
            sdr_desc = (
                "delivered sediment yields (the RUSLE-by-SDR product of "
                "[Dash et al. 2025](https://doi.org/10.1016/j.jenvman.2025.127199), so no additional delivery ratio is "
                "applied)")
        else:
            sdr_desc = (f"a sediment delivery ratio of "
                        f"{_fmt(stats.get('sediment_sdr'))}")
        A(f"- **Sediment budget**: assuming {sdr_desc} and a deposited bulk "
          f"density of {_fmt(stats['sediment_bulk_density'])} t m⁻³, "
          "the median predicted capacity loss by "
          f"{_yr(stats.get('reference_year'))} is "
          f"**{_fmt(stats['sediment_loss_median']*100)}%** of the catalog "
          "value (loss capped at 100% by trap saturation, and "
          f"{_fmt(stats.get('sediment_n_fully_silted'))} reservoirs reach "
          "full siltation).")
    if "loo_multi_anchor_within_2x_frac" in stats:
        A("- **Regionalization accuracy (leave-one-out on the training dams, "
          "multi-feature regression)**: "
          f"{_pctfmt(stats['loo_multi_anchor_within_2x_frac'])} of predicted "
          "volumes lie within a factor of two of the SRTM-derived reference "
          f"at full pool, {_pctfmt(stats.get('loo_multi_anchor_within_2x_frac_050pct'))} "
          f"at half pool and {_pctfmt(stats.get('loo_multi_anchor_within_2x_frac_010pct'))} "
          "at tenth pool, with a median bias of "
          f"{_relfmt(stats['loo_multi_anchor_median_log10'], signed=True)} at full pool.")
    elif "loo_loglog_anchor_within_2x_frac" in stats:
        A("- **Regionalization accuracy (leave-one-out on the training dams, "
          "capacity-only regression)**: "
          f"{_pctfmt(stats['loo_loglog_anchor_within_2x_frac'])} of predicted "
          "volumes lie within a factor of two of the SRTM-derived reference "
          "at full pool, with a median bias of "
          f"{_relfmt(stats['loo_loglog_anchor_median_log10'], signed=True)}.")
    A("")

    # ---- Pipeline ----
    A("## Pipeline overview")
    A("")
    A("EAVES uses a dam catalog (coordinates, design capacity, dam length "
      "and height, spillway height, construction year), SRTM GL1 elevation "
      "tiles, the MERIT-Basins river reaches and unit catchments, a country "
      "boundary for selecting the reaches and, optionally, a satellite "
      "water-extent series per dam and a catchment table with upstream "
      "areas and sediment yields. For each dam it executes the following "
      "stages, all coded in the `eaves` package:")
    A("")
    A("1. **Preprocessing** (`eaves.preprocess`): the MERIT-Basins reaches of "
      "the country and of every reach that drains into it are clipped to a "
      "per-dam bounding box, reaches longer than 2 km are subdivided into "
      "equal parts, and each dam takes the nearer endpoint of the nearest "
      "reach part within 1 km of its catalog coordinate as its snapped node.")
    A("2. **DEM clip and reprojection** (`eaves.pipeline.terrain`): the SRTM "
      "tile mosaic is clipped to a per-dam radius and reprojected to the "
      "appropriate UTM zone.")
    A("3. **Dam wall placement and flood fill** (`eaves.pipeline.placement`, "
      "`eaves.pipeline.curves`): a six-stage procedure places a "
      "terrain-aligned wall at the starting point (stage 1), walks upstream "
      "along the valley and retries (stage 2), repeats the upstream search "
      "when the accepted footprint is skewed downstream, displaced or short "
      "of catalog capacity (stage 3), shifts the wall upstream and "
      "downstream along the river for a closer match to catalog capacity "
      "(stage 4), retries with relaxed flow alignment (stage 5) and finally "
      "places a synthetic wall at the starting point (stage 6). The "
      "acceptance checks screen each fill for basin-floor elevation, "
      "vertical extent, downstream leakage and pool position, drainage near "
      "the wall, displacement from the dam, SRTM voids and volume.")
    A("4. **Power-law fit** (`eaves.pipeline.curves`): the area-volume "
      "pairs from the lowest represented elevation to the spillway, or for "
      "capped fills to the level where the volume reaches catalog capacity, "
      "are fitted to V = c A<sup>b</sup> on untransformed volumes by "
      "nonlinear least squares, returning (c, b, R²). For trusted dams the "
      f"released exponent has a lower bound of {_cfg.B_LOWER_BOUND:.0f}, with "
      "c re-solved to keep the full-pool area and volume.")
    A("5. **Quality grading and reliability tagging** "
      "(`eaves.postprocess.regionalization`): each fit gets a grade A to F. The "
      f"trusted subset holds the fits with {_TRUSTED_FILTER_DOC}, which is "
      "stricter than grades A and B alone. The capacity floor of the training dams that "
      "set the regional b is chosen by a sweep of `frac_reliable` against "
      "candidate cutoffs (see Fig. S4).")
    A("6. **Regionalization** (`eaves.postprocess.regionalization`): dams "
      "outside the trusted subset receive (c, b) from the two-component, "
      "regionally calibrated empirical procedure described below.")
    A("7. **Leave-one-out evaluation** (`eaves.postprocess.validation`): "
      "leaving out each training dam (trusted and built after 2000) in turn "
      "gives the accuracy distribution of each regionalization anchor.")
    A("")
    A("Outputs land under `<OUTPUT_DIR>/1_results_csv/` and "
      "`<OUTPUT_DIR>/2_results_plots/`.")
    L.extend(_embed_figure(
        "p1_domain_flowchart.png",
        "Domain map and EAVES pipeline flowchart",
        "Figure 1. (a) Locations of the retained dams, marked by curve "
        "source (SRTM-derived or regionalized), with the dams whose wall "
        "placement, fill acceptance or power-law fit fails marked "
        "separately. The inset enlarges an outlined area in the southwest "
        "of the country. (b) The pipeline combines SRTM topography, the "
        "MERIT-Basins river network and the dam catalog and runs from wall "
        "placement and flood fill to the fitted power law and the per-dam "
        "EAV table.",
    ))
    A("")

    # ---- Physics ----
    A("## Physics of the area-volume relation")
    A("")
    A("Reservoir storage is integrated from a hypsometric area-elevation "
      "function: V(z) = ∫<sub>z_min</sub><sup>z</sup> A(ζ) "
      "dζ. For a valley filled by a transverse dam, the "
      "wetted area at elevation z is set by where the water surface "
      "intersects the surrounding terrain. If the wetted area grows with "
      "depth as A(z) ∝ (z − z_min)<sup>β</sup>, with z_min the "
      "basin-floor elevation and β > 0, integrating area over depth gives "
      "V = c A<sup>b</sup> with b = 1 + 1/β.")
    A("")
    A("Two idealized valley shapes with uniformly sloping beds illustrate "
      "the relation. In a constant-width valley the pool lengthens without "
      "widening as water rises, so this wedge-shaped pool has an area "
      "proportional to depth (β = 1, b = 2). In a V-shaped valley with "
      "straight side slopes, however, the pool widens and lengthens in "
      "proportion to depth, so its area grows with depth squared (β = 2, "
      "b = 1.5). The assumed area-depth relation permits any b > 1, "
      "including b > 2 when 0 < β < 1. An exponent below 1 would make the "
      "mean depth V/A fall as the area grows.")
    A("")
    if "b_median" in stats:
        A(f"In this region's trusted set (n = {_fmt(stats.get('n_trusted'))}), "
          f"the unconstrained exponent b has median **{_fmt(stats['b_median'])}**, "
          f"a P05 to P95 range of [{_fmt(stats.get('b_p05'))}, "
          f"{_fmt(stats.get('b_p95'))}] and a full range of "
          f"[{_fmt(stats.get('b_min'))}, {_fmt(stats.get('b_max'))}]. The "
          "spread that enters the uncertainty bands is taken over the "
          f"training dams, b_σ = {_fmt(stats.get('b_sigma_training'))}.")
        A("")
    _bs = stats.get("b_sigma_training")
    _err_half = 0.5 ** -_bs - 1.0 if _bs is not None else None
    _err_tenth = 0.1 ** -_bs - 1.0 if _bs is not None else None
    A("The coefficient c sets the absolute scale of the curve. Once "
      "b is fixed, anchoring at a known point (A_cap, "
      "V_cap) pins c = V_cap / A_cap<sup>b</sup>. "
      "This back-solve is exact at the anchor, so any uncertainty in b "
      "shows up as V_pred / V_ref = "
      "(A/A_cap)<sup>Δb</sup> at other water levels. A mismatch in b equal "
      f"to the trusted-set spread ({_fmt(_bs)}, the P16 to P84 half-width) "
      f"therefore produces about {_pctfmt(_err_half)} volume error at "
      f"0.5 A_cap and about {_pctfmt(_err_tenth)} at 0.1 A_cap, without the "
      "area-independent terms of the band. For applications that need "
      "detail at low water levels, the released EAV tables in `eav_tables/` "
      "retain the SRTM-derived hypsometry within the reconstructed range, "
      "which the power law smooths over.")
    A("")

    # ---- Domain characterization ----
    A("## Domain characterization")
    A("")

    A("### Catalog demographics")
    A("")
    if "capacity_total_mcm" in stats:
        A(f"The placement pipeline produces a flood fill for "
          f"n = {_fmt(stats.get('n_dams_summary'))} dams. Together with the "
          f"{_fmt(stats.get('n_dams_with_params') - stats.get('n_dams_summary'))} dams "
          "without a fill, which carry enough catalog metadata to be "
          "regionalized, "
          f"**{_fmt(stats.get('n_dams_with_params'))} dams** in total receive "
          "an EAV curve assignment "
          f"({_fmt(stats.get('n_params_source_srtm_derived'))} SRTM-derived, "
          f"{_fmt(stats.get('n_params_source_regi_multi'))} regionalized). "
          f"Aggregate design storage is "
          f"**{_fmt(stats['capacity_total_mcm'])} MCM**. The capacity "
          "distribution is strongly right-skewed: median "
          f"{_fmt(stats['capacity_median_mcm'])} MCM, P05 to P95 = "
          f"[{_fmt(stats['capacity_p05_mcm'])}, "
          f"{_fmt(stats['capacity_p95_mcm'])}] MCM, maximum "
          f"{_fmt(stats['capacity_max_mcm'])} MCM. By size class:")
        A("")
        A("| Class | Count |")
        A("| --- | --- |")
        A(f"| V_cap ≥ 100 MCM | "
          f"{_fmt(stats.get('n_cap_above_100mcm'))} |")
        A(f"| V_cap ≥ 25 MCM | "
          f"{_fmt(stats.get('n_cap_above_25mcm'))} |")
        A(f"| V_cap ≥ 5 MCM | "
          f"{_fmt(stats.get('n_cap_above_5mcm'))} |")
        A(f"| V_cap < 1 MCM | "
          f"{_fmt(stats.get('n_cap_below_1mcm'))} |")
        A("")

    if "construction_year_min" in stats:
        n_unknown = stats.get("n_year_unknown", 0)
        A(f"Construction years span {_yr(stats['construction_year_min'])} to "
          f"{_yr(stats['construction_year_max'])} with the median dam built "
          f"in {_yr(stats['construction_year_median'])}. Era breakdown:")
        A("")
        A("| Era | Count |")
        A("| --- | --- |")
        A(f"| Before 1980 | {_fmt(stats.get('n_pre_1980'))} |")
        A(f"| 1980 to 1999 | {_fmt(stats.get('n_1980_2000'))} |")
        A(f"| 2000 to 2009 | {_fmt(stats.get('n_2000_2010'))} |")
        A(f"| 2010 or later | {_fmt(stats.get('n_post_2010'))} |")
        A(f"| Year unknown | {_fmt(n_unknown)} |")
        A("")
        if n_unknown == 1:
            A("The one dam without a recorded construction year is retained "
              "in every EAV product and carries the `unknown_year` flag. It "
              "is screened for flat water like the dams built before 2000, "
              "and it is left out of the regionalization training set, the "
              "era classes above and the sediment budget below.")
            A("")
        elif n_unknown:
            A(f"The {_fmt(n_unknown)} dams without a recorded construction "
              "year are retained in every EAV product and carry the "
              "`unknown_year` flag. They are screened for flat water like the "
              "dams built before 2000, and they are left out of the "
              "regionalization training set, the era classes above and the "
              "sediment budget below.")
            A("")

    # ---- Operational fill behavior ----
    A("### Operational fill behavior")
    A("")
    if "fill_median" in stats:
        med = stats["fill_median"]
        A(f"For the {_fmt(stats['fill_n'])} trusted dams with a nonzero "
          "95th-percentile satellite-observed water extent, that extent "
          "(A_sat<sup>P95</sup>) is compared with the SRTM-derived full-pool "
          "area A_DEM. The ratio "
          "A_sat<sup>P95</sup> / A_DEM characterizes how "
          "fully a reservoir is operated relative to its design.")
        A("")
        A(f"In this region the median ratio is **{_fmt(med)}**, so the "
          "95th-percentile extent of a typical reservoir reaches only about "
          f"{_fmt(med*100)}% of its full-pool area. The P16 to P84 band "
          f"is [{_fmt(stats['fill_p16'])}, {_fmt(stats['fill_p84'])}]. Only "
          f"{_fmt(stats.get('fill_n_above_half'))} of the "
          f"{_fmt(stats['fill_n'])} dams "
          f"({_fmt(100*stats.get('fill_n_above_half', 0)/max(stats['fill_n'], 1))}%) "
          "reach half the full-pool area at that extent.")
        A("")
        A("This shortfall reflects sparse, episodic inflows in an arid "
          "climate, operational drawdown, seepage and evaporation losses, and "
          "the design margin built into nominal capacities, consistent with "
          "human-managed reservoirs commonly operating well below design "
          "capacity ([Cooley et al. 2021](https://doi.org/10.1038/s41586-021-03262-3))."
          + (f" At {ex['name']}, the SRTM-derived area at the end of the fill "
             "matches the design spillway area (Figure 5b)." if ex else ""))
        A("")
        A("The same shortfall motivates the choice of the regionalization "
          "anchor in this report. An anchor at the 95th-percentile "
          "satellite-observed water area does not match the full-pool area "
          "that catalog capacity refers to, so anchoring "
          "V_cap at A_sat<sup>P95</sup> increases "
          "c by (A_DEM/A_sat)<sup>b</sup>, about "
          f"{_fmt((1.0/med)**stats.get('b_regionalized', stats.get('b_median', 1.5)))}× "
          "at the median in this region. Anchoring against a DEM-derived "
          "A_cap instead keeps both endpoints in the design regime.")
        A("")
    else:
        A("Satellite water-extent statistics unavailable. Run the "
          "validation module to populate this section.")
        A("")

    # ---- Sediment budget ----
    A("### Sediment budget")
    A("")
    if "sediment_loss_median" in stats:
        if stats.get("sediment_sdr_model") == "none_yield_is_delivered":
            sdr_eq = ("The yield input is _delivered_ sediment yield at the "
                      "reservoir inlet. [Dash et al. (2025)](https://doi.org/10.1016/j.jenvman.2025.127199) compute it as "
                      "RUSLE gross erosion times an area-dependent delivery "
                      "ratio (their Eqs. 2 to 4), so "
                      "no additional delivery ratio is applied here "
                      "(a second SDR would double-discount delivery).")
        else:
            sdr_eq = ("A uniform sediment delivery ratio "
                      f"SDR = {_fmt(stats.get('sediment_sdr'))} "
                      "is applied to the yield input.")
        A("A first-order sediment budget is computed from "
          "catchment-specific delivered-yield estimates "
          "(`sed_yield_t_ha_yr`) and "
          "upstream catchment areas, propagated to the reference year "
          f"({_yr(stats['reference_year'])}) with a uniform deposited bulk "
          f"density ρ_sed = "
          f"{_fmt(stats['sediment_bulk_density'])} t m⁻³ "
          "([Morris and Fan 1998](https://www.reservoirsedimentation.com/)). "
          f"{sdr_eq} "
          "The budget holds each catchment's yield constant from the "
          "construction year to the reference year, charges each dam with the "
          "yield of its whole upstream catchment without trapping by dams "
          "further upstream, and assumes complete trapping in the reservoir "
          "and no removal by flushing or dredging. "
          "The accumulated trap volume is V_sed = "
          "Y · A_cat · (t - t_built) "
          "/ ρ_sed, and the predicted fractional "
          "capacity loss is capped at 100% by trap saturation (a reservoir "
          "cannot lose more storage than it holds).")
        A("")
        A(f"Across n = {_fmt(stats['sediment_n'])} dams with all required "
          "inputs, the predicted median capacity loss is "
          f"**{_fmt(stats['sediment_loss_median']*100)}%** of design "
          "capacity, with P16 to P84 = "
          f"[{_fmt(stats['sediment_loss_p16']*100)}%, "
          f"{_fmt(stats['sediment_loss_p84']*100)}%]. "
          f"Of the {_fmt(stats['sediment_n'])} dams, "
          f"{_fmt(stats.get('sediment_n_loss_above_50pct'))} are predicted to "
          "have lost more than half of their design capacity and "
          f"{_fmt(stats.get('sediment_n_fully_silted'))} to be effectively "
          "silted, with a deposited volume that reaches or exceeds design "
          "capacity before the loss is capped. The per-dam capped "
          "fraction and a categorical risk band are released as "
          "`predicted_silt_fraction` and `sediment_risk` in "
          "`eaves_summary.csv`.")
        A("")
        if ex and ex["silt_fraction"] is not None:
            survey = ""
            if (ex["survey_year"] is not None and ex["construction_year"] is not None
                    and ex["survey_loss"] is not None and ex["silt_fraction"] < 1.0):
                yrs_ref = stats["reference_year"] - ex["construction_year"]
                yrs_survey = ex["survey_year"] - ex["construction_year"]
                if yrs_ref > 0 and yrs_survey > 0:
                    at_survey = ex["silt_fraction"] * yrs_survey / yrs_ref
                    survey = (f" and {_pctfmt(at_survey)} at the survey date, against the "
                              f"{_pctfmt(ex['survey_loss'])} loss that the survey of Figure 5 "
                              "records at the top of the design table, so the surveyed loss is "
                              f"{ex['survey_loss'] / at_survey:.1f} times the budget at that date")
            A(f"At {ex['name']} ({ex['id']}), the reservoir with a sonar "
              "survey, the budget predicts a loss of "
              f"{_pctfmt(ex['silt_fraction'])} of design capacity by the "
              f"reference year{survey}.")
        A("The per-dam numbers "
          "are first-order screening indicators, "
          "not site predictions. A region-specific calibration would benefit from "
          "comparative bathymetry on a small panel of reservoirs spanning "
          "the size range.")
        A("")
        A("The EAV curves describe the terrain as SRTM imaged it in February "
          "2000. For dams built after the acquisition this is the valley "
          "before impoundment, so their curves give design storage rather "
          "than present-day storage. For the `pre_srtm` dams with an "
          "SRTM-derived curve it is the valley as it stood in 2000, which may "
          "already hold sediment deposited since construction. The "
          "regionalized curves are anchored to the catalog design capacity. "
          "A sediment-corrected operational curve set can be produced by "
          "subtracting V_sed from the V axis of the released curves (with "
          "the curve truncated below the predicted sediment floor) but is "
          "not the canonical product. For `pre_srtm` dams, however, the "
          "budget integrates deposition from the construction year, so "
          "subtracting V_sed from their SRTM-derived curves counts the "
          "deposit already present in 2000 twice.")
        A("")
    else:
        A("Sedimentation inputs not configured.")
        A("")

    # ---- Geometry distribution ----
    A("### Geometry distribution and regionalization features")
    A("")
    if "b_median" in stats:
        A(f"On the trusted subset (n = {_fmt(stats.get('n_trusted'))}), the "
          f"unconstrained exponent b has median **{_fmt(stats['b_median'])}**, "
          "which compares with b = 1.5 for an idealized V-shaped valley. "
          "These empirical fits, however, emphasize the upper storage levels "
          "and need not represent the geometry throughout the basin.")
        A("")
    if "loglog_alpha" in stats:
        A("The empirical area-capacity relation, fit on the training dams "
          "as log₁₀ A_cap [km²] = "
          "α + β_A log₁₀ V_cap [MCM], "
          f"yields α = {_fmt(stats['loglog_alpha'])} and "
          f"β_A = {_fmt(stats['loglog_beta'])} with a residual RMS "
          f"of a factor of {_fmt(10**stats['loglog_resid_rms'])} over "
          f"n = {_fmt(stats['loglog_n'])} training dams. The fitted β_A is "
          "close to the geometric expectation of 2/3 for "
          "cone-like valley fills. The validation uses this relation as "
          "the capacity-only comparison anchor.")
        A("")

    # ---- SRTM-derived curves ----
    A("## SRTM-derived curves")
    A("")
    A("For each dam that survives placement and quality gating, the curve "
      f"is fit directly from the SRTM-clipped flood fill. Levels {_cfg.BIN_Z:g} m "
      "apart run from the lowest represented elevation to the spillway or, "
      "for capped fills, to the level where the integrated volume reaches "
      "catalog capacity. At each level z the wetted area A(z) is the number "
      "of footprint cells at or below z times the cell area, and at the "
      "final capped level the area is interpolated linearly between the "
      "adjacent levels. The volume V(z) = ∫ A dz follows by cumulative "
      "trapezoidal integration, and the resulting (A, V) pairs are fit "
      "to V = c A<sup>b</sup>. The procedure is purely geometric and uses no "
      "satellite or in-situ data. Curves that pass the trusted-set filter "
      f"({_TRUSTED_FILTER_DOC}) are the reference against which all other "
      "claims in this report are calibrated.")
    A("")
    if "fit_rms_frac_resid_median" in stats:
        typical = ""
        if "fill_median" in stats and "fit_abs_frac_dev_typical_extent_median" in stats:
            typical = (f" At {_pctfmt(stats['fill_median'])} of the full-pool area, the median "
                       "satellite 95th-percentile water extent, the median absolute difference is "
                       f"{_pctfmt(stats['fit_abs_frac_dev_typical_extent_median'])}.")
        A(f"The {_fmt(stats.get('fit_n_converged'))} converged power-law fits have a median R² of "
          f"{_fmt(stats.get('fit_r_squared_median'), 4)}. Fitting untransformed volumes emphasizes "
          "the upper reservoir levels, so a high R² can mask larger relative errors at low storage. "
          "The absolute fractional volume residual |c A<sup>b</sup> − V| / V at each fitted level, "
          "released per dam in `validation/goodness_of_fit.csv`, counts every level equally and is "
          "therefore sensitive to large relative differences at low volumes. Among the "
          f"{_fmt(stats.get('fit_n_trusted_resid'))} trusted dams its per-dam root-mean-square has a "
          f"median of {_fmt(stats['fit_rms_frac_resid_median'])}, with 10th to 90th percentiles of "
          f"[{_fmt(stats.get('fit_rms_frac_resid_p10'))}, {_fmt(stats.get('fit_rms_frac_resid_p90'))}]. "
          "Compared with the SRTM-derived volumes, the median absolute difference is "
          f"{_pctfmt(stats.get('fit_abs_frac_resid_full_pool_median'))} at full pool. Median absolute "
          "differences, calculated within each dam and then across dams, are "
          f"{_pctfmt(stats.get('fit_median_abs_frac_resid_upper_half_median'))} over the upper half of "
          f"the full-pool area and {_pctfmt(stats.get('fit_median_abs_frac_resid_below_tenth_median'))} "
          "below a tenth." + typical)
        A("")
        if "fit_rms_frac_resid_two_segment_median" in stats:
            A("A two-segment straight-line fit in log space, with the break chosen per dam by the "
              "log-space sum of squares, is the alternative to the single power law. It reduces the "
              "median root-mean-square fractional residual across the trusted dams from "
              f"{_fmt(stats['fit_rms_frac_resid_median'])} to "
              f"{_fmt(stats['fit_rms_frac_resid_two_segment_median'])}. At storage levels of at least "
              "10% of the maximum SRTM-derived volume, however, the median is "
              f"{_fmt(stats.get('fit_rms_frac_resid_upper_volume_median'))} for the power law and "
              f"{_fmt(stats.get('fit_rms_frac_resid_two_segment_upper_volume_median'))} for the "
              "two-segment fit, so the gain lies at the low stages that the tabulated EAV curves of "
              "`eav_tables/` describe directly.")
            A("")
    grdl_diffs = _grdl_mean_abs_differences()
    if grdl_diffs:
        grdl_agreement = (
            "differ from the EAVES curves in volume at equal area by a mean absolute "
            + _and_join([f"{100.0 * d:.0f}% ({name})" for name, d in grdl_diffs])
            + " over the area range that GRDL represents (Figure 6)"
        )
    else:
        grdl_agreement = "are compared with the EAVES curves at equal area (Figure 6)"
    checks = []
    if ex:
        checks.append(
            f"the sonar survey of {ex['name']} gives a spillway-level "
            "capacity well below the design capacity, consistent with storage "
            "lost to sedimentation since construction. The survey describes "
            "the present reservoir, whereas the SRTM-derived curve represents "
            "the valley before the dam was built. The design table agrees "
            "with the SRTM-derived curve within a few percent in area and "
            "volume at the design spillway level (Figure 5)")
    if grdl_diffs or getattr(_cfg, "GRDL_DIR", None):
        n_grdl = f"{_count_word(len(grdl_diffs))} GRDL curves" if grdl_diffs else "the GRDL curves"
        checks.append(
            f"{n_grdl}, which a deep-learning model reconstructs from the "
            "surrounding SRTM terrain with reservoir boundaries set mainly by "
            "Landsat-observed water extents "
            "([Hao et al. 2024](https://doi.org/10.1029/2023WR035781)), "
            f"{grdl_agreement}")
    if checks:
        n = len(checks)
        A(f"{_count_word(n).capitalize()} comparison{'s' if n > 1 else ''} "
          f"with reference datasets check{'' if n > 1 else 's'} the "
          "consistency of the EAVES curves rather than validating them "
          "directly. "
          + " ".join(f"({'i' * (k + 1)}) {c[0].upper()}{c[1:]}." for k, c in enumerate(checks))
          + f" {'These comparisons assess' if n > 1 else 'This comparison assesses'} "
          "consistency rather than volumetric accuracy.")
    L.extend(_embed_figure(
        "p2_placement.png",
        "Dam wall placement examples",
        "Figure 2. Examples of the six-stage dam-wall placement procedure. "
        "(a) Direct placement at the catalog coordinate (stage 1). (b) Wall "
        "shifted along the river to improve the volume match to catalog "
        "capacity (stage 4). (c) Synthetic wall at the catalog coordinate "
        "after unsuccessful terrain-based placement (stage 6). Red stars "
        "mark the catalog dam locations, white triangles the snapped "
        "MERIT-Basins nodes and amber lines the accepted walls. Blue "
        "polygons show the 8-connected flooded basins over hill-shaded SRTM "
        "terrain, each filled to the spillway elevation or to catalog "
        "capacity, whichever it reaches first.",
    ))
    L.extend(_embed_figure(
        "p3_baish_example.png",
        f"EAVES outputs at {exname}",
        f"Figure 3. EAVES outputs at {exname} and the distribution of fitted "
        "exponents. (a) SRTM elevation with the inundated footprint and the "
        "dam location. (b) SRTM-derived area-volume pairs and the fitted "
        "power law on log-log axes, annotated with c, b, R² on untransformed "
        "volumes and the root-mean-square fractional residual. (c) "
        "Distribution of the unconstrained exponents b across the trusted "
        "dams, with the trusted-set median, the example dam and the lower "
        f"bound b = {_cfg.B_LOWER_BOUND:.0f} of the released exponent marked.",
    ))
    A("")

    # ---- Regionalization ----
    A("## Regionalization")
    A("")
    A("Dams without a trusted SRTM-derived fit receive (c, b) from a "
      "two-component, regionally calibrated empirical procedure, which "
      "pairs a regional exponent b with a predicted full-pool area that "
      "fixes c. Both components are _trained on the region's "
      "own training dams (trusted fits built after the SRTM acquisition)_, "
      "so the method itself is portable but its "
      "coefficients are region-specific.")
    A("")
    A("_Choice of b._ The selected procedure assigns every regionalized dam "
      f"the regional median **b = {_fmt(stats.get('b_regionalized', stats.get('b_median')))}**, "
      "the median over the training dams at or above the minimum training "
      f"capacity of {_fmt(stats.get('reliability_threshold_mcm'), 1)} MCM "
      "with complete morphometric features. On this catalog, neither the "
      "regressions nor the clustering below improves enough on the regional "
      "median to replace it.")
    A("")
    _rho = stats.get("b_feature_rho_max")
    _rho_str = _fmt(_rho) if _rho is not None else "n/a"
    _rho_pct = f"{100.0 * _rho * _rho:.0f}" if _rho is not None else "n/a"
    A("_1. Multivariate regression (linear and random forest)._ "
      "A linear regression and a random forest of b on `valley_ratio`, "
      "`channel_slope`, `mean_catchment_slope`, and `dam_height_m` are "
      "evaluated by leave-one-out cross-validation on the training dams at "
      "or above the minimum training capacity with complete features. "
      "The selection gate requires "
      "R²_LOO ≥ 0.25 for a regression to replace the "
      "median. Both models fall below the gate. No single feature explains "
      f"more than about {_rho_pct}% of the variance in b "
      f"(Spearman |ρ| ≤ {_rho_str} over the {_fmt(stats.get('n_regression_basis'), 0)} dams "
      "of the regression basis), and the features are partly redundant, so "
      "combining them yields no improvement over the constant. The regional "
      "median is therefore retained.")
    A("")
    # Reads the silhouette and LOO numbers of b_clustering_diagnostic.csv
    gain = stats.get("b_cluster_best_gain_pct")
    gain_str = f"{gain:.0f}" if gain is not None else "n/a"

    A("_2. Morphological clustering with a per-cluster median._ "
      "K-means clustering in standardized log space on six morphometric "
      "features (valley-width ratio, channel slope, mean catchment slope, "
      "dam height, spillway height and dam length) sweeps k = 2 to 12, with "
      "the results released in `validation/b_clustering_diagnostic.csv`. "
      f"The best configuration (k = {stats.get('b_cluster_best_k', 'n/a')}) "
      f"lowers the leave-one-out σ(Δb) by {gain_str}%, from "
      f"{_fmt(stats.get('b_cluster_baseline_sigma'))} to "
      f"{_fmt(stats.get('b_cluster_best_sigma'))}, but its leave-one-out R² "
      f"reaches only {_fmt(stats.get('b_cluster_best_loo_r2'))}, below the "
      "0.25 gate applied to the regressions (Fig. S1b). Mean silhouette "
      f"coefficients of {_fmt(stats.get('b_cluster_silhouette_min'))} to "
      f"{_fmt(stats.get('b_cluster_silhouette_max'))} stay below the "
      "conventional 0.50 reasonable-structure threshold, so the training "
      "dams do not split into well-separated groups, although b varies "
      "gradually along the first principal component (Spearman ρ = "
      f"{_fmt(stats.get('b_cluster_pc1_spearman_b'))}, Fig. S1c).")
    A("")
    A("_Practical implication._ "
      "No clustering configuration reaches the 0.25 gate that a regression "
      "must clear, so the selected procedure keeps the **regional median**, "
      "and the `b_sigma` column of `validation/v_uncertainty.csv` "
      "quantifies the remaining spread of b.")
    A("")
    A("_Regression branch as a region-portable fallback._ "
      "Where the better of the two regressions on a region's morphometric "
      "features reaches an R²_LOO of at least 0.25 "
      "(`eaves.postprocess.regionalization.run_regionalization`), its "
      "predicted b values replace the regional median, and the dams keep "
      "the `regi_multi` source label like every regionalized dam.")
    A("")
    A("_Choice of c._ The selected procedure anchors each regionalized "
      "dam at the predicted full-pool area A_cap and back-"
      "solves c = V_cap / A_cap<sup>b</sup>. A linear regression in log "
      "space, fitted to the SRTM-derived full-pool areas of the training "
      "dams, predicts A_cap from seven features:")
    A("")
    A("log A_cap = α_0 + Σ_(i=1…7) α_i log X_i")
    A("")
    A("with X_i ∈ { `capacity_mcm`, `dam_height_m`, "
      "`spillway_height_m`, `valley_ratio`, `channel_slope`, "
      "`mean_catchment_slope`, `upstream_area_km2` }. Missing features are "
      "replaced with their training-set medians before prediction.")
    A("")
    A("The validation module evaluates two alternative anchors for the "
      "comparison below: (i) the "
      "satellite 95th-percentile water area, and (ii) a capacity-only "
      "log₁₀ A_cap = α + β_A log₁₀ V_cap "
      "regression. The multi-feature regression is the selected anchor.")
    A("")
    if "fill_median" in stats:
        med = stats["fill_median"]
        A("Because the 95th-percentile extent of a typical reservoir reaches "
          f"only about {_fmt(med*100)}% of its full-pool area, the satellite anchor "
          "captures an _operational_ area rather than the design area that "
          "the catalog V_cap refers to. Mixing a design "
          "volume with an operational area inflates c by "
          f"~ (1/{_fmt(med)})<sup>b</sup> ≈ "
          f"{_fmt((1.0/med)**stats.get('b_regionalized', stats.get('b_median', 1.5)))}× at the median. "
          "Both DEM-trained anchors stay in the design regime by "
          "construction.")
        A("")

    # ---- Validation ----
    A("## Leave-one-out evaluation of regionalization")
    A("")
    A("The leave-one-out evaluation tests how well the regionalization "
      "reconstructs the SRTM-derived curves of the training dams. It "
      "assesses reconstruction of those curves rather than accuracy against "
      "measured storage. Each training dam is left out in turn. The anchors "
      "are refitted and b is recalculated as the median exponent of the "
      "remaining training dams, and the predicted volumes are compared with "
      "the omitted dam's SRTM-derived power-law curve at full, half and "
      "tenth pool (100%, 50% and 10% of its recovered full-pool area "
      "A_DEM). Errors are computed in log₁₀ ratio space and reported "
      "below in the relative convention (a percentage, or a multiplicative "
      "factor for larger values). The table below gives the full-pool "
      "scores and the shares within a factor of two and three at half and "
      "tenth pool, and Figure 4 shows all three levels. The full per-dam "
      "table lives in `<CSV_DIR>/validation/regionalization_loo.csv`.")
    A("")
    if "loo_multi_anchor_within_2x_frac" in stats:
        A("| Metric | Satellite 95th-percentile extent | Capacity-only "
          "regression | Multi-feature regression (selected) |")
        A("| --- | --- | --- | --- |")
        A(f"| n | {_fmt(stats.get('loo_sat_anchor_n'))} | "
          f"{_fmt(stats.get('loo_loglog_anchor_n'))} | "
          f"{_fmt(stats.get('loo_multi_anchor_n'))} |")
        A(f"| Median bias | "
          f"{_relfmt(stats.get('loo_sat_anchor_median_log10'), signed=True)} | "
          f"{_relfmt(stats['loo_loglog_anchor_median_log10'], signed=True)} | "
          f"**{_relfmt(stats['loo_multi_anchor_median_log10'], signed=True)}** |")
        A(f"| Median absolute percentage error | "
          f"n/a | n/a | "
          f"**{_pctfmt(stats.get('loo_multi_anchor_medape_frac'))}** |")
        A(f"| Relative RMSE | "
          f"n/a | n/a | "
          f"**{_pctfmt(stats.get('loo_multi_anchor_relrmse_frac'))}** |")
        A(f"| Within 2× | "
          f"{_pctfmt(stats.get('loo_sat_anchor_within_2x_frac'))} | "
          f"{_pctfmt(stats['loo_loglog_anchor_within_2x_frac'])} | "
          f"**{_pctfmt(stats['loo_multi_anchor_within_2x_frac'])}** |")
        A(f"| Within 3× | "
          f"{_pctfmt(stats.get('loo_sat_anchor_within_3x_frac'))} | "
          f"{_pctfmt(stats['loo_loglog_anchor_within_3x_frac'])} | "
          f"**{_pctfmt(stats['loo_multi_anchor_within_3x_frac'])}** |")
        A(f"| Within 10× | "
          f"{_pctfmt(stats.get('loo_sat_anchor_within_10x_frac'))} | "
          f"{_pctfmt(stats['loo_loglog_anchor_within_10x_frac'])} | "
          f"**{_pctfmt(stats['loo_multi_anchor_within_10x_frac'])}** |")
        for lvl, lname in (("050pct", "half pool"), ("010pct", "tenth pool")):
            for fac in ("2", "3"):
                A(f"| Within {fac}× at {lname} | "
                  f"{_pctfmt(stats.get(f'loo_sat_anchor_within_{fac}x_frac_{lvl}'))} | "
                  f"{_pctfmt(stats.get(f'loo_loglog_anchor_within_{fac}x_frac_{lvl}'))} | "
                  f"**{_pctfmt(stats.get(f'loo_multi_anchor_within_{fac}x_frac_{lvl}'))}** |")
        A("")
        A("'Within n×' means |log₁₀(V_pred / "
          "V_SRTM)| ≤ log₁₀(n), i.e. the predicted "
          "volume sits between V_SRTM / n and "
          "V_SRTM · n.")
        A("")
        A("The selected multi-feature regression has the tightest spread of the "
          f"three, a 1σ of {_relfmt(stats.get('loo_multi_anchor_sigma_log10'))} "
          f"against {_relfmt(stats.get('loo_loglog_anchor_sigma_log10'))} for the "
          "capacity-only regression and "
          f"{_relfmt(stats.get('loo_sat_anchor_sigma_log10'))} for the satellite "
          "anchor. Both DEM-trained anchors stay in the design regime that "
          "the catalog V_cap refers to, and the satellite anchor carries "
          "the operational bias.")
        L.extend(_embed_figure(
            "p4_regionalization_validation.png",
            "Regionalization accuracy panel",
            "Figure 4. Leave-one-out evaluation of the regionalization "
            "procedure on the training dams at three fill levels. (a to c) "
            "Predicted versus SRTM-derived reference volume at full, half and "
            "tenth pool (the recovered full-pool area A_DEM, half and a tenth "
            "of it) for the multi-feature regression, with the 1:1 line and "
            "the ±factor-2 and ±factor-3 bands. The inset names the level and "
            "gives the share within a factor of two, the median bias and the "
            "median absolute error. (d) Signed prediction error in "
            "log₁₀(V_pred/V_SRTM) at the three levels, with the per-dam "
            "values, the median and the P16 to P84 interval, beside the "
            "median regionalized uncertainty band half-width (±1σ) at the "
            "same level. (e) Binned median error against catalog capacity at "
            "the three levels, with the number of dams in each bin. Dashed "
            "lines in (d) and (e) mark factor-of-two limits, and dotted lines "
            "in (e) mark factor-of-three limits.",
        ))
        A("")

    A("The leave-one-out test measures the agreement of the procedure with "
      "_the SRTM-derived curves_ of the training dams, and Figure 4 reports "
      "the accuracy on that sample. The training dams are larger than the "
      "regionalized dams, so the scores are less representative of the "
      "smallest regionalized reservoirs. Full-pool agreement is partly "
      "anchored by construction, because each regionalized curve passes "
      "through catalog capacity at its predicted full-pool area and most "
      "reference fills stop at the same capacity. The procedure, predictors "
      "and training threshold are also selected on the same dataset, so the "
      "reported scores may be optimistic.")
    L.extend(_embed_figure(
        "p5_comparison.png",
        f"{exname} comparison and domain-wide volume ratio",
        f"Figure 5. {exname} comparison and domain-wide volume ratio. "
        f"(a) Area-volume curves at {exname} from the SRTM-derived fill, "
        "the sonar survey and the documented design table. Because catalog "
        "capacity limits the fill, the comparison with the design table "
        "evaluates the reconstructed curve shape and surface area. "
        f"(b) Elevation-area curves at {exname} from the same three sources, "
        "without vertical alignment. SRTM represents the valley before dam "
        "construction, whereas the sonar survey represents the reservoir at "
        "the survey date, so the comparison cannot separate reconstruction "
        "error from changes in reservoir geometry. The dashed line marks "
        "the top of dead storage, the lowest level of the design and "
        "survey tables, below which only the SRTM-derived curve continues. "
        "(c) Distribution of the maximum SRTM-derived volume divided by "
        "catalog capacity (V_SRTM/V_cap) across the dams with a flood fill. "
        "Catalog capacity bounds the ratio at 1, which the capped fills "
        "reach. Shading marks the nested volume-ratio windows [0.5, 2.0] and "
        "[0.3, 5.0] of grades A and B, whose counts differ from the grade "
        "counts because grading also considers fit quality and reservoir "
        "dimensions.",
    ))
    grdl_names = _and_join([name.capitalize() for name in _cfg.GRDL_NAME_MAP])
    L.extend(_embed_figure(
        "p6_grdl_comparison.png",
        "Comparison of SRTM-derived and GRDL reservoir curves",
        "Figure 6. Comparison of SRTM-derived and GRDL reservoir curves. "
        "GRDL reconstructs bathymetry from the surrounding terrain with a "
        "deep-learning model and takes its reservoir boundaries mainly from "
        "Landsat-observed water extents. Because GRDL also uses SRTM and is "
        "itself a reconstruction, the comparison assesses consistency "
        "between reconstructions. (a) Area-volume curves from EAVES and GRDL "
        f"for {grdl_names}, one row per reservoir. (b) Depth-area curves for "
        "the same reservoirs, with depth measured from the lowest level of "
        "each curve.",
    ))
    A("")

    # ---- Uncertainty propagation ----
    A("## Uncertainty on volume predictions")
    A("")
    # Reads the band terms of v_uncertainty.csv
    vunc_path = Path(_cfg.CSV_DIR) / "validation" / "v_uncertainty.csv"
    vu = pd.read_csv(vunc_path) if vunc_path.exists() else None
    floor_srtm = floor_regi = "n/a"
    if vu is not None and {"source", "sigma_log_vcap", "sigma_acap_term"}.issubset(vu.columns):
        floor_srtm = _bandfmt(float(vu["sigma_log_vcap"].median()))
        regi = vu[vu["source"] != "srtm_derived"]
        if len(regi) > 0:
            floor_regi = _bandfmt(float(np.hypot(regi["sigma_log_vcap"], regi["sigma_acap_term"]).median()))
    A("The volume band combines up to three terms. The training-set spread "
      "of the exponent b "
      f"(b_σ ≈ {_fmt(stats.get('b_sigma_training'))}, the "
      "dimensionless P16 to P84 half-width, identical "
      "for every dam) sets the geometric term. It is released per dam as the `b_sigma` column of "
      "`validation/v_uncertainty.csv` (the near-identical "
      "`b_cluster_baseline_sigma` in `domain_characterization.csv` is the "
      "separate clustering-baseline diagnostic). Because every curve is pinned through the "
      "catalog anchor (A_cap, V_cap), the resulting "
      "V band widens away from full pool. The catalog capacity on which "
      "every curve is anchored has an unknown error of its own, so every "
      "curve also carries the area-independent catalog-capacity term. "
      "Estimated from the spread of log₁₀(V_SRTM/V_cap) over the uncapped "
      "training fills, this term floors the SRTM-derived band at about "
      f"{floor_srtm} even at the anchor. Regionalized curves add the predicted-"
      f"area term and floor at about {floor_regi} (see `validation/v_uncertainty.csv`).")
    A("")
    A("The band is σ(log₁₀V) = √((b · σ_logAcap)² + (b_σ · log₁₀(A/A_cap))² "
      "+ σ_logVcap²), with A_cap = (V_cap/c)<sup>1/b</sup> the implicit "
      "anchor and the predicted-area term set to zero for SRTM-derived "
      "curves. A user wanting a confidence band on V should read the "
      "combined per-dam band from `validation/v_uncertainty.csv` or "
      "evaluate this expression with its `sigma_log_acap`, `b_sigma` and "
      "`sigma_log_vcap` columns. The geometric term alone, "
      "V_lo,hi = V_cap (A/A_cap)<sup>b ± b_σ</sup>, understates the band "
      "near full pool, where the area-independent anchor terms dominate. "
      "The band quantifies parameterization uncertainty only. It excludes "
      "errors in the satellite water extent, the DEM vertical error assessed "
      "by the Monte-Carlo of `validation/dem_error_montecarlo.csv` and the "
      "power-law fit residuals of `validation/goodness_of_fit.csv`.")
    A("")
    A("The full per-dam table at three reference fill levels is written by "
      "`eaves.postprocess.uncertainty` to "
      "`<CSV_DIR>/validation/v_uncertainty.csv`, where the regionalized "
      "curves carry wider bands than the SRTM-derived ones. Median band "
      "widths by curve source for this region:")
    A("")
    if vu is not None and "source" in vu.columns:
        A("| Fill level | SRTM-derived | Regionalized |")
        A("| --- | --- | --- |")
        groups = (vu[vu["source"] == "srtm_derived"], vu[vu["source"] != "srtm_derived"])
        for label_h, key in [("Half pool (A/A_cap=0.50)",     "half_pool"),
                             ("Quarter pool (A/A_cap=0.25)",  "quarter_pool"),
                             ("Tenth pool (A/A_cap=0.10)",    "tenth_pool")]:
            cells = [_updown(float(g[f"V_frac_up_{key}"].median()), float(g[f"V_frac_down_{key}"].median()))
                     if len(g) else "n/a" for g in groups]
            A(f"| {label_h} | {cells[0]} | {cells[1]} |")
    A("")

    # ---- Generalization ----
    A("## Generalization to other regions")
    A("")
    A("The EAVES method transfers to other regions, but its application to "
      "a new region is not automatic. Pieces that carry over:")
    A("")
    A("- The structure of the placement cascade, the flood fill, the "
      "power-law fit and the leave-one-out validation carries over "
      "unchanged. The constants of the placement and acceptance checks, "
      "however, are fixed values set on SRTM and the Saudi catalog and need "
      "re-evaluation for a new region (below).")
    A("- The regionalization procedure (regional median b and multi-feature "
      "regression for the A_cap anchor) is trained only on the region's own "
      "training dams.")
    A("- The leave-one-out evaluation gives an accuracy estimate of the "
      "regionalization in each region.")
    A("")
    A("Region-specific parameters, re-fit by the pipeline on the region's "
      "own training dams and never inherited from another region:")
    A("")
    A("- The multi-feature regression coefficients of the full-pool area "
      "anchor. These reflect the region's terrain and design conventions "
      "and do not transfer between regions.")
    A("- The regional median b (or, where a regression for b clears the "
      "0.25 gate, the regression coefficients).")
    A("- The training cut of the regional exponent, chosen from a fresh "
      "capacity-threshold sweep.")
    A("")
    A("The constants of the placement and acceptance checks and the "
      "quality-grade thresholds (`r_squared`, `vol_ratio`, `n_pixels`) are "
      "fixed values set on SRTM and the Saudi catalog. They depend on the "
      "noise of the DEM and of the catalog, so they should be re-evaluated "
      "for a new region, for example with the sensitivity sweep of the "
      "placement and acceptance constants and the DEM vertical-error "
      "Monte-Carlo.")
    A("")
    A("The design-area anchor is the appropriate default in any arid or "
      "hyper-arid region where reservoirs do not routinely fill to "
      "spillway. In humid catchments with regular drawdown-to-spillway "
      "cycles, the satellite signal may become competitive and is worth "
      "re-evaluating per region.")
    A("")
    A("To run EAVES on a new region, give the paths of the dam catalog, "
      "the DEM and the river network in a regional settings JSON, then run "
      "`./run_all.sh region/<country>/<country>.json` from the project "
      "root. The script "
      "chains the pipeline, validation, uncertainty, panels and report in the correct "
      "order so every figure and every number in this document is "
      "regenerated with regionally-fit values.")
    A("")

    # ---- Limitations ----
    A("## Limitations and open issues")
    A("")
    A("- **Independent validation is limited by the available bathymetry.** "
      f"The {exname} sonar survey records the reservoir at the survey date, "
      "whereas its SRTM-derived curve represents the terrain at the SRTM "
      "acquisition, so the comparison cannot separate reconstruction error "
      "from changes in reservoir geometry. GRDL also uses SRTM inputs, so "
      "agreement between the two products does not independently establish "
      "storage accuracy. Broader validation requires additional bathymetric "
      "references and information on changes between acquisition dates.")
    A("- **Catalog capacity and spillway height carry their own errors.** "
      "Capacity sets the endpoint of capped SRTM-derived fills and "
      "influences both the volume and the predicted-area anchors of "
      "regionalized curves, and no correction is applied for its errors. "
      "The catalog-capacity term of the uncertainty band (about "
      f"{floor_srtm}) represents the disagreement between uncapped "
      "SRTM-derived and catalog volumes, which combines catalog and "
      "reconstruction errors, and does not correct individual capacity "
      "errors. Spillway-height errors can alter the fill ceiling and are "
      "not separately propagated.")
    A("- **Sediment loss is a first-order estimate.** The budget uses "
      "delivered catchment yields from a regional model, with no further "
      "delivery ratio, and a uniform bulk density. Comparative bathymetry "
      "on a small panel of reservoirs would allow a local calibration.")
    A("- **SRTM resolution and voids limit the smallest reservoirs.** SRTM "
      "resolution and elevation uncertainty limit how well the reservoir "
      "geometry is resolved, particularly for small reservoirs. Narrow "
      "valleys, small footprints and DEM voids can prevent a reconstruction "
      "from meeting the trusted-set criteria, in which case the regionalized "
      "coefficients are used. Radar penetration into very dry sediment may "
      "also bias the recorded elevations. The DEM vertical-error Monte-Carlo "
      "(`validation/dem_error_montecarlo.csv`) assesses how spatially "
      "correlated random elevation errors affect the recovered volumes, but "
      "does not model this bias.")
    A("- **One exponent per reservoir.** The single power law summarizes each "
      "reservoir with one exponent, smoothing variations in its area-volume "
      "relation. Fitting untransformed volumes emphasizes the higher storage "
      "levels, so relative errors are larger at low stages (per-dam residuals "
      "in `validation/goodness_of_fit.csv`, the two-segment alternative in "
      "the SRTM-derived curves section above). For reservoirs with an "
      "SRTM-derived fit, the tabulated EAV curves of `eav_tables/` describe "
      "the hypsometry directly within their reconstructed range and offer "
      "more low-stage detail than the power law. Partial curves exclude the "
      "storage below the water surface recorded by SRTM.")
    A("- **Per-dam b uncertainty is population-level, not individual.** "
      "`validation/v_uncertainty.csv` and "
      "`domain_characterization.csv` carry the 1σ uncertainty on "
      f"b as a single region-level number (b_σ ≈ {_fmt(stats.get('b_sigma_training'))}, dimensionless, from the training set), identical for every "
      "dam regardless of source. A per-dam narrowing of that interval would "
      "require repeated DEM realizations or an ensemble of independent DEMs.")
    A("")

    # ---- Supplementary figures ----
    A("## Supplementary figures")
    pc1_share = stats.get("b_cluster_pc1_var_share")
    pc1_share_str = _pctfmt(pc1_share) if pc1_share is not None else "n/a"
    pc2_share = stats.get("b_cluster_pc2_var_share")
    pc2_share_str = _pctfmt(pc2_share) if pc2_share is not None else "n/a"
    pc1_rho_str = _fmt(stats.get("b_cluster_pc1_spearman_b"))
    L.extend(_embed_figure(
        "s1_b_clustering_silhouette.png",
        "Supplementary: K-means clustering diagnostic for b",
        "Figure S1. K-means clustering diagnostic on the training-set "
        "dams in log-transformed morphometric feature space. "
        "(a) Mean silhouette coefficient versus number of clusters k "
        "for the six morphometric features. It remains below the "
        "conventional 0.50 reasonable-structure threshold for every "
        f"k. The k = {stats.get('b_cluster_silhouette_max_k', 'n/a')} peak at "
        f"{_fmt(stats.get('b_cluster_silhouette_max'))} reflects a cut "
        "across the dominant gradient of panel c, not two morphological "
        "types. (b) Leave-"
        "one-out σ(Δb) for a per-cluster-median predictor "
        "of b versus the global-median baseline (dashed). The best "
        f"configuration (k = {stats.get('b_cluster_best_k', 'n/a')}) lowers σ(Δb) "
        f"by {gain_str}%, while its leave-one-out R² stays at "
        f"{_fmt(stats.get('b_cluster_best_loo_r2'))}, below the 0.25 gate. "
        "(c) The training dams in the plane of "
        "the first two principal components of the standardized "
        "log-transformed features, colored by b, with marker shapes for "
        "the clusters at the best k of panel b. The first two components "
        f"carry {pc1_share_str} and {pc2_share_str} of the variance, and b "
        "varies along the first "
        f"(Spearman ρ = {pc1_rho_str}), so the dams form "
        "one continuous cloud along which b changes gradually.",
    ))
    L.extend(_embed_figure(
        "s2_uncertainty_band.png",
        "Supplementary: Per-dam volume uncertainty band",
        "Figure S2. Per-dam volume uncertainty band. "
        f"(a) Worked example on {exname} dam. The ±b_σ band shows the "
        "geometric term alone. It is forced through the catalog full-pool "
        "anchor (red star) and widens at lower water levels. (b) The two "
        "σ(log₁₀V) tiers versus normalized area, "
        "shown as the upper bound of the band. The SRTM-derived tier is "
        f"floored by the catalog-capacity term ({floor_srtm} at the anchor) "
        "and widens with the geometric b_σ term away from full pool, while "
        "the regionalized tier adds the area-independent "
        f"anchor terms and floors near {floor_regi}. The regional typical "
        "operational fill level (the median 95th-percentile observed extent "
        "as a fraction of the SRTM-derived full-pool area) is overlaid as a "
        "vertical dashed line, and a marker on "
        "the SRTM-derived curve gives the band at that level, so the V "
        "uncertainty at the fill level at which most reservoirs in this "
        "region operate can be read off directly.",
    ))
    A("")

    # ---- Files produced ----
    A("## Files produced")
    A("")
    A("| Path | Content |")
    A("| --- | --- |")
    A("| `0_check_dams/<dam_id>_{srtm,regi}.png` | Per-dam flood map of "
      "every dam with a flood fill, suffixed `srtm` for a direct SRTM fit "
      "or `regi` for regionalized parameters. |")
    A("| `1_results_csv/eaves_summary.csv` | One row per dam of "
      "`eaves_params.csv`. Per-dam pipeline outputs: "
      "placement metadata, fit results, quality flags, external attributes. "
      "A dam without a flood fill has empty fill and fit cells. |")
    A("| `1_results_csv/eaves_params.csv` | Lean per-dam parameter table: "
      "(c, b) plus identification and the assignment source. Six "
      "columns. The 1σ uncertainty on b is a single region-level "
      "scalar stored in `validation/v_uncertainty.csv` and "
      "`domain_characterization.csv`, not duplicated per row. |")
    A("| `1_results_csv/failed_dams.csv` | Dams failing wall placement, fill "
      "acceptance, or the power-law fit, with failure reason. |")
    A("| `1_results_csv/threshold_analysis.csv` | Capacity-threshold "
      "sweep behind the training cut of the regional exponent. |")
    A("| `1_results_csv/eav_tables/<dam_id>_eav.csv` | Elevation, depth, "
      "area and volume table per dam with a flood fill, with elevation and "
      "depth in m, area in m² and volume in m³. |")
    A("| `1_results_csv/validation/regionalization_loo.csv` | Per-anchor "
      "leave-one-out residuals, every training dam. |")
    A("| `1_results_csv/validation/dem_vs_sat_area.csv` | A_DEM "
      "vs A_sat<sup>P95</sup> paired data. |")
    A("| `1_results_csv/validation/b_clustering_diagnostic.csv` | Silhouette, "
      "LOO σ(Δb) and LOO R² per (feature-set, k), with the variance share "
      "of the first principal component of the features and the Spearman "
      "correlation of b with it, backs the supplementary figure S1. |")
    A("| `1_results_csv/validation/v_uncertainty.csv` | Per-dam combined "
      "volume band (geometric, catalog-capacity and, for regionalized "
      "curves, predicted-area terms) at half, quarter, and tenth pool, "
      "backs the supplementary figure S2. |")
    A("| `1_results_csv/validation/goodness_of_fit.csv` | Per-dam "
      "fractional volume residuals of the power-law fit (area-to-volume "
      "direction), their medians by fill level, the departure at the "
      "typical satellite extent and the residual of the two-segment "
      "alternative. |")
    A("| `1_results_csv/validation/acap_regression_diagnostics.csv` | "
      "VIF, condition number, incremental and drop-one leave-one-out "
      "diagnostics of the seven-feature A_cap regression. |")
    A("| `1_results_csv/validation/dem_error_montecarlo.csv` | Per-dam "
      "volume spread under SRTM vertical-error perturbations, backs the "
      "supplementary figure S3. |")
    A("| `1_results_csv/validation/sensitivity_sweep.csv` | Trusted-set "
      "stability under ±20% and ±30% perturbations of five placement and "
      "acceptance constants, backs the supplementary figure S5. |")
    A("| `1_results_csv/domain_characterization.csv` | Flat table of every "
      "statistic referenced in this report. |")
    A("| `1_results_csv/domain_characterization.json` | The same "
      "statistics as `domain_characterization.csv` with typed values. |")
    A("| `2_results_plots/p1_*.{png,pdf}` to `p6_*.{png,pdf}` | Panel "
      "figures. Each panel is written as both a 300-dpi PNG (embedded in "
      "this report) and a vector PDF. |")
    A("| `2_results_plots/s1_b_clustering_silhouette.{png,pdf}` | "
      "Supplementary figure S1: K-means clustering diagnostic for b, "
      "with the training dams in the plane of the first two principal "
      "components. |")
    A("| `2_results_plots/s2_uncertainty_band.{png,pdf}` | Supplementary "
      "figure S2: per-dam volume uncertainty band, with a "
      f"worked example on {exname} and the two-tier σ(log₁₀V) "
      "curves versus normalized area. |")
    A("| `2_results_plots/s3_dem_error.{png,pdf}` | Supplementary "
      "figure S3: DEM vertical-error Monte-Carlo volume spread by "
      "capacity class. |")
    A("| `2_results_plots/s4_threshold_analysis.{png,pdf}` | Supplementary "
      "figure S4: capacity-threshold sweep behind the training cut of the "
      "regional exponent (R² against reservoir size by quality grade, and "
      "the fraction of dams clearing the combined reliability gates "
      "against the candidate cutoff). |")
    A("| `2_results_plots/s5_sensitivity.{png,pdf}` | Supplementary "
      "figure S5: sensitivity of the trusted set to the placement and "
      "acceptance constants. |")
    A("| `report.md` | This document. |")
    A("")

    return "\n".join(L)


# ---- Entry points ----

def run(settings_path: str | None = None,
        ref_year: int | None = None,
        sediment_sdr: float | None = None,
        sediment_bulk_density: float = 1.3) -> dict:
    """Programmatic entry: compute characterization, write the CSV with its JSON twin and the Markdown.

    ``sediment_sdr=None`` (the default) applies no delivery ratio, because
    the ``sed_yield_t_ha_yr`` input is delivered yield (see
    ``compute_characterization``). Pass a float to apply a constant SDR for regions whose yield
    input is gross erosion.
    """
    if settings_path is not None:
        load_settings(settings_path)

    data = _load_inputs()
    stats = compute_characterization(
        data, ref_year=ref_year,
        sediment_sdr=sediment_sdr,
        sediment_bulk_density=sediment_bulk_density,
    )

    if ref_year is None:
        ref_year = stats.get("reference_year")
    augment_summary_with_sediment_risk(
        data.get("summary"),
        Path(_cfg.CSV_DIR) / "eaves_summary.csv",
        ref_year=ref_year,
        sediment_sdr=sediment_sdr,
        sediment_bulk_density=sediment_bulk_density,
    )

    csv_path = Path(_cfg.CSV_DIR) / "domain_characterization.csv"
    write_characterization_csv(stats, csv_path)
    json_path = write_characterization_json(csv_path)

    generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    md = render_report_md(stats, generated_at)
    md_path = Path(_cfg.OUTPUT_DIR) / "report.md"
    md_path.write_text(md)

    print(f"wrote {csv_path}")
    print(f"wrote {json_path}")
    print(f"wrote {md_path}")
    return stats


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--settings", required=True,
                   help="Path to region settings JSON (e.g. region/ksa/ksa.json).")
    p.add_argument("--ref-year", type=int, default=None,
                   help="Reference year for sediment accumulation "
                   "(default: current UTC year).")
    p.add_argument("--sediment-sdr", type=float, default=None,
                   help="Constant sediment delivery ratio. Default (None) "
                   "applies no SDR because the yield input is delivered "
                   "yield. Pass a float only if the input is gross erosion.")
    p.add_argument("--sediment-bulk-density", type=float, default=1.3,
                   help="Deposited sediment bulk density in t/m³ "
                   "(default 1.3).")
    args = p.parse_args(argv)
    run(settings_path=args.settings,
        ref_year=args.ref_year,
        sediment_sdr=args.sediment_sdr,
        sediment_bulk_density=args.sediment_bulk_density)


if __name__ == "__main__":
    main()
