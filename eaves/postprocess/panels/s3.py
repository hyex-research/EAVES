"""Panel s3 (supplementary): propagation of SRTM vertical error into recovered volume.

Per-reservoir SRTM vertical error is propagated through the per-dam pipeline
with a Monte Carlo ensemble. Each realization perturbs the DEM within
its vertical-error envelope and re-derives the volume. The resulting spread of
log10 V (``sigma_logV_realizations``, log10 units) measures how much DEM
noise alone moves the volume estimate, plotted here as a fractional volume
uncertainty.

Panel a: per-dam fractional volume uncertainty versus storage capacity
(log x), one point per dam, colored by capacity class, with the class median
drawn as a segment across the class capacity range and annotated. A dam with
fewer than ``_MIN_VALID_REALIZATIONS`` valid realizations is left out.

Panel b: the same spread summarized by capacity class, median and P16 to P84
range over the per-dam strip, with the medians annotated.

Reads:

- ``<CSV_DIR>/validation/dem_error_montecarlo.csv``
"""

from __future__ import annotations

import os
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import eaves.config as _cfg

from ._shared import COL_REGI, COL_SRTM, PANEL_TEXT_RC, mm_to_in, panel_label, save_panel

# Splits the capacity classes at the 1 and 5 MCM cuts of the catalog and colors them orange, SRTM blue and green from small to large
_CLASS_EDGES = [(-np.inf, 1.0), (1.0, 5.0), (5.0, np.inf)]
_CLASS_LABELS = ["< 1 MCM", "1–5 MCM", "≥ 5 MCM"]
_CLASS_LABELS_SHORT = ["< 1", "1–5", "≥ 5"]
_CLASS_COLORS = [COL_REGI, COL_SRTM, "#54A24B"]
_SIGMA = "sigma_logV_realizations"
# Fewest valid realizations a dam needs to enter the panel
_MIN_VALID_REALIZATIONS = 10
_YLABEL = "DEM-error volume uncertainty"


def _size_class(capacity_mcm: float) -> int:
    for i, (lo, hi) in enumerate(_CLASS_EDGES):
        if lo <= capacity_mcm < hi:
            return i
    return len(_CLASS_EDGES) - 1


# ---- Data ----

def _load_montecarlo() -> pd.DataFrame:
    """Reads the Monte Carlo table, keeps the dams with enough valid realizations and assigns the capacity class."""
    df = pd.read_csv(
        os.path.join(_cfg.CSV_DIR, "validation", "dem_error_montecarlo.csv")
    )
    df = df[(df["capacity_mcm"] > 0) & df[_SIGMA].notna()
            & (df["n_ok"] >= _MIN_VALID_REALIZATIONS)].copy()
    df["class_idx"] = df["capacity_mcm"].apply(_size_class)
    return df


# ---- Drawing ----

def _draw_panel_a(ax, df: pd.DataFrame, y_max: float) -> None:
    """Panel a, per-dam fractional volume uncertainty against capacity, with the class medians."""
    for i, label in enumerate(_CLASS_LABELS):
        sub = df[df["class_idx"] == i]
        ax.scatter(
            sub["capacity_mcm"], (10.0 ** sub[_SIGMA] - 1.0),
            s=22, color=_CLASS_COLORS[i], alpha=0.80, edgecolor="none",
            zorder=3, label=f"{label} (n = {len(sub)})",
        )
        if not len(sub):
            continue
        # Draws a segment at the class median across the class capacity range
        med = float(sub[_SIGMA].median())
        lo = float(sub["capacity_mcm"].min())
        hi = float(sub["capacity_mcm"].max())
        med_frac = 10.0 ** med - 1.0
        ax.plot([lo, hi], [med_frac, med_frac], color=_CLASS_COLORS[i],
                linewidth=2.2, alpha=0.95, zorder=2, solid_capstyle="round")
        ax.annotate(
            f"{med_frac:.2f}",
            xy=(np.sqrt(lo * hi), med_frac), xytext=(0, 6),
            textcoords="offset points", color="black", fontsize=10,
            ha="center", va="bottom",
        )

    ax.set_xscale("log")
    ax.set_xlabel("Storage capacity (MCM)", fontsize=10)
    ax.set_ylabel(_YLABEL, fontsize=10)
    ax.tick_params(labelsize=10, length=2.5)
    ax.grid(True, which="both", linewidth=0.3, color="0.88")
    ax.set_axisbelow(True)
    ax.set_ylim(0.0, y_max)
    ax.legend(loc="upper right", frameon=False, fontsize=10,
              handlelength=1.2, handletextpad=0.4, labelspacing=0.25,
              borderaxespad=0.2)
    panel_label(ax, "a", fontsize=12)


def _draw_panel_b(ax, df: pd.DataFrame, y_max: float) -> None:
    """Panel b, median and P16 to P84 range per capacity class over the per-dam strip."""
    xs = np.arange(len(_CLASS_LABELS))
    for i in range(len(_CLASS_LABELS)):
        sub = df[df["class_idx"] == i]
        if not len(sub):
            continue
        vals = (10.0 ** sub[_SIGMA].values - 1.0)
        med = float(np.median(vals))
        p16 = float(np.quantile(vals, 0.16))
        p84 = float(np.quantile(vals, 0.84))
        # Draws a jittered per-dam strip behind the summary marker
        jitter = (np.random.default_rng(i).random(len(vals)) - 0.5) * 0.18
        ax.scatter(xs[i] + jitter, vals, s=14, color=_CLASS_COLORS[i],
                   alpha=0.40, edgecolor="none", zorder=2)
        ax.errorbar(
            xs[i], med, yerr=[[med - p16], [p84 - med]],
            fmt="o", markersize=8, color=_CLASS_COLORS[i],
            ecolor=_CLASS_COLORS[i], elinewidth=1.6, capsize=5,
            capthick=1.6, zorder=4,
        )
        ax.annotate(
            f"{med:.2f}",
            xy=(xs[i], p84), xytext=(0, 7),
            textcoords="offset points", color="black", fontsize=10,
            ha="center", va="bottom",
        )

    ax.set_xticks(xs)
    ax.set_xticklabels(_CLASS_LABELS_SHORT)
    ax.set_xlim(-0.5, len(xs) - 0.5)
    ax.set_xlabel("Capacity class (MCM)", fontsize=10)
    ax.set_ylabel(_YLABEL, fontsize=10)
    ax.tick_params(labelsize=10, length=2.5)
    ax.set_ylim(0.0, y_max)
    ax.grid(True, axis="y", linewidth=0.3, color="0.88")
    ax.set_axisbelow(True)
    panel_label(ax, "b", fontsize=12)


def make_s3_dem_error(out_dir: Path) -> Path:
    """Renders s3, the per-dam DEM-error volume uncertainty and its by-class summary in one row.

    Panel a: per-dam uncertainty against storage capacity with the class medians.
    Panel b: median and P16 to P84 range per capacity class.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_png = out_dir / "s3_dem_error.png"

    df = _load_montecarlo()
    # Shares one y range across the two panels, ending just above the largest per-dam value
    y_max = (10.0 ** float(df[_SIGMA].max()) - 1.0) * 1.05

    with plt.rc_context(PANEL_TEXT_RC):
        fig = plt.figure(figsize=(mm_to_in(187.0), mm_to_in(90.0)))
        gs = fig.add_gridspec(
            1, 2,
            width_ratios=[1.7, 1.0],
            wspace=0.25,
            left=0.075, right=0.981, top=0.93, bottom=0.14,
        )
        _draw_panel_a(fig.add_subplot(gs[0, 0]), df, y_max)
        _draw_panel_b(fig.add_subplot(gs[0, 1]), df, y_max)

        # Opens the axes by hiding the top and right spines
        for _ax in fig.axes:
            _ax.spines["top"].set_visible(False)
            _ax.spines["right"].set_visible(False)

        save_panel(fig, out_png)
    plt.close(fig)
    return out_png
