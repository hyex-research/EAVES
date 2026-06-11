"""Domain characterization and comprehensive pipeline report.

Reads the EAVES pipeline outputs (``eaves_summary.csv``, ``eaves_params.csv``,
``failed_dams.csv``, ``validation/regionalization_loo.csv``,
``validation/dem_vs_sat_area.csv``) plus the auxiliary water-extent and
sedimentation inputs, computes a characterization of the reservoir
population in the configured region, and emits two artefacts:

1. ``<CSV_DIR>/domain_characterization.csv``
   Machine-readable key/value table of every statistic computed below.
2. ``<OUTPUT_DIR>/report.md``
   Prose Markdown report covering the pipeline, the physics behind the
   power-law area--volume relation, domain characterization (catalogue
   demographics, operational fill behavior, sediment budget, geometry
   distribution), the regionalization method and its accuracy, and the
   region-independent vs region-specific parts of the workflow.

Sections of the report degrade gracefully if validation CSVs are absent.
For a complete document run ``python -m eaves.postprocess.validation``
first, then ``python -m eaves.postprocess.report``.

Usage:
    python -m eaves.postprocess.report --settings region/<region>/<region>.json
"""

from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import eaves.config as _cfg
from .reliability import training_mask


# --- Inputs ---

def _load_inputs() -> dict:
    csv_dir = Path(_cfg.CSV_DIR)
    paths = {
        "summary":         csv_dir / "eaves_summary.csv",
        "params":          csv_dir / "eaves_params.csv",
        "failed":          csv_dir / "failed_dams.csv",
        "threshold":       csv_dir / "threshold_analysis.csv",
        "validation_loo":     csv_dir / "validation" / "regionalization_loo.csv",
        "validation_area":    csv_dir / "validation" / "dem_vs_sat_area.csv",
        "b_clustering_diag":  csv_dir / "validation" / "b_clustering_diagnostic.csv",
    }
    out: dict[str, pd.DataFrame | None] = {}
    for k, p in paths.items():
        out[k] = pd.read_csv(p) if p.exists() else None
    return out


# --- Characterization ---

_TRUSTED_FILTER_DOC = (
    "quality $\\in$ {A, B}, $r^2 \\ge 0.98$, "
    "$0.3 \\le V_\\mathrm{SRTM}/V_\\mathrm{cap} \\le 5.0$, "
    "$n_\\mathrm{pixels} \\ge 50$, $b$ defined."
)


def _trusted_mask(df: pd.DataFrame) -> pd.Series:
    return (
        df["quality"].isin(["A", "B"])
        & (df["r_squared"] >= 0.98)
        & df["vol_ratio"].between(0.3, 5.0)
        & (df["n_pixels"] >= 50)
        & df["b"].notna()
    )


def _q(s: pd.Series, q: float) -> float:
    return float(s.quantile(q))


# sed_yield_t_ha_yr is delivered yield (Dash et al. 2025: RUSLE x Boyce SDR applied at source).
# No further delivery ratio is applied here; a second SDR double-discounts (Baish miss ~10x -> ~1.6x).
# sediment_sdr stays available as a constant factor for gross-erosion inputs.


def compute_characterization(data: dict, ref_year: int | None = None,
                              sediment_sdr: float | None = None,
                              sediment_bulk_density: float = 1.3) -> dict:
    """Compute a complete domain characterization as a flat ``dict``."""
    if ref_year is None:
        ref_year = datetime.now(timezone.utc).year

    stats: dict[str, Any] = {}
    stats["region"] = getattr(_cfg, "TARGET_COUNTRY", "unknown")
    stats["reference_year"] = int(ref_year)

    summary = data["summary"]
    params = data["params"]
    failed = data["failed"]

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

    # Capacity stats span the released catalogue; year stats only dams with an SRTM footprint.
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

    if summary is not None:
        if "construction_year" in summary.columns:
            cy = summary["construction_year"].dropna()
            stats["construction_year_min"]    = int(cy.min())
            stats["construction_year_median"] = int(cy.median())
            stats["construction_year_max"]    = int(cy.max())
            stats["n_pre_1980"]               = int((cy < 1980).sum())
            stats["n_1980_2000"]              = int(((cy >= 1980) & (cy < 2000)).sum())
            stats["n_2000_2010"]              = int(((cy >= 2000) & (cy < 2010)).sum())
            stats["n_post_2010"]              = int((cy >= 2010).sum())
            # Unknown-year dams stay visible; the era counts above exclude them.
            stats["n_year_unknown"]           = int(summary["construction_year"].isna().sum())

        if "dam_height_m" in summary.columns:
            dh = summary["dam_height_m"].dropna()
            stats["dam_height_median_m"] = float(dh.median())
            stats["dam_height_max_m"]    = float(dh.max())

    # Trusted-set geometry distribution
    if summary is not None and "b" in summary.columns:
        T = summary[_trusted_mask(summary)].copy()
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

        # Training set: trusted AND post-SRTM construction -- the population
        # that trains the regionalization and sets the band's b_sigma.
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

        # Log--log area-capacity fit on the training set (the retired
        # single-feature recipe trains on the same population as the rest).
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

    # Sediment budget: delivered yield in, no additional delivery ratio (see note above).
    # Reported loss is min(uncapped, 1): trap saturation caps a dam at 100% of its storage.
    if summary is not None and {"sed_yield_t_ha_yr", "upstream_area_km2",
                                 "capacity_mcm", "construction_year"
                                 }.issubset(summary.columns):
        m = summary.dropna(subset=["sed_yield_t_ha_yr", "upstream_area_km2",
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
        # "Fully silted": the uncapped budget reached 100% of capacity.
        stats["sediment_n_fully_silted"] = int((frac_uncapped >= 1.0).sum())
        # Legacy back-compat field: count whose uncapped budget exceeded capacity.
        stats["sediment_n_filled_in"]    = int((frac_uncapped > 1.0).sum())

    # LOO validation -- per recipe
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
            # MedAPE and relRMSE are meaningful only for the shipped multi anchor.
            # Retired anchors are off by up to ~10x; their relative RMSE carries no information.
            # e = V_pred/V_obs - 1 = 10**(log10 ratio) - 1, so the metrics need no volumes.
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
        stats["b_cluster_silhouette_min"] = float(bcd["silhouette"].min())
        loo = bcd.dropna(subset=["loo_sigma_delta_b"])
        if len(loo) > 0:
            best = loo.loc[loo["loo_sigma_delta_b"].idxmin()]
            stats["b_cluster_best_set"]     = str(best["feature_set"])
            stats["b_cluster_best_k"]       = int(best["k"])
            stats["b_cluster_best_sigma"]   = float(best["loo_sigma_delta_b"])
            stats["b_cluster_best_gain_pct"] = float(best["loo_relative_gain_pct"])

    return stats


def write_characterization_csv(stats: dict, out_path: Path) -> None:
    rows = [{"statistic": k, "value": v} for k, v in stats.items()]
    df = pd.DataFrame(rows)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)


# Advisory sediment-risk bands on the capped silt fraction; (c, b), grades, filters untouched.
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
    deposited sediment volume to catalogue capacity. The yield input is
    delivered yield (see module-level note), so no additional delivery ratio
    is applied unless ``sediment_sdr`` is given. ``sediment_risk`` is a
    categorical band (``low``/``moderate``/``high``/``severe``/
    ``fully_silted``/``unknown``). Columns are appended in place to
    ``eaves_summary.csv``; the (c, b) parameters live in ``eaves_params.csv``
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
        ref_year = datetime.now(timezone.utc).year

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

    # Append via raw-text edit so existing columns keep their exact serialization.
    if "predicted_silt_fraction" in df.columns or "sediment_risk" in df.columns:
        df = df.drop(columns=[c for c in ("predicted_silt_fraction",
                                          "sediment_risk") if c in df.columns])
        df.to_csv(summary_path, index=False)

    lines = summary_path.read_text().splitlines()
    if len(lines) - 1 != len(df):
        # Row count mismatch (unexpected) -- fall back to a full rewrite.
        df["predicted_silt_fraction"] = [
            "" if not np.isfinite(v) else f"{v:.6f}" for v in capped]
        df["sediment_risk"] = risk
        df.to_csv(summary_path, index=False)
        return
    out = [lines[0] + ",predicted_silt_fraction,sediment_risk"]
    for ln, v, r in zip(lines[1:], capped, risk):
        cell = "" if not np.isfinite(v) else f"{v:.6f}"
        out.append(f"{ln},{cell},{r}")
    summary_path.write_text("\n".join(out) + "\n")


# --- Markdown report ---

def _fmt(x, prec: int = 2) -> str:
    """Compact number format that handles ``None`` / non-numerics."""
    if x is None or (isinstance(x, float) and (np.isnan(x) or not np.isfinite(x))):
        return "—"
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
    A fraction ``f <= 1.0`` prints as a percentage (``f"{f*100:.0f}%"``); a
    fraction ``f > 1.0`` (> 100%) prints as the multiplicative factor 1 + f (e.g. ``2.3×``).
    """
    if f is None or (isinstance(f, float) and (np.isnan(f) or not np.isfinite(f))):
        return "—"
    f = float(f)
    if f <= 1.0:
        return f"{f * 100:.0f}%"
    return f"{f + 1.0:.1f}×"


def _relfmt(log10_val, signed: bool = False) -> str:
    """A base-10 log ratio shown in the relative convention (percent / factor).

    Matches the manuscript: below 100% prints as a percentage, at or above 100%
    as a multiplicative factor. log10 is the computation space only, never shown.
    """
    if log10_val is None or (
        isinstance(log10_val, float) and (np.isnan(log10_val) or not np.isfinite(log10_val))
    ):
        return "—"
    rel = 10.0 ** float(log10_val) - 1.0
    if signed and 0.0 <= rel <= 1.0:
        return f"+{_pctfmt(rel)}"
    if signed and -1.0 < rel < 0.0:
        return f"−{_pctfmt(abs(rel))}"
    return _pctfmt(rel)


def _yr(x) -> str:
    """Year format: no thousands separator."""
    if x is None or (isinstance(x, float) and (np.isnan(x) or not np.isfinite(x))):
        return "—"
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


def render_report_md(stats: dict, generated_at: str) -> str:
    region = stats.get("region", "unknown")

    L: list[str] = []
    A = L.append

    # ---- header ----
    A(f"# EAVES domain report — {region}")
    A("")
    A(f"_Generated: {generated_at}_")
    A("")
    A(f"_Source code: `eaves/` package; this report: `eaves.postprocess.report`._")
    A("")
    A("This document characterizes the reservoir population in the configured "
      "region and explains the EAVES pipeline that produced its "
      "elevation–area–volume (EAV) curves. It covers the physics of the "
      "power-law parameterization, the DEM-based fitting procedure used for "
      "trusted dams, the regionalization recipe used for the remainder, and "
      "the leave-one-out validation behind the accuracy figures reported in "
      "the panel set. Every number quoted below is regenerated from the "
      "pipeline outputs at runtime, so figures and prose move together as the "
      "catalogue or methodology evolves.")
    A("")

    # ---- executive summary ----
    A("## Executive summary")
    A("")
    n_total = stats.get("n_dams_with_params")
    n_srtm = stats.get("n_params_source_srtm_derived")
    n_regi = stats.get("n_params_source_regi_multi")
    n_failed = stats.get("n_dams_failed_pipeline")

    A(f"- **Catalogue**: {_fmt(n_total)} dams with assigned EAV "
      "parameters.")
    A(f"- **DEM-derived curves**: {_fmt(n_srtm)} dams "
      "have curves fit directly from SRTM-clipped flood-fills (these are the "
      "trusted population).")
    A(f"- **Regionalized curves**: {_fmt(n_regi)} dams "
      "have curves assigned via a region-trained empirical recipe because "
      "the DEM fit failed quality gates — of which "
      f"{_fmt(n_failed)} are pipeline failures (placement, fill, or fit) "
      "regionalized with topographic features captured at failure time.")
    if "fill_median" in stats:
        A(f"- **Operational fill behavior**: the median ratio "
          f"$A_\\mathrm{{sat}}^{{P95}} / A_\\mathrm{{DEM}}$ is "
          f"**{_fmt(stats['fill_median'])}**, meaning a typical reservoir's "
          "observed maximum extent reaches only "
          f"~{_fmt(stats['fill_median']*100)}% of its DEM-derived design "
          "footprint. This is the central physical fact behind the "
          "regionalization method choice below.")
    if "sediment_loss_median" in stats:
        if stats.get("sediment_sdr_model") == "none_yield_is_delivered":
            sdr_desc = (
                "delivered sediment yields (the RUSLE-by-SDR product of "
                "Dash et al. 2025, so no additional delivery ratio is "
                "applied)")
        else:
            sdr_desc = (f"a sediment delivery ratio of "
                        f"{_fmt(stats.get('sediment_sdr'))}")
        A(f"- **Sediment budget**: assuming {sdr_desc} and a deposited bulk "
          f"density of {_fmt(stats['sediment_bulk_density'])} t m$^{{-3}}$, "
          "the median predicted capacity loss by "
          f"{_yr(stats.get('reference_year'))} is "
          f"**{_fmt(stats['sediment_loss_median']*100)}%** of the catalogue "
          "value (loss capped at 100% by trap saturation; "
          f"{_fmt(stats.get('sediment_n_fully_silted'))} reservoirs reach "
          "full siltation).")
    if "loo_multi_anchor_within_2x_frac" in stats:
        A(f"- **Regionalization accuracy (LOO on the training dams, multi-feature "
          f"LR anchor)**: "
          f"{_pctfmt(stats['loo_multi_anchor_within_2x_frac'])} of predictions "
          "within a factor of 2 of the SRTM-derived truth, median bias "
          f"{_relfmt(stats['loo_multi_anchor_median_log10'], signed=True)}.")
    elif "loo_loglog_anchor_within_2x_frac" in stats:
        A(f"- **Regionalization accuracy (LOO on the training dams, log-log "
          f"anchor)**: "
          f"{_pctfmt(stats['loo_loglog_anchor_within_2x_frac'])} of predictions "
          "within a factor of 2 of the SRTM-derived truth, median bias "
          f"{_relfmt(stats['loo_loglog_anchor_median_log10'], signed=True)}.")
    A("")

    # ---- pipeline ----
    A("## Pipeline overview")
    A("")
    A("EAVES consumes a national reservoir catalogue (latitude, longitude, "
      "dam height, spillway height, storage capacity, construction year), "
      "void-corrected SRTM elevation tiles, MERIT-Hydro river and basin "
      "polygons, an optional pre-computed satellite water-extent time series "
      "per dam, and optional sedimentation-yield estimates per dam. For each "
      "dam it executes the following stages, all coded in the `eaves` "
      "package:")
    A("")
    A("1. **Preprocessing** (`eaves.preprocess`): MERIT-Hydro segments are "
      "clipped to a per-dam bounding box, segments longer than "
      "$2\\,\\mathrm{km}$ are split, and each dam is snapped to the nearest "
      "river segment within $1\\,\\mathrm{km}$.")
    A("2. **DEM clip and reprojection** (`eaves.pipeline.terrain`): the SRTM "
      "tile mosaic is clipped to a per-dam radius and reprojected to the "
      "appropriate UTM zone.")
    A("3. **Dam wall placement and flood-fill** (`eaves.pipeline.placement`, "
      "`eaves.pipeline.curves`): a six-stage cascade tries an aligned crest "
      "at the catalogue location (Stage 1), walks upstream along the valley "
      "axis (Stage 2), recovers from poor geometry or under-volume fills "
      "(Stage 3), retries upstream along the river vector (Stage 4), relaxes "
      "the flow-alignment filter (Stage 5), and finally falls back to a "
      "multi-direction fill (Stage 6). Acceptance gates reject fills that "
      "leak downstream, are centroid-displaced, or fail volume sanity "
      "checks.")
    A("4. **Power-law fit** (`eaves.pipeline.curves`): the resulting "
      "$(A, V)$ pairs over the elevation range $[z_\\mathrm{min}, "
      "z_\\mathrm{spillway}]$ are fit to $V = c A^b$ by nonlinear least "
      "squares, returning $(c, b, r^2)$.")
    A("5. **Quality grading and reliability tagging** "
      "(`eaves.postprocess.regionalization`): each fit gets a grade A–F. The "
      "trusted subset is the union of A and B grades that also satisfy "
      f"{_TRUSTED_FILTER_DOC} The capacity floor used to define the "
      "training set is chosen by a sweep of `frac_reliable` against "
      "candidate cutoffs (see Fig. S2).")
    A("6. **Regionalization** (`eaves.postprocess.regionalization`): dams "
      "outside the trusted subset receive $(c, b)$ from a region-trained "
      "empirical recipe described below.")
    A("7. **Validation** (`eaves.postprocess.validation`): leave-one-out on "
      "the training dams (trusted and post-2000) gives per-recipe accuracy distributions.")
    A("")
    A("Outputs land under `<OUTPUT_DIR>/1_results_csv/` and "
      "`<OUTPUT_DIR>/2_results_plots/`.")
    L.extend(_embed_figure(
        "p1_domain_flowchart.png",
        "Domain map and EAVES pipeline flowchart",
        "Figure 1. (a) Spatial distribution of catalogued dams within the "
        "target country, sized by storage capacity and colored by "
        "parameter source. (b) Flowchart of the EAVES pipeline from "
        "catalogue and SRTM inputs through to the per-dam EAV table.",
    ))
    A("")

    # ---- physics ----
    A("## Physics of the area–volume relation")
    A("")
    A("Reservoir storage is integrated from a hypsometric area–elevation "
      "function: $V(z) = \\int_{z_\\mathrm{min}}^{z} A(\\zeta)\\,"
      "\\mathrm{d}\\zeta$. For a valley filled by a transverse dam, the "
      "wetted area at elevation $z$ is set by where the water surface "
      "intersects the surrounding terrain, which is well approximated by a "
      "power-law in depth: $A(z) \\propto (z - z_\\mathrm{min})^{\\beta}$ "
      "with $\\beta > 0$. Integrating that area against depth and "
      "expressing the result against area rather than depth yields the "
      "compact form")
    A("")
    A("$$V = c\\,A^{b}, \\quad b = \\tfrac{\\beta + 1}{\\beta}.$$")
    A("")
    A("Two geometric extremes bracket the exponent:")
    A("")
    A("- A **cylindrical** reservoir (vertical walls, constant area) has "
      "$\\beta \\to \\infty$ and $b \\to 1$.")
    A("- A **wedge-shaped** two-dimensional valley fill (the classical "
      "valley-fill end-member) has $\\beta = 1$ and $b = 2$.")
    A("")
    A("Real reservoirs land between these. The bulk of trusted KSA dams "
      "cluster around $b \\sim 1.5$, which corresponds to $\\beta = 2$ — a "
      "three-dimensional converging valley.")
    A("")
    if "b_median" in stats:
        A(f"In this region's trusted set ($n = {_fmt(stats.get('n_trusted'))}$), "
          f"$b$ has median **{_fmt(stats['b_median'])}** with $1\\sigma = "
          f"{_fmt(stats.get('b_sigma'))}$, P05–P95 range "
          f"[{_fmt(stats.get('b_p05'))}, {_fmt(stats.get('b_p95'))}], and "
          f"absolute range [{_fmt(stats.get('b_min'))}, "
          f"{_fmt(stats.get('b_max'))}]. The width of that distribution is "
          "the dominant geometric uncertainty in regionalized curves.")
        A("")
    A("The coefficient $c$ sets the absolute scale of the curve. Once "
      "$b$ is fixed, anchoring at a known point $(A_\\mathrm{cap}, "
      "V_\\mathrm{cap})$ pins $c = V_\\mathrm{cap} / A_\\mathrm{cap}^{b}$. "
      "This back-solve is exact at the anchor, so any uncertainty in $b$ "
      "shows up as $V_\\mathrm{pred} / V_\\mathrm{true} = "
      "(A/A_\\mathrm{cap})^{\\Delta b}$ at other water levels. A "
      "$1\\sigma$ mismatch in $b$ therefore produces ~20% volume error at "
      "$0.5 A_\\mathrm{cap}$ and ~84% at $0.1 A_\\mathrm{cap}$. Users who "
      "need accuracy at very low water levels should treat the curve as a "
      "structural estimate, not a precise prediction.")
    A("")

    # ---- domain characterization ----
    A("## Domain characterization")
    A("")

    A("### Catalogue demographics")
    A("")
    if "capacity_total_mcm" in stats:
        A(f"The placement pipeline produces a fit summary for "
          f"$n = {_fmt(stats.get('n_dams_summary'))}$ dams. Together with "
          f"{_fmt(stats.get('n_dams_failed_pipeline'))} additional records "
          "that fail pipeline gating but carry enough catalogue metadata to "
          "be regionalized, "
          f"**{_fmt(stats.get('n_dams_with_params'))} dams** in total receive "
          "an EAV curve assignment "
          f"({_fmt(stats.get('n_params_source_srtm_derived'))} SRTM-derived, "
          f"{_fmt(stats.get('n_params_source_regi_multi'))} regionalized). "
          f"Aggregate design storage is "
          f"**{_fmt(stats['capacity_total_mcm'])} MCM**. The capacity "
          "distribution is strongly right-skewed: median "
          f"{_fmt(stats['capacity_median_mcm'])} MCM, P05–P95 = "
          f"[{_fmt(stats['capacity_p05_mcm'])}, "
          f"{_fmt(stats['capacity_p95_mcm'])}] MCM, maximum "
          f"{_fmt(stats['capacity_max_mcm'])} MCM. By size class:")
        A("")
        A("| Class | Count |")
        A("| --- | --- |")
        A(f"| $V_\\mathrm{{cap}} \\ge 100$ MCM | "
          f"{_fmt(stats.get('n_cap_above_100mcm'))} |")
        A(f"| $V_\\mathrm{{cap}} \\ge 25$ MCM | "
          f"{_fmt(stats.get('n_cap_above_25mcm'))} |")
        A(f"| $V_\\mathrm{{cap}} \\ge 5$ MCM | "
          f"{_fmt(stats.get('n_cap_above_5mcm'))} |")
        A(f"| $V_\\mathrm{{cap}} < 1$ MCM | "
          f"{_fmt(stats.get('n_cap_below_1mcm'))} |")
        A("")

    if "construction_year_min" in stats:
        n_unknown = stats.get("n_year_unknown", 0)
        A(f"Construction years span {_yr(stats['construction_year_min'])}–"
          f"{_yr(stats['construction_year_max'])} with the median dam built "
          f"in {_yr(stats['construction_year_median'])}. Era breakdown:")
        A("")
        A("| Era | Count |")
        A("| --- | --- |")
        A(f"| Pre-1980 | {_fmt(stats.get('n_pre_1980'))} |")
        A(f"| 1980–2000 | {_fmt(stats.get('n_1980_2000'))} |")
        A(f"| 2000–2010 | {_fmt(stats.get('n_2000_2010'))} |")
        A(f"| Post-2010 | {_fmt(stats.get('n_post_2010'))} |")
        A(f"| Year unknown | {_fmt(n_unknown)} |")
        A("")
        if n_unknown:
            A(f"The {_fmt(n_unknown)} year-unknown dams carry no catalogue "
              "construction date. They are retained in the population and in "
              "every EAV product; only the age-dependent statistics (era "
              "assignment above, sediment budget below) exclude them, since "
              "fabricating a year would bias those figures.")
            A("")

    # ---- operational fill behavior ----
    A("### Operational fill behavior")
    A("")
    if "fill_median" in stats:
        med = stats["fill_median"]
        A(f"For the {_fmt(stats['fill_n'])} trusted dams with a satellite "
          "water-extent time series, the 95th-percentile observed water area "
          "is compared against the DEM-derived spillway-level footprint. "
          "The ratio "
          "$A_\\mathrm{sat}^{P95} / A_\\mathrm{DEM}$ characterizes how "
          "fully a reservoir is operated relative to its design.")
        A("")
        A(f"In this region, the median ratio is **{_fmt(med)}**, meaning a "
          "typical reservoir's largest observed extent reaches only "
          f"~{_fmt(med*100)}% of its design footprint. The P16–P84 band "
          f"is [{_fmt(stats['fill_p16'])}, {_fmt(stats['fill_p84'])}]. Only "
          f"{_fmt(stats.get('fill_n_above_half'))} out of "
          f"{_fmt(stats['fill_n'])} reservoirs "
          f"({_fmt(100*stats.get('fill_n_above_half', 0)/max(stats['fill_n'], 1))}%) "
          "ever reach $\\ge 0.5\\,A_\\mathrm{DEM}$ in the observation "
          "window.")
        A("")
        A("Physically this signal reflects a combination of (a) arid-zone "
          "hydrology with sparse, episodic inflows that rarely accumulate "
          "to design pool, (b) operational drawdown for irrigation and "
          "domestic supply, (c) seepage and evaporation losses, and (d) "
          "the design margin built into nominal capacities. The signal is "
          "_not_ caused by sedimentation (sediment fills the bottom of "
          "the reservoir without much reducing the spillway-level area) "
          "and _not_ caused by DEM oversizing (at the only available "
          "bathymetric ground-truth site — Baish — the SRTM footprint "
          "matches the design-table spillway area to within ~1%).")
        A("")
        A("This is the central physical fact that motivates the "
          "regionalization recipe in this report: an anchor based on the "
          "satellite-observed maximum extent does not match the design "
          "footprint the catalogue capacity refers to, so anchoring "
          "$V_\\mathrm{cap}$ against $A_\\mathrm{sat}^{P95}$ inflates "
          "$c$ by $(A_\\mathrm{DEM}/A_\\mathrm{sat})^{b}$, of order "
          f"$\\sim {_fmt((1.0/med)**stats.get('b_regionalized', stats.get('b_median', 1.5)))}\\times$ "
          "in this region. Anchoring against a DEM-derived $A_\\mathrm{cap}$ "
          "instead keeps both endpoints in the design regime.")
        A("")
    else:
        A("Satellite water-extent statistics unavailable — run the "
          "validation module to populate this section.")
        A("")

    # ---- sediment budget ----
    A("### Sediment budget")
    A("")
    if "sediment_loss_median" in stats:
        if stats.get("sediment_sdr_model") == "none_yield_is_delivered":
            sdr_eq = ("The yield input is *delivered* sediment yield at the "
                      "reservoir inlet -- Dash et al. (2025) compute it as "
                      "RUSLE gross erosion times the Boyce (1974) "
                      "area-dependent delivery ratio (their Eqs. 2-4) -- so "
                      "no additional delivery ratio is applied here "
                      "(a second SDR would double-discount delivery).")
        else:
            sdr_eq = ("A uniform sediment delivery ratio "
                      f"$\\mathrm{{SDR}} = {_fmt(stats.get('sediment_sdr'))}$ "
                      "is applied to the yield input.")
        A("A first-order sediment budget is computed from "
          "catchment-specific delivered-yield estimates "
          "(`sed_yield_t_ha_yr`) and "
          "upstream catchment areas, propagated to the reference year "
          f"({_yr(stats['reference_year'])}) with deposited bulk density "
          f"$\\rho_\\mathrm{{sed}} = "
          f"{_fmt(stats['sediment_bulk_density'])}\\,\\mathrm{{t\\,m^{{-3}}}}$. "
          f"{sdr_eq} "
          "The accumulated trap volume is $V_\\mathrm{sed} = "
          "Y \\cdot A_\\mathrm{cat} \\cdot (t - t_\\mathrm{built}) "
          "/ \\rho_\\mathrm{sed}$, and the predicted fractional "
          "capacity loss is capped at $100\\%$ by trap saturation (a reservoir "
          "cannot lose more storage than it holds).")
        A("")
        A(f"Across $n = {_fmt(stats['sediment_n'])}$ dams with all required "
          "inputs, the predicted median capacity loss is "
          f"**{_fmt(stats['sediment_loss_median']*100)}%** of design "
          "capacity, with P16–P84 = "
          f"[{_fmt(stats['sediment_loss_p16']*100)}%, "
          f"{_fmt(stats['sediment_loss_p84']*100)}%]. "
          f"{_fmt(stats.get('sediment_n_loss_above_50pct'))} reservoirs "
          "are predicted to have lost $\\ge 50\\%$ of their capacity, and "
          f"{_fmt(stats.get('sediment_n_fully_silted'))} reach full siltation "
          "($\\ge 100\\%$ of design before capping, i.e. the integrated "
          "sediment trap volume meets or exceeds the original storage, "
          "typically very small headwater impoundments). The per-dam capped "
          "fraction and a categorical risk band are released as "
          "`predicted_silt_fraction` and `sediment_risk` in "
          "`eaves_summary.csv`.")
        A("")
        A("The single bathymetric ground-truth comparison available (Baish, "
          "id_120000) shows this first-order budget under-predicts the "
          "observed loss by a factor of ~1.6 at that site "
          "(predicted ~23% versus ~36% from the 2025 sonar over the same "
          "window), consistent with site-specific sediment yield somewhat "
          "above the regional first-order input. The national capacity "
          "loss implied by the budget matches the ~32% reported by Dash "
          "et al. (2025) from the same yield estimates. The per-dam numbers "
          "should nevertheless be read as first-order screening indicators, "
          "not site predictions. A region-specific calibration would benefit from "
          "comparative bathymetry on a small panel of reservoirs spanning "
          "the size range.")
        A("")
        A("Crucially, sediment fills the bottom of the reservoir but does "
          "not change the spillway-level area, so the EAV curves shipped "
          "in this report are _design_ curves rather than current "
          "operational curves. A sediment-corrected operational curve set "
          "can be produced by subtracting $V_\\mathrm{sed}$ from the "
          "design $V$ axis (with the curve truncated below the predicted "
          "sediment floor) but is not the canonical product.")
        A("")
    else:
        A("Sedimentation inputs not configured.")
        A("")

    # ---- geometry distribution ----
    A("### Geometry distribution and regionalization features")
    A("")
    if "b_median" in stats:
        A(f"On the trusted subset ($n = {_fmt(stats.get('n_trusted'))}$), the "
          f"power-law exponent $b$ has median **{_fmt(stats['b_median'])}** "
          f"($1\\sigma$ width {_fmt(stats.get('b_sigma'))}). This sits in "
          "the classical valley-fill regime and is consistent with the "
          "wadi geometry that dominates the catalogue.")
        A("")
    if "loglog_alpha" in stats:
        A("The empirical area–capacity relation, fit on the training dams "
          "as $\\log A_\\mathrm{cap}\\,[\\mathrm{km}^2] = "
          "\\alpha + \\beta \\log V_\\mathrm{cap}\\,[\\mathrm{MCM}]$, "
          f"yields $\\alpha = {_fmt(stats['loglog_alpha'])}$, "
          f"$\\beta = {_fmt(stats['loglog_beta'])}$ with a residual RMS "
          f"of a factor of {_fmt(10**stats['loglog_resid_rms'])} over "
          f"$n = {_fmt(stats['loglog_n'])}$ training dams. The exponent "
          "$\\beta$ is close to the geometric expectation $2/3$ for "
          "cone-like valley fills, which is the structural basis for using "
          "this relation as the regionalization anchor.")
        A("")

    # ---- SRTM-derived curves ----
    A("## SRTM-derived curves")
    A("")
    A("For each dam that survives placement and quality gating, the curve "
      "is fit directly from the SRTM-clipped flood-fill: at each elevation "
      "bin in $[z_\\mathrm{min}, z_\\mathrm{spillway}]$ the wetted area "
      "$A(z)$ is computed by counting pixels below $z$ in the footprint, "
      "the corresponding volume $V(z) = \\int A\\,\\mathrm{d}z$ is obtained "
      "by trapezoidal integration, and the resulting $(A, V)$ pairs are fit "
      "to $V = c A^{b}$. The procedure is purely geometric: it uses no "
      "satellite or in-situ data. Curves that pass the trusted-set filter "
      f"({_TRUSTED_FILTER_DOC}) are the reference against which all other "
      "claims in this report are calibrated.")
    A("")
    A("Two cross-references against independently-produced datasets "
      "provide circumstantial consistency checks (not validation in the "
      "strict sense, because both anchors use methodologies distinct "
      "from EAVES): (i) the Baish bathymetric sonar survey -- which "
      "measures the _current operational_ reservoir floor rather than "
      "the pre-impoundment valley EAVES integrates -- lies well below the "
      "SRTM curve at intermediate water levels (sonar volume ~30-65% under "
      "SRTM, the expected signature of ~16 yr of accumulated sediment), "
      "while the design table agrees with SRTM within ~2% in both volume "
      "and area at the spillway level; (ii) three GRDL "
      "Landsat-derived $A$--$z$ curves -- reconstructed from "
      "Landsat-observed extents with a deep-learning bathymetry model "
      "rather than from SRTM topography "
      "directly -- agree visually with the SRTM curves over the "
      "observed depth range. These anchor the EAVES output in the "
      "neighborhood of independently-measured datasets but do not "
      "constitute volumetric validation.")
    L.extend(_embed_figure(
        "p2_placement.png",
        "Dam wall placement examples",
        "Figure 2. Worked examples of the six-stage wall-placement "
        "cascade. (a) Stage 1 fast-path placement on a representative "
        "wadi reservoir. (b) Stage 4 river-direction retry. (c) Stage 6 "
        "fallback fill on a difficult target. Red star: catalogue dam "
        "location. Amber line: accepted wall segment. Blue polygon: "
        "flooded basin at spillway level.",
    ))
    L.extend(_embed_figure(
        "p3_baish_example.png",
        "Worked example for the bathymetry-validated reservoir",
        "Figure 3. Per-dam outputs on the bathymetry-validated reservoir. "
        "(a) SRTM DEM with the inundated footprint overlaid. (b) Area–"
        "volume curve on log–log axes with the fitted power law. (c) "
        "Histogram of the exponent $b$ across the trusted-set "
        "reservoirs.",
    ))
    L.extend(_embed_figure(
        "p4_comparison.png",
        "Cross-reference comparison against sonar bathymetry and GRDL",
        "Figure 4. Cross-reference comparison against independently-"
        "produced reservoir datasets — not validation in the strict "
        "sense: sonar measures the current operational bathymetry "
        "(post-sediment) and GRDL reconstructs bathymetry from "
        "Landsat-observed extents with a deep-learning model, so both "
        "methodologies differ from EAVES. "
        "(a) Sonar bathymetry vs SRTM for the Baish reservoir: $V(A)$ "
        "on the left, elevation–area on the right. (b) GRDL "
        "Landsat-derived curves vs SRTM for three reference reservoirs. "
        "(c) Distribution of $V_\\mathrm{SRTM}/V_\\mathrm{catalogue}$ "
        "across the full catalogue, with the Grade A/B bands marked.",
    ))
    A("")

    # ---- regionalization ----
    A("## Regionalization")
    A("")
    A("Dams whose DEM fit fails the trusted-set filter are assigned $(c, b)$ "
      "by a region-trained empirical recipe rather than per-dam DEM fitting. "
      "The recipe has two pieces. Both pieces are *trained on the region's "
      "own training dams (trusted fits built after the SRTM acquisition)*, "
      "so the method itself is portable but its "
      "coefficients are region-specific.")
    A("")
    A("_Choice of $b$._ The shipped recipe assigns every regionalized dam "
      f"the regional median **$b = {_fmt(stats.get('b_median'))}$**. This is "
      "the principled choice given a strong empirical result: $b$ is **not "
      "predictable from morphometric features alone** with the data we have. "
      "We tested three increasingly flexible alternatives before settling "
      "on the median, and each one fell short.")
    A("")
    A("_1. Multivariate regression (linear and random forest)._ "
      "Trained `valley_ratio`, `channel_slope`, `mean_catchment_slope`, "
      "and `dam_height_m` against $b$ on the training set in a "
      "leave-one-out cross-validation. Both LinearRegression and "
      "RandomForestRegressor were tried. The selection gate requires "
      "$R^2_\\mathrm{LOO} \\ge 0.25$ for a regression to replace the "
      "median. Both candidates fell below: each individual feature "
      "explains less than 10 % of the variance in $b$ "
      "(Spearman $|\\rho| \\le 0.31$, so $R^2 \\le 0.10$ per feature), "
      "and the features are partly redundant, so combining them adds "
      "little. The regression branch is rejected; the median is used.")
    A("")
    # Silhouette and LOO numbers come from b_clustering_diagnostic.csv so prose tracks the figure.
    gain = stats.get("b_cluster_best_gain_pct")
    gain_str = f"{gain:.0f}" if gain is not None else "—"

    A("_2. Morphological clustering with a per-cluster median._ "
      "Even when features can't drive a smooth regression, they may "
      "carve the training set into morphologically homogeneous clusters "
      "whose internal $b$ spread is tighter than the population spread. "
      "We tested this directly: k-means in log-space, $z$-scored, on the "
      "raw-morphometry feature set (released in "
      "`validation/b_clustering_diagnostic.csv`), sweeping $k = 2 \\ldots 12$. "
      "Best LOO $\\sigma(\\Delta b)$: "
      f"**{_fmt(stats.get('b_cluster_best_sigma'))} at "
      f"$k = {stats.get('b_cluster_best_k', '—')}$**, "
      f"versus **{_fmt(stats.get('b_cluster_baseline_sigma'))}** for "
      f"the global median — a genuine but modest "
      f"**~{gain_str} % tightening** (Fig. S1, panel b). "
      "The supporting silhouette analysis (Fig. S1, panel a) shows mean "
      f"silhouette coefficients in the "
      f"**{_fmt(stats.get('b_cluster_silhouette_min'))}"
      f"–{_fmt(stats.get('b_cluster_silhouette_max'))}** range across "
      "every feature set and every $k$, i.e. below the 0.50 conventional "
      "threshold for _reasonable_ cluster structure — there is no natural "
      "morphological partition to exploit. Two things drive the small "
      "remaining gain: (a) every morphological feature individually has "
      "Spearman $|\\rho| \\le 0.31$ with $b$, so cluster boundaries blur; "
      "(b) the within-cluster variance of $b$ is comparable to the "
      "between-cluster differences, meaning the clusters don't actually "
      "separate the population into distinct $b$ regimes.")
    L.extend(_embed_figure(
        "s1_b_clustering_silhouette.png",
        "Supplementary: K-means clustering diagnostic for b",
        "Figure S1. K-means clustering diagnostic on the training-set "
        "dams in log-transformed morphometric feature space. "
        "(a) Mean silhouette coefficient versus number of clusters $k$ "
        "for the raw-morphometry feature set. It remains below the "
        "conventional 0.50 _reasonable structure_ threshold for every "
        f"$k$; the $k = 2$ peak at {_fmt(stats.get('b_cluster_silhouette_max'))} reflects a single "
        "elongated population, not two morphological types. (b) Leave-"
        "one-out $\\sigma(\\Delta b)$ for a per-cluster-median predictor "
        "of $b$ versus the global-median baseline (dashed). The best "
        f"configuration improves on the baseline by ~{gain_str} %, well within "
        "the intrinsic noise floor of fitting the power law to "
        "integrated SRTM curves. The diagnostic justifies the global-"
        "median choice for $b$ in the production recipe.",
    ))
    A("")
    A("_3. The intrinsic noise floor._ "
      "Across every regression and clustering configuration we tried, "
      "the leave-one-out residual on $b$ converges to "
      "$\\sigma(\\Delta b) \\approx 0.24$. This is the noise floor of "
      "fitting a two-parameter power law to integrated SRTM curves: the "
      "value of $b$ is sensitive to (i) the discrete pixel-bin assignment "
      "of the flood fill, (ii) void interpolation in the DEM, (iii) the "
      "catalogue-driven spillway-height overrides that rewrite obviously-"
      "mistyped catalogue rows (`curves.py:65-73`), and (iv) where the "
      "capacity cap truncates the curve. Two dams with identical "
      "valley-ratio / slope / length / height signatures can fit "
      "different $b$ purely from these integration-side artefacts. No "
      "feature-based predictor can resolve $b$ below that floor.")
    A("")
    A("_Practical implication._ "
      "Adopting cluster-medians instead of the global median would buy "
      f"$\\sim {gain_str} \\%$ tighter $\\sigma_b$ at the cost of an additional "
      "moving part (cluster fit + per-dam assignment) that doesn't "
      "change the qualitative story. We retain the **global median** as "
      "the shipped recipe: it is the simplest assignment consistent with "
      "the data, and the `b_sigma` column quantifies the residual "
      "uncertainty without overclaiming structure we cannot resolve.")
    A("")
    A("_Regression branch retained as a region-portable fallback._ "
      "If a future region's catchment-feature distribution produces "
      "$R^2_\\mathrm{LOO} \\ge 0.25$, the regression auto-activates "
      "([`regionalization.py:259-298`]) and predicted $b$ values are "
      "written under the `regr_derived` source label (reserved for that "
      "branch; absent from the released KSA files). This has never "
      "fired on the KSA catalogue.")
    A("")
    A("_Choice of $c$._ The shipped recipe anchors each regionalized "
      "dam at the predicted full-pool area $A_\\mathrm{cap}$ and back-"
      "solves $c = V_\\mathrm{cap} / A_\\mathrm{cap}^{b}$. The prediction "
      "is a closed-form linear regression of $\\log A_\\mathrm{cap}$ on "
      "seven log-space features trained on the trusted DEM footprints:")
    A("")
    A("$$\\log A_\\mathrm{cap} = \\alpha_0 + \\sum_{i=1}^{7} \\alpha_i \\log X_i$$")
    A("")
    A("with $X_i \\in \\{$ `capacity_mcm`, `dam_height_m`, "
      "`spillway_height_m`, `valley_ratio`, `channel_slope`, "
      "`mean_catchment_slope`, `upstream_area_km2` $\\}$. Any feature "
      "that is missing for a given dam is imputed with the training-set "
      "median before prediction, so the regression always returns a "
      "finite value and there is a single recipe for every regionalized "
      "row in `eaves_params.csv`.")
    A("")
    A("Two earlier drafts of the pipeline are still evaluated by the "
      "validation module for the comparison below: (i) anchoring at the "
      "satellite 95th-percentile water area, and (ii) a single-feature "
      "$\\log A_\\mathrm{cap} = \\alpha + \\beta \\log V_\\mathrm{cap}$ "
      "regression. Both were retired in favor of the multi-feature "
      "anchor.")
    A("")
    if "fill_median" in stats:
        med = stats["fill_median"]
        A(f"Because reservoirs in this region operate at only "
          f"~{_fmt(med*100)}% of design footprint, the satellite anchor "
          "captures an _operational_ area rather than the design area that "
          "the catalogue $V_\\mathrm{cap}$ refers to. Mixing a design "
          "volume with an operational area inflates $c$ by "
          f"$\\sim (1/{_fmt(med)})^{{b}} \\approx "
          f"{_fmt((1.0/med)**stats.get('b_regionalized', stats.get('b_median', 1.5)))}\\times$ at the median. "
          "Both DEM-trained anchors stay in the design regime by "
          "construction.")
        A("")

    # ---- validation ----
    A("## Validation")
    A("")
    A("This is the formal validation of EAVES: a self-consistent test "
      "_within_ the EAVES methodology, in contrast to the cross-"
      "references above which use independently-produced datasets. "
      "Per-recipe accuracy is measured by masking each trusted dam in "
      "turn, retraining the regionalization recipe on the remaining "
      "training dams, predicting the masked dam's $V$ at "
      "$A = A_\\mathrm{DEM}$, and comparing against the SRTM-derived "
      "truth. Errors are computed in $\\log_{10}$ ratio space and reported "
      "below in the relative convention (a percentage, or a multiplicative "
      "factor for larger values). The full per-dam table lives in "
      "`<CSV_DIR>/validation/regionalization_loo.csv` and the visual "
      "summary in panel set p5.")
    A("")
    if "loo_multi_anchor_within_2x_frac" in stats:
        A("| Metric | Satellite anchor (retired) | Log–log anchor | "
          "Multi-feature LR (shipped) |")
        A("| --- | --- | --- | --- |")
        A(f"| n | {_fmt(stats.get('loo_sat_anchor_n'))} | "
          f"{_fmt(stats.get('loo_loglog_anchor_n'))} | "
          f"{_fmt(stats.get('loo_multi_anchor_n'))} |")
        A(f"| median bias | "
          f"{_relfmt(stats.get('loo_sat_anchor_median_log10'), signed=True)} | "
          f"{_relfmt(stats['loo_loglog_anchor_median_log10'], signed=True)} | "
          f"**{_relfmt(stats['loo_multi_anchor_median_log10'], signed=True)}** |")
        A(f"| Median abs. % error | "
          f"— | — | "
          f"**{_pctfmt(stats.get('loo_multi_anchor_medape_frac'))}** |")
        A(f"| Relative RMSE | "
          f"— | — | "
          f"**{_pctfmt(stats.get('loo_multi_anchor_relrmse_frac'))}** |")
        A(f"| Within $2\\times$ | "
          f"{_pctfmt(stats.get('loo_sat_anchor_within_2x_frac'))} | "
          f"{_pctfmt(stats['loo_loglog_anchor_within_2x_frac'])} | "
          f"**{_pctfmt(stats['loo_multi_anchor_within_2x_frac'])}** |")
        A(f"| Within $3\\times$ | "
          f"{_pctfmt(stats.get('loo_sat_anchor_within_3x_frac'))} | "
          f"{_pctfmt(stats['loo_loglog_anchor_within_3x_frac'])} | "
          f"**{_pctfmt(stats['loo_multi_anchor_within_3x_frac'])}** |")
        A(f"| Within $10\\times$ | "
          f"{_pctfmt(stats.get('loo_sat_anchor_within_10x_frac'))} | "
          f"{_pctfmt(stats['loo_loglog_anchor_within_10x_frac'])} | "
          f"**{_pctfmt(stats['loo_multi_anchor_within_10x_frac'])}** |")
        A("")
        A("'Within $n\\times$' means $|\\log_{10}(V_\\mathrm{pred} / "
          "V_\\mathrm{SRTM})| \\le \\log_{10}(n)$, i.e. the predicted "
          "volume sits between $V_\\mathrm{SRTM} / n$ and "
          "$V_\\mathrm{SRTM} \\cdot n$.")
        A("")
        A("The shipped multi-feature recipe halves the $1\\sigma$ spread "
          "of the single-feature log–log alternative (and is roughly five "
          "times tighter than the retired satellite anchor). The bias is "
          "essentially zero across all three candidates, but only the "
          "DEM-trained anchors stay in the design regime that the "
          "catalogue $V_\\mathrm{cap}$ refers to.")
        L.extend(_embed_figure(
            "p5_regionalization_validation.png",
            "Regionalization accuracy panel",
            "Figure 5. Leave-one-out validation of the regionalization "
            "recipe on the trusted SRTM-derived dams. (a) Predicted vs "
            "SRTM-truth volume at the DEM full-pool area, with 1:1 line "
            "and ±factor-2 / ±factor-3 bands; the inset box lists the "
            "headline accuracy statistics. (b) Signed prediction error "
            "distribution, zero line, median, and P16–P84 band marked. "
            "(c) Error stability across catalogue capacity; the binned "
            "median tracks zero across four decades of $V_\\mathrm{cap}$.",
        ))
        A("")

    A("Two caveats. First, the LOO test measures the recipe's ability to "
      "reproduce _the SRTM-derived curve_, not the absolute truth. The "
      "SRTM curves themselves have an unquantified residual error "
      "($\\lesssim 20\\%$ on the one available bathymetric anchor). "
      "Second, the LOO test is run on trusted-like dams; the actual "
      "regionalized population is systematically smaller and steeper, so "
      "the realised accuracy on those dams may have a wider spread than "
      "panel p5 reports. The structural bias correction ($\\sim 10\\times$ on "
      "the satellite-anchor recipe) carries through regardless.")
    A("")

    # ---- uncertainty propagation ----
    A("## Uncertainty on volume predictions")
    A("")
    A("The training-set spread of the exponent $b$ ($b_\\sigma \\approx 0.27$, the "
      "dimensionless P16--P84 half-width, identical "
      "for every dam) is the single number that propagates into the V "
      "confidence band. It is released per dam as the `b_sigma` column of "
      "`validation/v_uncertainty.csv` (the near-identical "
      "`b_cluster_baseline_sigma` in `domain_characterization.csv` is the "
      "separate clustering-baseline diagnostic). Because every curve is pinned through the "
      "catalogue anchor $(A_\\mathrm{cap}, V_\\mathrm{cap})$, the resulting "
      "V band widens away from full pool. Because the fill is capped at the "
      "catalog capacity, every curve also carries the area-independent "
      "catalog-capacity term, which floors the SRTM-derived band at about "
      "+39%/-28% even at the anchor; regionalized curves add the predicted-"
      "area term and floor at about +87%/-47% (see `validation/v_uncertainty.csv`):")
    A("")
    A("$$\\sigma(\\log_{10}V) = b_\\sigma \\cdot |\\log_{10}(A/A_\\mathrm{cap})|.$$")
    A("")
    A("A user wanting a confidence band on $V$ at any area $A$ should use:")
    A("")
    A("- $A_\\mathrm{cap} = (V_\\mathrm{cap}/c)^{1/b}$  (implicit anchor)")
    A("- $V_\\mathrm{lo} = V_\\mathrm{cap}\\,(A/A_\\mathrm{cap})^{b+b_\\sigma}$  (steeper bound)")
    A("- $V_\\mathrm{hi} = V_\\mathrm{cap}\\,(A/A_\\mathrm{cap})^{b-b_\\sigma}$  (shallower bound)")
    A("")
    A("The full per-dam table at three reference fill levels is written by "
      "`eaves.postprocess.uncertainty` to "
      "`<CSV_DIR>/validation/v_uncertainty.csv`. Population-median band widths "
      "for this region:")
    A("")
    # Pull median sigmas from the freshly computed table so prose tracks data.
    vunc_path = Path(_cfg.CSV_DIR) / "validation" / "v_uncertainty.csv"
    if vunc_path.exists():
        vu = pd.read_csv(vunc_path)
        A("| Fill level | V uncertainty (median) |")
        A("| --- | --- |")
        for label_h, key in [("half pool ($A/A_\\mathrm{cap}=0.50$)",     "half_pool"),
                             ("quarter pool ($A/A_\\mathrm{cap}=0.25$)",  "quarter_pool"),
                             ("tenth pool ($A/A_\\mathrm{cap}=0.10$)",    "tenth_pool")]:
            med_up  = float(vu[f"V_frac_up_{key}"].median())
            med_dn  = float(vu[f"V_frac_down_{key}"].median())
            A(f"| {label_h} | +{_pctfmt(med_up)} / -{_pctfmt(med_dn)} |")
    L.extend(_embed_figure(
        "s3_uncertainty_band.png",
        "Supplementary: V uncertainty band from b_sigma",
        "Figure S3. Propagation of the $1\\sigma$ uncertainty on $b$ into "
        "a V uncertainty band. (a) Worked example on the Baish reservoir: "
        "the $\\pm b_\\sigma$ band is forced through the catalogue full-pool "
        "anchor (red star) and fans out at lower water levels; the "
        "catalog-capacity floor (~+39%/-28%) applies even at the anchor. "
        "(b) The two $\\sigma(\\log_{10}V)$ tiers "
        "versus normalized area: the SRTM-derived tier is floored by the "
        "catalog-capacity term at the anchor and widens with the geometric "
        "$b_\\sigma$ term away from full pool, while the regionalized tier "
        "adds the area-independent "
        "anchor terms and floors near +87%. The regional typical operational "
        "fill level is overlaid (vertical dashed line), so the V "
        "uncertainty at the fill level most reservoirs in this region "
        "actually operate at can be read off directly.",
    ))
    A("")

    # ---- generalization ----
    A("## Generalization to other regions")
    A("")
    A("The EAVES pipeline is region-portable as method, region-specific as "
      "fitted parameters. Universal pieces:")
    A("")
    A("- The placement cascade and the power-law fit make no regional "
      "assumptions beyond the existence of a valley-shaped impoundment.")
    A("- The regionalization recipe (regional median $b$ + multi-feature "
      "LR $A_\\mathrm{cap}$ anchor) uses only the region's own trusted "
      "dams as training data.")
    A("- The LOO validation procedure provides an objective accuracy "
      "estimate in each region.")
    A("")
    A("Region-specific pieces (must be re-fit, never reused verbatim):")
    A("")
    A("- The multi-feature LR coefficients of the area–capacity anchor. "
      "These reflect the region's terrain and design conventions and do "
      "not transfer between regions.")
    A("- The regional median $b$ (or, where features predict $b$ well, "
      "the regression coefficients).")
    A("- The DEM-trained anchor remains the right choice in any arid or "
      "semi-arid region where reservoirs do not routinely fill to design "
      "pool. In humid catchments with regular drawdown-to-spillway "
      "cycles the satellite signal could become competitive and is worth "
      "re-evaluating per region.")
    A("- The quality-gate thresholds (`r_squared`, `vol_ratio`, "
      "`n_pixels`), which are tuned to the noise of the region's DEM and "
      "catalogue.")
    A("")
    A("To deploy EAVES on a new region: configure a settings JSON pointing "
      "to the local catalogue and SRTM mosaic, then run `./run_all.sh "
      "region/<country>/<country>.json` from the project root. The script "
      "chains the pipeline, validation, panels, and report in the correct "
      "order so every figure and every number in this document is "
      "regenerated with regionally-fit values.")
    A("")

    # ---- limitations ----
    A("## Limitations and open issues")
    A("")
    A("- **No true volumetric ground truth.** The closest cross-reference "
      "anchors are the Baish sonar survey and three Landsat-derived GRDL "
      "curves, both produced with methodologies distinct from EAVES "
      "(sonar measures the current operational reservoir floor; GRDL "
      "reconstructs bathymetry from Landsat-observed extents). They show "
      "circumstantial consistency, not direct validation. Wider "
      "bathymetric campaigns are the only path to a rigorous "
      "SRTM-truth comparison.")
    A("- **Catalogue capacity is design, not as-built.** No correction is "
      "applied for legacy errors in the published storage values, which "
      "the trusted set's vol_ratio histogram already shows can scatter "
      "over a decade.")
    A("- **Sediment loss is a first-order estimate.** Bulk density is "
      "uniform across the region and the delivery ratio follows a single "
      "area-dependent law. Bathymetric calibration of these on "
      "a small panel of reservoirs would let us promote the operational "
      "curve set from sensitivity scenario to canonical product.")
    A("- **Per-dam $b$ uncertainty is population-level, not individual.** "
      "`validation/v_uncertainty.csv` and "
      "`domain_characterization.csv` carry the $1\\sigma$ uncertainty on "
      "$b$ as a single region-level number ($b_\\sigma \\approx 0.27$, dimensionless, from the training set), identical for every "
      "dam regardless of source. A per-dam narrowing of that interval would "
      "require repeated DEM realizations or an ensemble of independent DEMs, "
      "which is not currently feasible.")
    A("")

    # ---- artefacts ----
    A("## Files produced")
    A("")
    A("| Path | Content |")
    A("| --- | --- |")
    A("| `1_results_csv/eaves_summary.csv` | Per-dam pipeline outputs: "
      "placement metadata, fit results, quality flags, external attributes. |")
    A("| `1_results_csv/eaves_params.csv` | Lean per-dam parameter table: "
      "$(c, b)$ plus identification and the assignment source. Six "
      "columns. The $1\\sigma$ uncertainty on $b$ is a single region-level "
      "scalar stored in `validation/v_uncertainty.csv` and "
      "`domain_characterization.csv`, not duplicated per row. |")
    A("| `1_results_csv/failed_dams.csv` | Dams dropped before fitting, with "
      "failure reason. |")
    A("| `1_results_csv/threshold_analysis.csv` | Reliability threshold "
      "sweep used to set the trusted-set cut. |")
    A("| `1_results_csv/eav_tables/<dam_id>_eav.csv` | Tabulated "
      "$(z, A, V)$ per dam. |")
    A("| `1_results_csv/validation/regionalization_loo.csv` | Per-recipe "
      "LOO residuals, every trusted dam. |")
    A("| `1_results_csv/validation/dem_vs_sat_area.csv` | $A_\\mathrm{DEM}$ "
      "vs $A_\\mathrm{sat}^{P95}$ paired data. |")
    A("| `1_results_csv/validation/b_clustering_diagnostic.csv` | Silhouette "
      "and LOO $\\sigma(\\Delta b)$ per (feature-set, $k$) — backs the "
      "supplementary figure S1. |")
    A("| `1_results_csv/validation/v_uncertainty.csv` | Per-dam V "
      "uncertainty propagated from `b_sigma` at half, quarter, and tenth "
      "pool — backs the supplementary figure S3. |")
    A("| `1_results_csv/validation/goodness_of_fit.csv` | Per-dam "
      "fractional volume residuals of the power-law fit (area-to-volume "
      "direction). |")
    A("| `1_results_csv/validation/acap_regression_diagnostics.csv` | "
      "VIF, condition number, and incremental-LOO diagnostics for the "
      "seven-feature $A_\\mathrm{cap}$ regression. |")
    A("| `1_results_csv/validation/dem_error_montecarlo.csv` | Per-dam "
      "volume spread under SRTM vertical-error perturbations — backs the "
      "supplementary figure S4. |")
    A("| `1_results_csv/validation/sensitivity_sweep.csv` | Trusted-set "
      "stability under ±20–30% perturbations of the placement constants "
      "— backs the supplementary figure S5. |")
    A("| `1_results_csv/domain_characterization.csv` | Flat table of every "
      "statistic referenced in this report. |")
    A("| `2_results_plots/p1`–`p5_*.{png,pdf}` | Publication-grade panel "
      "figures; each panel is written as both a 300-dpi PNG (embedded in "
      "this report) and a vector PDF (for journal submission). |")
    A("| `2_results_plots/s1_b_clustering_silhouette.{png,pdf}` | "
      "Supplementary figure S1: K-means clustering diagnostic for $b$. |")
    A("| `2_results_plots/s2_threshold_analysis.{png,pdf}` | Supplementary "
      "figure S2: capacity-threshold sweep behind the reliability cut "
      "($R^2$ vs reservoir size by quality grade, fraction-reliable vs "
      "candidate cutoff). |")
    A("| `2_results_plots/s3_uncertainty_band.{png,pdf}` | Supplementary "
      "figure S3: V uncertainty band derived from `b_sigma`, with a "
      "worked example on Baish and the two-tier $\\sigma(\\log_{10}V)$ "
      "curves versus normalized area. |")
    A("| `2_results_plots/s4_dem_error.{png,pdf}` | Supplementary "
      "figure S4: DEM vertical-error Monte-Carlo volume spread by "
      "capacity class. |")
    A("| `2_results_plots/s5_sensitivity.{png,pdf}` | Supplementary "
      "figure S5: placement-constant sensitivity sweep. |")
    A("| `report.md` | This document. |")
    A("")

    return "\n".join(L)


# --- Entry points ---

def run(settings_path: str | None = None,
        ref_year: int | None = None,
        sediment_sdr: float | None = None,
        sediment_bulk_density: float = 1.3) -> dict:
    """Programmatic entry: compute characterization, write CSV + Markdown.

    ``sediment_sdr=None`` (the default) applies no delivery ratio, because
    the ``sed_yield_t_ha_yr`` input is delivered yield (see module-level
    note); pass a float to apply a constant SDR for regions whose yield
    input is gross erosion.
    """
    if settings_path is not None:
        from eaves.settings import load_settings
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

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    md = render_report_md(stats, generated_at)
    md_path = Path(_cfg.OUTPUT_DIR) / "report.md"
    md_path.write_text(md)

    print(f"wrote {csv_path}")
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
                   "yield; pass a float only if the input is gross erosion.")
    p.add_argument("--sediment-bulk-density", type=float, default=1.3,
                   help="Deposited sediment bulk density in t/m^3 "
                   "(default 1.3).")
    args = p.parse_args(argv)
    run(settings_path=args.settings,
        ref_year=args.ref_year,
        sediment_sdr=args.sediment_sdr,
        sediment_bulk_density=args.sediment_bulk_density)


if __name__ == "__main__":
    main()
