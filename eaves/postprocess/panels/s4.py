"""Panel s4 -- supplementary: DEM vertical-error Monte-Carlo on V.

Per-reservoir SRTM vertical error is propagated through the area--volume
recipe with a Monte-Carlo ensemble. Each realization perturbs the DEM within
its vertical-error envelope and re-derives the volume. The resulting spread of
$\\log_{10}V$ (``sigma_logV_realizations``, log10 units) measures how much DEM
noise alone moves the volume estimate, plotted here as a fractional volume
uncertainty.

Panel a -- per-dam fractional volume uncertainty versus storage capacity
(log x), one point per dam, colored by size class. The DEM-error spread is the
leading term for small reservoirs (~0.79) and sub-dominant for medium and large
ones (~0.14-0.25), where many pixels average the noise out. One dam (id_100017) with
only 5 valid realizations is excluded as unreliable.

Panel b -- by-size-class summary: median $\\pm$ P16-P84 of
``sigma_logV_realizations`` for the three capacity classes, with the per-class
medians annotated.

Reads:

- ``<CSV_DIR>/validation/dem_error_montecarlo.csv``
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd

import eaves.config as _cfg

from ._shared import COL_REGI, COL_SRTM, apply_style, mm_to_in, panel_label, save_panel


# Size classes use the catalog's 1 and 5 MCM cuts (same as report.py and Supp Note F).
# Colors: small reservoirs orange (DEM error dominates), larger classes SRTM blue family.
_CLASS_EDGES = [(-np.inf, 1.0), (1.0, 5.0), (5.0, np.inf)]
_CLASS_LABELS = [r"$<1$ MCM", r"$1$-$5$ MCM", r"$\geq 5$ MCM"]
_CLASS_LABELS_SHORT = [r"$<1$", r"$1$-$5$", r"$\geq 5$"]
_CLASS_KEYS = ["low", "mid", "high"]
_CLASS_COLORS = [COL_REGI, COL_SRTM, "#54A24B"]
_SIGMA = "sigma_logV_realizations"
# id_100017: spurious factor-6 spread from only 5 valid realizations; dropped.
_DROP_DAM = "id_100017"


def _size_class(capacity_mcm: float) -> int:
    for i, (lo, hi) in enumerate(_CLASS_EDGES):
        if lo <= capacity_mcm < hi:
            return i
    return len(_CLASS_EDGES) - 1


def make_s4_dem_error(out_dir: Path) -> Path:
    apply_style()

    df = pd.read_csv(
        os.path.join(_cfg.CSV_DIR, "validation", "dem_error_montecarlo.csv")
    )
    df = df[(df["capacity_mcm"] > 0) & df[_SIGMA].notna()
            & (df["dam_id"] != _DROP_DAM)].copy()
    df["class_idx"] = df["capacity_mcm"].apply(_size_class)

    import matplotlib.pyplot as plt

    # Uniform 12 pt text across every element; panel labels overridden to 14.
    rc_override = {
        "font.size":       12,
        "axes.labelsize":  12,
        "axes.titlesize":  12,
        "xtick.labelsize": 12,
        "ytick.labelsize": 12,
        "legend.fontsize": 12,
    }
    rc_stack = plt.rc_context(rc_override)
    rc_stack.__enter__()

    fig_w = mm_to_in(250.0)
    fig_h = mm_to_in(95.0)
    fig, (ax_a, ax_b) = plt.subplots(1, 2, figsize=(fig_w, fig_h),
                                     gridspec_kw={"width_ratios": [1.7, 1.0]})
    fig.subplots_adjust(left=0.075, right=0.985, top=0.90, bottom=0.13,
                        wspace=0.30)

    # ---- panel a: per-dam sigma(log10 V) vs capacity ----
    medians = []
    for i, key in enumerate(_CLASS_KEYS):
        sub = df[df["class_idx"] == i]
        med = float(sub[_SIGMA].median()) if len(sub) else np.nan
        medians.append(med)
        ax_a.scatter(
            sub["capacity_mcm"], (10.0 ** sub[_SIGMA] - 1.0),
            s=22, color=_CLASS_COLORS[i], alpha=0.80, edgecolor="none",
            zorder=3, label=f"{_CLASS_LABELS[i]}  ($n = {len(sub)}$)",
        )
        # Horizontal segment at the class median, spanning the class capacity range.
        if len(sub) and np.isfinite(med):
            lo = float(sub["capacity_mcm"].min())
            hi = float(sub["capacity_mcm"].max())
            med_frac = 10.0 ** med - 1.0
            ax_a.plot([lo, hi], [med_frac, med_frac], color=_CLASS_COLORS[i],
                      linewidth=2.2, alpha=0.95, zorder=2,
                      solid_capstyle="round")
            ax_a.annotate(
                rf"${med_frac:.2f}$",
                xy=(np.sqrt(lo * hi), med_frac), xytext=(0, 6),
                textcoords="offset points", color="black",
                ha="center", va="bottom",
            )

    ax_a.set_xscale("log")
    ax_a.set_xlabel("Storage capacity (MCM)")
    ax_a.set_ylabel("Median DEM-error volume uncertainty")
    ax_a.grid(True, which="both", linewidth=0.3, color="0.88")
    ax_a.set_axisbelow(True)
    ax_a.set_ylim(0.0, (10.0 ** float(df[_SIGMA].max()) - 1.0) * 1.05)
    ax_a.legend(loc="upper right", frameon=True, framealpha=0.95)

    # ---- panel b: by-size-class median +/- P16-P84 summary ----
    xs = np.arange(len(_CLASS_KEYS))
    for i, key in enumerate(_CLASS_KEYS):
        sub = df[df["class_idx"] == i]
        if not len(sub):
            continue
        vals = (10.0 ** sub[_SIGMA].values - 1.0)
        med = float(np.median(vals))
        p16 = float(np.quantile(vals, 0.16))
        p84 = float(np.quantile(vals, 0.84))
        # Per-point strip (jittered) behind the summary marker.
        jitter = (np.random.default_rng(i).random(len(vals)) - 0.5) * 0.18
        ax_b.scatter(xs[i] + jitter, vals, s=14, color=_CLASS_COLORS[i],
                     alpha=0.40, edgecolor="none", zorder=2)
        ax_b.errorbar(
            xs[i], med, yerr=[[med - p16], [p84 - med]],
            fmt="o", markersize=8, color=_CLASS_COLORS[i],
            ecolor=_CLASS_COLORS[i], elinewidth=1.6, capsize=5,
            capthick=1.6, zorder=4,
        )
        ax_b.annotate(
            rf"${med:.2f}$",
            xy=(xs[i], p84), xytext=(0, 7),
            textcoords="offset points", color="black",
            ha="center", va="bottom",
        )

    ax_b.set_xticks(xs)
    ax_b.set_xticklabels(_CLASS_LABELS_SHORT)
    ax_b.set_xlim(-0.5, len(xs) - 0.5)
    ax_b.set_xlabel("Capacity class (MCM)")
    ax_b.set_ylabel("Median volume uncertainty")
    ax_b.set_ylim(0.0, (10.0 ** float(df[_SIGMA].max()) - 1.0) * 1.05)
    ax_b.grid(True, axis="y", linewidth=0.3, color="0.88")
    ax_b.set_axisbelow(True)

    panel_label(ax_a, "a", fontsize=14, y_offset_pt=8.0)
    panel_label(ax_b, "b", fontsize=14, y_offset_pt=8.0)

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_png = out_dir / "s4_dem_error.png"
    # Open axes: no top/right spines.
    for _ax in fig.axes:
        _ax.spines["top"].set_visible(False)
        _ax.spines["right"].set_visible(False)

    save_panel(fig, out_png)
    plt.close(fig)
    rc_stack.__exit__(None, None, None)
    return out_png
