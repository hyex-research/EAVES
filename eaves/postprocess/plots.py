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

        wall_vec = result.get("wall_vec")
        eff_length_m = result.get("eff_length_m")
        pixel_size = result.get("pixel_size")
        if wall_vec is not None and eff_length_m and pixel_size:
            half_len_px = (float(eff_length_m) / float(pixel_size)) / 2.0
            wr, wc = wall_vec
            r1 = dam_r - wr * half_len_px
            c1 = dam_c - wc * half_len_px
            r2 = dam_r + wr * half_len_px
            c2 = dam_c + wc * half_len_px
            ax.plot([c1, c2], [r1, r2], color="darkorange", lw=2.2, alpha=0.95,
                    solid_capstyle="round", zorder=9)

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
