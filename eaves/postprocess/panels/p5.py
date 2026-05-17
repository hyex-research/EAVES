"""Panel set p5 -- regionalization accuracy.

Single-method validation panel for the regionalization recipe shipped in
``regionalization.py``. The recipe anchors each non-trusted dam's
area--volume curve at ``A_cap = exp(alpha + beta * log V_cap)`` -- a log--log
fit of the DEM full-pool area against catalogue capacity trained on the
trusted SRTM-derived dams -- and back-solves the coefficient
``c = V_cap / A_cap^b``. Accuracy is measured by leave-one-out cross-
validation on the 320 trusted dams: each in turn is masked, the recipe is
re-trained on the remaining 319 and re-predicted, and the resulting curve is
compared against the SRTM "truth".

Panel a -- Predicted vs SRTM-truth volume at the dam's DEM full-pool area
           on log axes, with the 1:1 identity and shaded ±factor-2 and
           dashed ±factor-3 bands. Boxed stats give the headline accuracy
           numbers.
Panel b -- Signed prediction error distribution (log10 V_pred / V_SRTM in
           dex), with the zero line, the median, and the ±1-sigma band
           marked.
Panel c -- Error stability across the catalogue: signed error vs catalogue
           capacity, scatter plus a robust binned median line, on the same
           y axis as panel b so spreads are directly comparable.

Source: ``<CSV_DIR>/validation/regionalization_loo.csv`` written by
``python -m eaves.postprocess.validation --settings <region>.json``.
"""

from __future__ import annotations

import os
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import eaves.config as _cfg

from ._shared import (
    P4_BLUE,
    mm_to_in,
    panel_label,
    save_panel,
)


# Which recipe is the "final" one. Keeping this configurable so the panel
# tracks whatever the regionalization module actually ships with.
_METHOD_PREFIX = "multi"

_FRAC = 100      # evaluate at DEM full pool
_VCOL = f"{_METHOD_PREFIX}_V_at_{_FRAC:03d}pct_m3"
_RATIOCOL = f"{_METHOD_PREFIX}_log10_V_ratio_at_{_FRAC:03d}pct"


def _loo_csv() -> Path:
    return Path(_cfg.CSV_DIR) / "validation" / "regionalization_loo.csv"


def _load_loo() -> pd.DataFrame:
    p = _loo_csv()
    if not p.exists():
        raise RuntimeError(
            f"Missing {p}. Run: python -m eaves.postprocess.validation "
            f"--settings <settings>.json"
        )
    return pd.read_csv(p)


def _accuracy_stats(df: pd.DataFrame) -> dict:
    v_true = (df["V_srtm_at_100pct_m3"] / 1e6).values
    v_pred = (df[_VCOL] / 1e6).values
    m = (v_true > 0) & (v_pred > 0) & np.isfinite(v_true) & np.isfinite(v_pred)
    r = np.log10(v_pred[m]) - np.log10(v_true[m])
    return {
        "n": int(len(r)),
        "median": float(np.median(r)),
        "p16": float(np.quantile(r, 0.16)),
        "p84": float(np.quantile(r, 0.84)),
        "mae": float(np.mean(np.abs(r))),
        "rmse": float(np.sqrt(np.mean(r ** 2))),
        "within_2x": 100.0 * float(np.mean(np.abs(r) <= np.log10(2.0))),
        "within_3x": 100.0 * float(np.mean(np.abs(r) <= np.log10(3.0))),
        "within_10x": 100.0 * float(np.mean(np.abs(r) <= np.log10(10.0))),
        "v_true": v_true[m],
        "v_pred": v_pred[m],
        "residuals_dex": r,
    }


def _draw_panel_a(ax, stats: dict) -> None:
    v_true = stats["v_true"]
    v_pred = stats["v_pred"]

    lo = max(1e-3, min(v_true.min(), v_pred.min()) * 0.5)
    hi = max(v_true.max(), v_pred.max()) * 2.0
    grid = np.geomspace(lo, hi, 200)

    ax.fill_between(grid, grid / 2.0, grid * 2.0,
                    color="0.85", alpha=0.40, zorder=0, label="±factor 2")
    ax.plot(grid, grid * 3.0, color="0.55", lw=0.6, ls=":", zorder=2)
    ax.plot(grid, grid / 3.0, color="0.55", lw=0.6, ls=":", zorder=2,
            label="±factor 3")
    ax.plot(grid, grid, color="black", lw=1.3, zorder=4, label="1 : 1")

    ax.scatter(
        v_true, v_pred,
        s=18, color=P4_BLUE, alpha=0.65, edgecolor="white", linewidth=0.3,
        zorder=3,
    )

    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlim(lo, hi)
    ax.set_ylim(lo, hi)
    ax.set_xlabel(r"SRTM truth volume at $A_\mathrm{DEM}$  (MCM)", fontsize=10)
    ax.set_ylabel(r"Regionalised volume at $A_\mathrm{DEM}$  (MCM)", fontsize=10)
    ax.tick_params(labelsize=10, length=2.5)
    ax.grid(True, which="both", ls=":", lw=0.4, alpha=0.5)

    leg = ax.legend(loc="lower right", frameon=False, fontsize=10,
                    handlelength=1.4, labelspacing=0.3)
    for t in leg.get_texts():
        t.set_color("0.10")

    factor = 10 ** stats["median"]
    txt = (
        f"n                    = {stats['n']}\n"
        f"median bias   = {stats['median']:+.2f} dex  (×{factor:.2f})\n"
        f"MAE               = {stats['mae']:.2f} dex\n"
        f"RMSE             = {stats['rmse']:.2f} dex\n"
        f"within 2×       = {stats['within_2x']:.0f}%\n"
        f"within 3×       = {stats['within_3x']:.0f}%\n"
        f"within 10×     = {stats['within_10x']:.0f}%"
    )
    ax.text(
        0.03, 0.97, txt,
        transform=ax.transAxes, ha="left", va="top",
        fontsize=10, color="0.10",
        bbox=dict(boxstyle="round,pad=0.3", facecolor="white",
                  edgecolor="0.7", linewidth=0.5, alpha=0.55),
    )

    panel_label(ax, "a", fontsize=12)


def _draw_panel_b(ax, stats: dict) -> None:
    r = stats["residuals_dex"]
    edges = np.linspace(-1.5, 1.5, 41)

    ax.hist(
        r, bins=edges,
        color=P4_BLUE, alpha=0.7, edgecolor="white", linewidth=0.3,
        zorder=2,
    )
    ax.axvline(0.0, color="black", lw=1.3, zorder=4, label="zero error")
    ax.axvline(stats["median"], color="red", lw=1.4, ls="--", zorder=4,
               label=f"median =\n{stats['median']:+.2f} dex")
    ax.axvspan(stats["p16"], stats["p84"], color="red", alpha=0.10, zorder=1,
               label=f"P16–P84:\n[{stats['p16']:+.2f}, {stats['p84']:+.2f}]")
    ax.axvline(np.log10(2.0), color="0.45", lw=0.6, ls=":", zorder=3)
    ax.axvline(-np.log10(2.0), color="0.45", lw=0.6, ls=":", zorder=3)

    ax.set_xlim(edges[0], edges[-1])
    ax.set_xlabel(r"$\log_{10}(V_\mathrm{pred}\,/\,V_\mathrm{SRTM})$  at $A_\mathrm{DEM}$  (dex)",
                  fontsize=10)
    ax.set_ylabel("Number of dams", fontsize=10)
    ax.tick_params(labelsize=10, length=2.5)
    ax.grid(True, ls=":", lw=0.4, alpha=0.5)

    ax.text(np.log10(2.0), ax.get_ylim()[1] * 0.97,
            " ±factor 2", color="0.45", fontsize=10, ha="left", va="top")
    ax.text(-np.log10(2.0), ax.get_ylim()[1] * 0.97,
            "±factor 2 ", color="0.45", fontsize=10, ha="right", va="top")

    leg = ax.legend(loc="center left", frameon=False, fontsize=10,
                    handlelength=1.4, labelspacing=0.3)
    for t in leg.get_texts():
        t.set_color("0.10")

    panel_label(ax, "b", fontsize=12)


def _draw_panel_c(ax, df: pd.DataFrame, stats: dict) -> None:
    d = df.dropna(subset=["capacity_mcm", _RATIOCOL]).copy()
    d = d[d["capacity_mcm"] > 0]
    cap = d["capacity_mcm"].values
    err = d[_RATIOCOL].values

    ax.scatter(
        cap, err,
        s=14, color=P4_BLUE, alpha=0.5,
        edgecolor="white", linewidth=0.25, zorder=2,
    )

    ax.axhline(0.0, color="black", lw=1.2, zorder=4)
    ax.axhline(np.log10(2.0), color="0.45", lw=0.6, ls=":", zorder=3)
    ax.axhline(-np.log10(2.0), color="0.45", lw=0.6, ls=":", zorder=3)
    ax.axhline(np.log10(3.0), color="0.55", lw=0.6, ls=":", zorder=3)
    ax.axhline(-np.log10(3.0), color="0.55", lw=0.6, ls=":", zorder=3)

    edges = np.geomspace(max(cap.min(), 1e-3), cap.max(), 11)
    centres = np.sqrt(edges[:-1] * edges[1:])
    med, p16, p84, ns = [], [], [], []
    for a, b in zip(edges[:-1], edges[1:]):
        sub = err[(cap >= a) & (cap < b)]
        if len(sub) >= 3:
            med.append(float(np.median(sub)))
            p16.append(float(np.quantile(sub, 0.16)))
            p84.append(float(np.quantile(sub, 0.84)))
        else:
            med.append(np.nan); p16.append(np.nan); p84.append(np.nan)
        ns.append(len(sub))
    med = np.asarray(med); p16 = np.asarray(p16); p84 = np.asarray(p84)
    valid = np.isfinite(med)

    ax.fill_between(centres[valid], p16[valid], p84[valid],
                    color="red", alpha=0.13, zorder=3, label="binned P16–P84")
    ax.plot(centres[valid], med[valid], color="red", lw=1.8, marker="o", ms=4,
            mfc="white", mec="red", mew=1.0, zorder=5, label="binned median")

    ax.set_xscale("log")
    ax.set_ylim(-1.5, 1.5)
    ax.set_xlabel("Catalogue capacity (MCM)", fontsize=10)
    ax.set_ylabel(r"$\log_{10}(V_\mathrm{pred}\,/\,V_\mathrm{SRTM})$  (dex)",
                  fontsize=10)
    ax.tick_params(labelsize=10, length=2.5)
    ax.grid(True, which="both", ls=":", lw=0.4, alpha=0.5)

    leg = ax.legend(loc="upper right", frameon=False, fontsize=10,
                    handlelength=1.4, labelspacing=0.3)
    for t in leg.get_texts():
        t.set_color("0.10")

    ax.text(
        0.03, 0.03,
        f"n = {stats['n']} dams\nbinned across decades of $V_\\mathrm{{cap}}$",
        transform=ax.transAxes, ha="left", va="bottom",
        fontsize=10, color="0.10",
        bbox=dict(boxstyle="round,pad=0.3", facecolor="white",
                  edgecolor="0.7", linewidth=0.5, alpha=0.9),
    )

    panel_label(ax, "c", fontsize=12)


def make_p5_validation(output_dir: str | os.PathLike) -> Path:
    """Render p5 (regionalization-accuracy panel for the shipped recipe)."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_png = out_dir / "p5_regionalization_validation.png"

    df = _load_loo()
    stats = _accuracy_stats(df)

    with plt.rc_context({
        "font.size":       10,
        "axes.labelsize":  10,
        "axes.titlesize":  10,
        "xtick.labelsize": 10,
        "ytick.labelsize": 10,
        "legend.fontsize": 10,
    }):
        fig = plt.figure(figsize=(mm_to_in(290), mm_to_in(105)))
        gs = fig.add_gridspec(
            1, 3,
            width_ratios=[1.30, 1.25, 1.00],
            wspace=0.24,
            left=0.05, right=0.985, top=0.90, bottom=0.12,
        )
        _draw_panel_a(fig.add_subplot(gs[0, 0]), stats)
        _draw_panel_b(fig.add_subplot(gs[0, 1]), stats)
        _draw_panel_c(fig.add_subplot(gs[0, 2]), df, stats)

        save_panel(fig, out_png)
    plt.close(fig)
    print(f"wrote {out_png}")
    return out_png
