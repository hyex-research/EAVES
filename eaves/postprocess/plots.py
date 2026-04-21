"""All plotting functions — styled for Nature Water submission.

Panel labels use bold lowercase letters (a, b, c, ...).
Font sizes: 5-7 pt (Nature max 7 pt), Arial / Helvetica.
Figure widths: 89 mm / 3.5 in (single column), 183 mm / 7.2 in (double column).
Colourblind-safe palette throughout; viridis as default sequential cmap.
Flood QC maps stay at 100 DPI (not for publication).
"""

from __future__ import annotations

import os

import numpy as np
import pandas as pd
import matplotlib as mpl
import matplotlib.pyplot as plt

import eaves.config as _cfg
from ..config import (
    _BASE_FS,
    FIG_SINGLE_COL,
    FIG_DOUBLE_COL,
    FIG_MAX_HEIGHT,
    GRADE_COLORS,
    NATURE_COLORS,
)
from ..utils import fit_power_law, power_law_2p


_ANALYSIS_FS = 16
_PANEL_FS = _ANALYSIS_FS * 1.2

_ANALYSIS_RC = {
    "font.size": _ANALYSIS_FS,
    "axes.titlesize": _ANALYSIS_FS,
    "axes.labelsize": _ANALYSIS_FS,
    "xtick.labelsize": _ANALYSIS_FS,
    "ytick.labelsize": _ANALYSIS_FS,
    "legend.fontsize": _ANALYSIS_FS,
    "axes.linewidth": 1.0,
}


def _label_panel(ax, label):
    """Bold lowercase panel label, top-left, outside axes (project convention)."""
    ax.text(
        0.0, 1.06, label,
        transform=ax.transAxes,
        fontsize=_PANEL_FS, fontweight="bold",
        ha="left", va="bottom",
        clip_on=False,
    )


# ---------------------------------------------------------------------------
# Bathymetry validation (2-panel): sonar EAV vs SRTM-derived EAV
# ---------------------------------------------------------------------------

def bathymetry_validation(summary, output_dir):
    bathy_csv = getattr(_cfg, "BATHYMETRY_EAV_CSV", None)
    if not bathy_csv or not os.path.isfile(bathy_csv):
        return

    bathy = pd.read_csv(bathy_csv)
    elev_bathy = bathy["elevation_m"].values
    area_bathy = bathy["area_m2_integrated_dem"].values
    vol_bathy = bathy["volume_m3_integrated_dem"].values

    c_bathy, b_bathy, r2_bathy = fit_power_law(area_bathy, vol_bathy)

    elev_srtm = summary["elev_bins"]
    area_srtm = summary["area_m2"]
    vol_srtm = summary["vol_m3"]

    c_srtm = summary["c"]
    b_srtm = summary["b"]

    max_len = max(len(elev_bathy), len(elev_srtm))

    def pad(arr, length):
        out = np.full(length, np.nan)
        out[: len(arr)] = arr
        return out

    val_df = pd.DataFrame({
        "elev_bathy_m": pad(elev_bathy, max_len),
        "area_bathy_m2": pad(area_bathy, max_len),
        "vol_bathy_m3": pad(vol_bathy, max_len),
        "elev_srtm_m": pad(elev_srtm, max_len),
        "area_srtm_m2": pad(area_srtm, max_len),
        "vol_srtm_m3": pad(vol_srtm, max_len),
    })
    val_df.to_csv(os.path.join(_cfg.CSV_DIR, "bathymetry_validation.csv"), index=False)

    with mpl.rc_context(_ANALYSIS_RC):
        fig, axes = plt.subplots(1, 2, figsize=(14.0, 5.0), tight_layout=True)

        ax = axes[0]
        _label_panel(ax, "a")
        ax.plot(area_bathy / 1e6, vol_bathy / 1e6,
                color=NATURE_COLORS["blue"], lw=1.4, label="Bathymetry (2025 sonar)")
        ax.plot(area_srtm / 1e6, vol_srtm / 1e6,
                color=NATURE_COLORS["vermillion"], lw=1.4, label="SRTM (pre-dam valley)")
        if not np.isnan(c_bathy):
            a_fit = np.linspace(0, np.max(area_bathy), 200)
            ax.plot(a_fit / 1e6, power_law_2p(a_fit, c_bathy, b_bathy) / 1e6,
                    color=NATURE_COLORS["blue"], ls="--", lw=0.8, alpha=0.7,
                    label=f"Bathy fit: c={c_bathy:.4g}, b={b_bathy:.4f}")
        if not np.isnan(c_srtm):
            a_fit = np.linspace(0, np.max(area_srtm), 200)
            ax.plot(a_fit / 1e6, power_law_2p(a_fit, c_srtm, b_srtm) / 1e6,
                    color=NATURE_COLORS["vermillion"], ls="--", lw=0.8, alpha=0.7,
                    label=f"SRTM fit: c={c_srtm:.4g}, b={b_srtm:.4f}")
        ax.set_xlabel("Area (km\u00b2)")
        ax.set_ylabel("Volume (MCM)")
        ax.set_title("Sonar vs SRTM: Area\u2013Volume")
        ax.legend()
        ax.grid(True, ls="--", alpha=0.3, lw=0.4)

        ax = axes[1]
        _label_panel(ax, "b")
        ax.plot(area_bathy / 1e6, elev_bathy,
                color=NATURE_COLORS["blue"], lw=1.4, label="Bathymetry")
        ax.plot(area_srtm / 1e6, elev_srtm,
                color=NATURE_COLORS["vermillion"], lw=1.4, label="SRTM")
        ax.set_xlabel("Area (km\u00b2)")
        ax.set_ylabel("Elevation (m asl)")
        ax.set_title("Sonar vs SRTM: Elevation\u2013Area")
        ax.legend()
        ax.grid(True, ls="--", alpha=0.3, lw=0.4)

        plt.savefig(os.path.join(output_dir, "bathymetry_validation.png"),
                    dpi=300, bbox_inches="tight")
        plt.close(fig)


# ---------------------------------------------------------------------------
# Diagnostic plots (histogram, scatter, map)
# ---------------------------------------------------------------------------

def make_diagnostic_plots(summary_df, output_dir):
    valid = summary_df.dropna(subset=["b"])

    with mpl.rc_context(_ANALYSIS_RC):
        fig, axes = plt.subplots(1, 3, figsize=(24.0, 5.5))
        fig.subplots_adjust(wspace=0.35)

        ax = axes[0]
        _label_panel(ax, "a")
        ax.hist(valid["b"], bins=30, edgecolor="k", lw=0.4, alpha=0.7,
                color=NATURE_COLORS["sky_blue"])
        ax.set_xlabel("EAV exponent $b$")
        ax.set_ylabel("Count")
        ax.set_title("Distribution of EAV exponents")
        ax.axvline(valid["b"].median(), color=NATURE_COLORS["vermillion"], ls="--", lw=1,
                   label=f"median = {valid['b'].median():.3f}")
        ax.legend()
        ax.grid(True, ls="--", alpha=0.3, lw=0.4)

        ax = axes[1]
        _label_panel(ax, "b")
        sc = ax.scatter(valid["dam_height_m"], valid["b"], c=valid["r_squared"],
                        cmap="viridis", edgecolors="k", s=30, alpha=0.8, lw=0.3)
        cbar = plt.colorbar(sc, ax=ax)
        cbar.set_label("R\u00b2")
        ax.set_xlabel("Dam height (m)")
        ax.set_ylabel("EAV exponent $b$")
        ax.set_title("Exponent vs height")
        ax.grid(True, ls="--", alpha=0.3, lw=0.4)

        ax = axes[2]
        _label_panel(ax, "c")
        sc = ax.scatter(valid["lon"], valid["lat"], c=valid["b"],
                        cmap="viridis", edgecolors="k", s=28, alpha=0.8, lw=0.3)
        cbar = plt.colorbar(sc, ax=ax, shrink=0.8)
        cbar.set_label("EAV exponent $b$")
        ax.set_xlabel("Longitude (\u00b0E)")
        ax.set_ylabel("Latitude (\u00b0N)")
        ax.set_title("EAV exponent map")
        ax.grid(True, ls="--", alpha=0.3, lw=0.4)

        plt.savefig(os.path.join(output_dir, "exponent_diagnostics.png"),
                    dpi=300, bbox_inches="tight")
        plt.close(fig)

    print("Diagnostic plots saved.")


# ---------------------------------------------------------------------------
# GRDL comparison (multi-row panels)
# ---------------------------------------------------------------------------

def grdl_validation(summary_df, output_dir):
    if not os.path.isdir(_cfg.GRDL_DIR):
        return

    import glob as _glob
    grdl_files = sorted(_glob.glob(os.path.join(_cfg.GRDL_DIR, "*.csv")))
    if not grdl_files:
        return

    comparisons = []
    for gf in grdl_files:
        stem = os.path.splitext(os.path.basename(gf))[0].lower()
        mapped_id = _cfg.GRDL_NAME_MAP.get(stem)
        if mapped_id is None:
            continue

        with open(gf, "r") as fh:
            lines = fh.readlines()
        data_lines = [l.strip() for l in lines[5:] if l.strip()]
        if not data_lines:
            data_lines = [l.strip() for l in lines[4:] if l.strip()]
        depths, areas_km2, vols_mcm = [], [], []
        for dl in data_lines:
            parts = dl.split(";")
            if len(parts) >= 3:
                try:
                    depths.append(float(parts[0]))
                    areas_km2.append(float(parts[1]))
                    vols_mcm.append(float(parts[2]))
                except ValueError:
                    continue
        if len(depths) < 3:
            continue

        grdl_area_m2 = np.array(areas_km2) * 1e6
        grdl_vol_m3 = np.array(vols_mcm) * 1e6
        c_grdl, b_grdl, r2_grdl = fit_power_law(grdl_area_m2, grdl_vol_m3)

        our_row = summary_df[summary_df["dam_id"] == mapped_id]
        eav_path = os.path.join(_cfg.EAV_DIR, f"{mapped_id}_eav.csv")
        if not os.path.exists(eav_path) or our_row.empty:
            continue

        our_eav = pd.read_csv(eav_path)
        our_row = our_row.iloc[0]

        comparisons.append({
            "name": stem.capitalize(),
            "dam_id": mapped_id,
            "grdl_depth": np.array(depths),
            "grdl_area_km2": np.array(areas_km2),
            "grdl_vol_mcm": np.array(vols_mcm),
            "c_grdl": c_grdl, "b_grdl": b_grdl, "r2_grdl": r2_grdl,
            "our_eav": our_eav,
            "our_row": our_row,
        })

    if not comparisons:
        return

    n_dams = len(comparisons)
    with mpl.rc_context(_ANALYSIS_RC):
        row_h = 5.0
        fig, axes = plt.subplots(n_dams, 2,
                                 figsize=(14.0, row_h * n_dams),
                                 tight_layout=True, squeeze=False)
        letters = "abcdefghijklmnopqrstuvwxyz"
        for i, comp in enumerate(comparisons):
            oeav = comp["our_eav"]
            orow = comp["our_row"]

            ax = axes[i, 0]
            _label_panel(ax, letters[2 * i])
            ax.plot(comp["grdl_area_km2"], comp["grdl_vol_mcm"],
                    color=NATURE_COLORS["blue"], marker="o", lw=1.2, ms=3, label="GRDL")
            ax.plot(oeav["area_m2"] / 1e6, oeav["volume_m3"] / 1e6,
                    color=NATURE_COLORS["vermillion"], lw=1.2, label="SRTM")
            ax.set_xlabel("Area (km\u00b2)")
            ax.set_ylabel("Volume (MCM)")
            ax.set_title(f"{comp['name']} ({comp['dam_id']}): Area\u2013Volume")
            ax.legend()
            ax.grid(True, ls="--", alpha=0.3, lw=0.4)

            ax = axes[i, 1]
            _label_panel(ax, letters[2 * i + 1])
            elev = oeav["elevation_m"].values
            depth = elev - elev.min()
            ax.plot(comp["grdl_area_km2"], comp["grdl_depth"],
                    color=NATURE_COLORS["blue"], marker="o", lw=1.2, ms=3, label="GRDL")
            ax.plot(oeav["area_m2"] / 1e6, depth,
                    color=NATURE_COLORS["vermillion"], lw=1.2, label="SRTM")
            ax.set_xlabel("Area (km\u00b2)")
            ax.set_ylabel("Depth (m)")
            ax.set_title(f"{comp['name']} ({comp['dam_id']}): Depth\u2013Area")
            ax.legend()
            ax.grid(True, ls="--", alpha=0.3, lw=0.4)

        plt.savefig(os.path.join(output_dir, "grdl_validation.png"),
                    dpi=300, bbox_inches="tight")
        plt.close(fig)


# ---------------------------------------------------------------------------
# Flood map (QC only — not publication, 100 DPI)
# ---------------------------------------------------------------------------

_QC_RC = {
    "font.size": 12,
    "axes.titlesize": 12,
    "axes.labelsize": 11,
    "xtick.labelsize": 10,
    "ytick.labelsize": 10,
    "legend.fontsize": 10,
    "axes.linewidth": 1.0,
}


def save_flood_map(result, flood_dir, dam_id=None, dam_name=None):
    file_label = dam_id if dam_id else result.get("dam_id", "unknown")
    dem = result["dem_utm"]
    fp = result["footprint"]
    dam_r, dam_c = result["dam_rc"]

    with mpl.rc_context(_QC_RC):
        fig, ax = plt.subplots(figsize=(10, 8), tight_layout=True)

        masked_dem = np.where(np.isnan(dem), np.nan, dem)
        im = ax.imshow(masked_dem, cmap="cubehelix", interpolation="nearest")
        cbar = plt.colorbar(im, ax=ax, shrink=0.8, pad=0.02)
        cbar.set_label("Elevation (m)")

        flood_overlay = np.ma.masked_where(~fp, np.ones_like(dem))
        ax.imshow(flood_overlay, cmap="Blues", alpha=0.8, interpolation="nearest")

        ax.plot(dam_c, dam_r, "v", color="red", markersize=10, markeredgecolor="k",
                markeredgewidth=0.8, zorder=10)

        river = result.get("flood_river_overlay")
        if river is not None:
            lc, lr = river["line_cc"], river["line_rr"]
            if lc.size >= 2:
                ax.plot(
                    lc, lr, color="cyan", lw=2.2, alpha=0.92, zorder=6,
                    solid_capstyle="round",
                )
            if river["arrow_cc"].size > 0:
                ax.quiver(
                    river["arrow_cc"],
                    river["arrow_rr"],
                    river["arrow_uc"],
                    river["arrow_vr"],
                    angles="xy",
                    scale_units="xy",
                    scale=1.0,
                    color="gold",
                    width=0.0045,
                    zorder=7,
                    headwidth=4.5,
                    headlength=5.0,
                    linewidth=0.4,
                    edgecolor="darkgoldenrod",
                )

        cap_tag = " [capped]" if result["capped"] else ""
        id_label = file_label
        if dam_name:
            id_label = f"{file_label}, {dam_name}"
        year = result.get("construction_year")
        year_tag = f"year={int(year)}" if year is not None and np.isfinite(year) else ""
        ax.set_title(f"{id_label}{cap_tag}\n"
                     f"{year_tag}\n"
                     f"A={result['footprint_area_km2']:.2f} km\u00b2, "
                     f"V={result['vol_m3'][-1]/1e6:.1f} MCM, "
                     f"Cap={result['capacity_mcm']:.1f} MCM")
        ax.set_xlabel("Column (px)")
        ax.set_ylabel("Row (px)")

        plt.savefig(os.path.join(flood_dir, f"{file_label}_flood.png"),
                    dpi=100, bbox_inches="tight")
        plt.close(fig)


# ---------------------------------------------------------------------------
# Threshold analysis (extracted from main)
# ---------------------------------------------------------------------------

def plot_threshold_analysis(summary_df, threshold_df, chosen_threshold, output_dir):
    """Two-panel threshold diagnostics figure."""
    with mpl.rc_context(_ANALYSIS_RC):
        fig, axes = plt.subplots(1, 2, figsize=(14.0, 5.0), tight_layout=True)

        ax = axes[0]
        _label_panel(ax, "a")
        for q, color in GRADE_COLORS.items():
            mask = summary_df["quality"] == q
            if mask.any():
                ax.scatter(
                    summary_df.loc[mask, "capacity_mcm"],
                    summary_df.loc[mask, "r_squared"],
                    c=color, label=f"Grade {q}", s=30, alpha=0.7,
                    edgecolors="k", lw=0.3,
                )
        ax.axvline(chosen_threshold, color=NATURE_COLORS["vermillion"], ls="--", lw=1,
                   label=f"Threshold = {chosen_threshold:.1f} MCM")
        ax.set_xscale("log")
        ax.set_xlabel("Storage capacity (MCM)")
        ax.set_ylabel("R\u00b2")
        ax.set_title("Fit quality vs dam size")
        ax.legend()
        ax.grid(True, ls="--", alpha=0.3, lw=0.4)

        ax = axes[1]
        _label_panel(ax, "b")
        ax.plot(threshold_df["threshold_mcm"], threshold_df["frac_reliable"],
                color=NATURE_COLORS["blue"], marker="o", ms=3, lw=1, label="Fraction reliable")
        ax.set_xlabel("Capacity threshold (MCM)")
        ax.set_ylabel("Fraction reliable")
        ax.axvline(chosen_threshold, color=NATURE_COLORS["vermillion"], ls="--", lw=1)
        ax.grid(True, ls="--", alpha=0.3, lw=0.4)
        ax2 = ax.twinx()
        ax2.bar(threshold_df["threshold_mcm"], threshold_df["n_above"],
                width=0.4, alpha=0.3, color="gray", label="N dams above")
        ax2.set_ylabel("Number of dams")
        ax.set_title("Threshold selection")

        plt.savefig(os.path.join(output_dir, "threshold_analysis.png"),
                    dpi=300, bbox_inches="tight")
        plt.close(fig)


# ---------------------------------------------------------------------------
# Regression diagnostics (extracted from main)
# ---------------------------------------------------------------------------

def plot_regression_diagnostics(
    y, best_preds, train_clean, features, importances,
    best_model_name, best_r2_val, output_dir,
):
    """Three-panel regression diagnostics figure."""
    with mpl.rc_context(_ANALYSIS_RC):
        fig, axes = plt.subplots(1, 3, figsize=(18.0, 5.0), tight_layout=True)

        ax = axes[0]
        _label_panel(ax, "a")
        sc = ax.scatter(y, best_preds, c=train_clean["capacity_mcm"].values,
                        cmap="viridis", edgecolors="k", s=30, alpha=0.8, lw=0.3)
        lims = [min(y.min(), best_preds.min()) - 0.05,
                max(y.max(), best_preds.max()) + 0.05]
        ax.plot(lims, lims, color=NATURE_COLORS["vermillion"], ls="--", lw=0.8)
        ax.set_xlabel("Observed $b$")
        ax.set_ylabel("Predicted $b$ (LOO)")
        ax.set_title(f"{best_model_name}: R\u00b2 = {best_r2_val:.3f}")
        plt.colorbar(sc, ax=ax, shrink=0.8).set_label("Capacity (MCM)")
        ax.grid(True, ls="--", alpha=0.3, lw=0.4)

        ax = axes[1]
        _label_panel(ax, "b")
        ax.barh(features, importances, color=NATURE_COLORS["blue"], edgecolor="k", lw=0.4)
        ax.set_xlabel(
            "Importance" if best_model_name == "random_forest"
            else "Normalised |coefficient|"
        )
        ax.set_title("Feature importances")

        ax = axes[2]
        _label_panel(ax, "c")
        residuals = y - best_preds
        ax.scatter(train_clean["capacity_mcm"].values, residuals,
                   c=NATURE_COLORS["blue"], edgecolors="k", s=25, alpha=0.7, lw=0.3)
        ax.axhline(0, color=NATURE_COLORS["vermillion"], ls="--", lw=0.8)
        ax.set_xlabel("Capacity (MCM)")
        ax.set_ylabel("Residual (obs \u2212 pred)")
        ax.set_title("Residuals vs capacity")
        ax.grid(True, ls="--", alpha=0.3, lw=0.4)

        plt.savefig(os.path.join(output_dir, "regression_diagnostics.png"),
                    dpi=300, bbox_inches="tight")
        plt.close(fig)
