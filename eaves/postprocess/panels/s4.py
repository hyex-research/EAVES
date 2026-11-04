"""Panel s4 (supplementary): capacity-threshold sweep behind the training cut.

Panel a: fit quality (R^2) against storage capacity, colored by quality grade,
         with the R^2 reliability cut and the selected capacity cut marked.
Panel b: fraction of dams clearing the combined reliability gates against the
         candidate capacity cutoff, with the number of dams above each cutoff
         as bars and the selected cut marked. The selected cut is the lowest
         tested threshold with at least 30 dams at or above it and at least
         80% of them clearing the gates.

Reads:

- ``<CSV_DIR>/eaves_summary.csv``        (per-dam fit quality + grade)
- ``<CSV_DIR>/threshold_analysis.csv``   (threshold sweep written by
  :func:`eaves.postprocess.regionalization.run_regionalization`)
"""

from __future__ import annotations

import os
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

import eaves.config as _cfg

from ...utils import dams_with_fill
from ..regionalization import FALLBACK_RELIABILITY_THRESHOLD_MCM, choose_reliability_threshold
from ._shared import PANEL_TEXT_RC, _style_legend, mm_to_in, panel_label, save_panel

# ---- Style ----

_GRADE_COLORS = {
    "A": "#4C78A8",   # blue
    "B": "#54A24B",   # green
    "C": "#F58518",   # orange
    "D": "#E45756",   # red
    "F": "#54585A",   # dark gray
}
COL_CUT = "0.30"
COL_R2_CUT = "0.55"
COL_NOTE = "0.40"
COL_FRACTION = "#D62728"
COL_BARS = "0.82"


# ---- Data ----

def _load_threshold_data() -> tuple[pd.DataFrame, pd.DataFrame, float]:
    """Reads the per-dam summary of the dams with a fill, the threshold sweep and the cut that
    :func:`eaves.postprocess.regionalization.choose_reliability_threshold` selects on it."""
    summary_df = dams_with_fill(pd.read_csv(os.path.join(_cfg.CSV_DIR, "eaves_summary.csv")))
    summary_df = summary_df[summary_df["capacity_mcm"] > 0].copy()
    threshold_df = pd.read_csv(os.path.join(_cfg.CSV_DIR, "threshold_analysis.csv"))
    threshold_df = threshold_df.sort_values("threshold_mcm").reset_index(drop=True)
    chosen = choose_reliability_threshold(threshold_df)
    return summary_df, threshold_df, FALLBACK_RELIABILITY_THRESHOLD_MCM if chosen is None else chosen


# ---- Drawing ----

def _draw_panel_a(ax, summary_df: pd.DataFrame, cutoff: float) -> None:
    """Panel a, R^2 against storage capacity by quality grade, with the R^2 reliability cut and the selected capacity cut."""
    for grade, color in _GRADE_COLORS.items():
        sub = summary_df[summary_df["quality"] == grade]
        if len(sub) == 0:
            continue
        ax.scatter(
            sub["capacity_mcm"], sub["r_squared"],
            s=10, color=color, alpha=0.75, edgecolor="none",
            label=f"Grade {grade} (n = {len(sub)})",
        )

    ax.axvline(cutoff, color=COL_CUT, linewidth=0.9, linestyle="--", zorder=1)
    ax.text(
        cutoff * 1.12, 0.03, f"Selected cut\n({cutoff:.1f} MCM)",
        transform=ax.get_xaxis_transform(),
        fontsize=10, color=COL_NOTE, va="bottom", ha="left",
    )
    ax.axhline(0.98, color=COL_R2_CUT, linewidth=0.7, linestyle=":", zorder=1)
    ax.text(
        summary_df["capacity_mcm"].max() * 0.7, 0.9795,
        "$R^2 = 0.98$\nreliability cut",
        fontsize=10, color=COL_NOTE, va="top", ha="right",
    )

    ax.set_xscale("log")
    # The axis spans every fit, from just under the lowest R^2 to the top of the range
    ax.set_ylim(float(summary_df["r_squared"].min()) - 0.005, 1.001)
    ax.set_xlabel("Storage capacity (MCM)", fontsize=10)
    ax.set_ylabel(r"Fit quality $R^2$", fontsize=10)
    ax.tick_params(labelsize=10, length=2.5)
    ax.grid(True, linewidth=0.3, color="0.88")
    ax.set_axisbelow(True)
    # Key in the band the fits leave free right of the cut, under the two lowest fits of that band
    _style_legend(ax.legend(loc="lower right", bbox_to_anchor=(1.0, 0.26),
                            frameon=False, fontsize=10,
                            handlelength=1.0, handletextpad=0.4, labelspacing=0.25,
                            borderaxespad=0.1, borderpad=0.2))
    # Opens the axes
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    panel_label(ax, "a", fontsize=12)


def _draw_panel_b(ax, threshold_df: pd.DataFrame, cutoff: float) -> None:
    """Panel b, fraction reliable against the candidate cutoff, over the number of dams above each cutoff as bars."""
    ax_bars = ax.twinx()
    ax_bars.bar(
        threshold_df["threshold_mcm"], threshold_df["n_above"],
        width=0.4, color=COL_BARS, edgecolor="none", zorder=1,
    )
    ax_bars.set_ylabel("Number of dams above threshold", fontsize=10)
    ax_bars.tick_params(labelsize=10, length=2.5)

    ax.plot(threshold_df["threshold_mcm"], threshold_df["frac_reliable"],
            color=COL_FRACTION, marker="o", markersize=3.2, linewidth=1.2,
            zorder=3, label="Fraction reliable")
    ax.axvline(cutoff, color=COL_CUT, linewidth=0.9, linestyle="--", zorder=2,
               label=f"Selected cut\n({cutoff:.1f} MCM)")

    ax.set_ylim(0.84, 1.002)
    ax.set_xlabel("Capacity threshold (MCM)", fontsize=10)
    ax.set_ylabel("Fraction reliable (grade A/B, $R^2 \\geq 0.98$,\n"
                  "$V_\\mathrm{SRTM}/V_\\mathrm{cap} \\in [0.3, 5]$, $\\geq 50$ grid cells)",
                  fontsize=10)
    ax.tick_params(labelsize=10, length=2.5)
    # Draws the line axes over the bar axes
    ax.set_zorder(ax_bars.get_zorder() + 1)
    ax.patch.set_visible(False)
    ax.grid(True, linewidth=0.3, color="0.88")
    ax.set_axisbelow(True)
    # Key below the plateau of the fraction at 1, in the region the bars leave free
    _style_legend(ax.legend(loc="upper right", bbox_to_anchor=(1.0, 0.90),
                            frameon=False, fontsize=10,
                            handlelength=1.0, handletextpad=0.4, labelspacing=0.25,
                            borderaxespad=0.1, borderpad=0.2))
    # Opens the axes, the right spine stays for the bar axis
    ax.spines["top"].set_visible(False)
    ax_bars.spines["top"].set_visible(False)
    panel_label(ax, "b", fontsize=12)


def make_s4_threshold(out_dir: Path) -> Path:
    """Renders s4, the capacity-threshold sweep in one row.

    Panel a: R^2 against storage capacity by quality grade.
    Panel b: fraction reliable and number of dams against the candidate cutoff.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_png = out_dir / "s4_threshold_analysis.png"

    summary_df, threshold_df, cutoff = _load_threshold_data()

    with plt.rc_context(PANEL_TEXT_RC):
        fig = plt.figure(figsize=(mm_to_in(187.0), mm_to_in(90.0)))
        gs = fig.add_gridspec(
            1, 2,
            width_ratios=[1.33, 1.0],
            wspace=0.36,
            left=0.097, right=0.9119, top=0.92, bottom=0.13,
        )
        _draw_panel_a(fig.add_subplot(gs[0, 0]), summary_df, cutoff)
        _draw_panel_b(fig.add_subplot(gs[0, 1]), threshold_df, cutoff)
        save_panel(fig, out_png)
    plt.close(fig)
    return out_png
