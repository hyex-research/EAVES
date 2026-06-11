"""Panel s2 -- supplementary: capacity-threshold sweep for the reliability cut.

Two questions:

1.  How does fit quality (``r_squared``) vary with reservoir size? Smaller
    reservoirs are systematically harder for SRTM to resolve.
2.  Where should the capacity cutoff for the reliable / training subset
    sit? The chosen threshold is the smallest one sustaining at least 80%
    reliability over at least 30 dams (1 MCM on the Saudi domain).

Reads:

- ``<CSV_DIR>/eaves_summary.csv``        (per-dam fit quality + grade)
- ``<CSV_DIR>/threshold_analysis.csv``   (threshold sweep written by
  :func:`eaves.postprocess.regionalization.run_regionalization`)
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

import eaves.config as _cfg

from ._shared import apply_style, mm_to_in, panel_label, save_panel


_GRADE_COLORS = {
    "A": "#4C78A8",   # blue
    "B": "#54A24B",   # green
    "C": "#F58518",   # orange
    "D": "#E45756",   # red
    "F": "#54585A",   # dark grey
}


def _chosen_threshold(threshold_df: pd.DataFrame, default_mcm: float = 5.0) -> float:
    """Mirror ``regionalization.run_regionalization``'s selection rule."""
    primary = threshold_df[
        (threshold_df["frac_reliable"] >= 0.80)
        & (threshold_df["n_above"] >= 30)
    ]
    if len(primary) > 0:
        return float(primary.iloc[0]["threshold_mcm"])
    fallback = threshold_df[
        (threshold_df["frac_reliable"] >= 0.70)
        & (threshold_df["n_above"] >= 20)
    ]
    if len(fallback) > 0:
        return float(fallback.iloc[0]["threshold_mcm"])
    return default_mcm


def make_s2_threshold(out_dir: Path) -> Path:
    apply_style()

    summary_df = pd.read_csv(os.path.join(_cfg.CSV_DIR, "eaves_summary.csv"))
    threshold_df = pd.read_csv(os.path.join(_cfg.CSV_DIR, "threshold_analysis.csv"))
    cutoff = _chosen_threshold(threshold_df)

    import matplotlib.pyplot as plt

    # Uniform 10 pt text across every element; panel labels overridden to 12.
    rc_override = {
        "font.size":       10,
        "axes.labelsize":  10,
        "axes.titlesize":  10,
        "xtick.labelsize": 10,
        "ytick.labelsize": 10,
        "legend.fontsize": 10,
    }
    rc_stack = plt.rc_context(rc_override)
    rc_stack.__enter__()

    fig_w = mm_to_in(220.0)
    fig_h = mm_to_in(95.0)
    fig, (ax_a, ax_b) = plt.subplots(1, 2, figsize=(fig_w, fig_h),
                                     gridspec_kw={"width_ratios": [1.35, 1.0]})
    fig.subplots_adjust(left=0.07, right=0.93, top=0.90, bottom=0.13,
                        wspace=0.45)

    # ---- panel a: R^2 vs capacity, colored by quality grade ----
    s = summary_df[summary_df["capacity_mcm"] > 0].copy()
    for grade in ["A", "B", "C", "D", "F"]:
        sub = s[s["quality"] == grade]
        if len(sub) == 0:
            continue
        ax_a.scatter(
            sub["capacity_mcm"], sub["r_squared"],
            s=10, color=_GRADE_COLORS[grade], alpha=0.75,
            edgecolor="none", label=f"grade {grade}  (n = {len(sub)})",
        )

    ax_a.axvline(cutoff, color="0.30", linewidth=0.9, linestyle="--",
                 zorder=1, label=f"threshold = {cutoff:.1f} MCM")
    ax_a.axhline(0.98, color="0.55", linewidth=0.7, linestyle=":", zorder=1)
    ax_a.text(
        s["capacity_mcm"].max() * 0.7, 0.9805,
        r"$R^2 = 0.98$ reliability cut",
        color="0.40", va="bottom", ha="right",
    )

    ax_a.set_xscale("log")
    ax_a.set_xlabel("Storage capacity (MCM)")
    ax_a.set_ylabel(r"Fit quality $R^2$")
    ax_a.grid(True, linewidth=0.3, color="0.88")
    ax_a.set_axisbelow(True)
    ax_a.legend(loc="lower right", frameon=True, framealpha=0.95)
    ax_a.set_ylim(max(0.85, float(s["r_squared"].quantile(0.02)) - 0.01), 1.005)

    # ---- panel b: fraction reliable vs threshold + n_above bars ----
    t = threshold_df.sort_values("threshold_mcm")
    ax_b_bars = ax_b.twinx()
    ax_b_bars.bar(
        t["threshold_mcm"], t["n_above"],
        width=0.4, color="0.82", edgecolor="none", zorder=1,
    )
    ax_b_bars.set_ylabel("Number of dams above threshold")

    ax_b.plot(t["threshold_mcm"], t["frac_reliable"],
              color="#D62728", marker="o", markersize=3.2, linewidth=1.2,
              zorder=3, label="fraction reliable")
    ax_b.axvline(cutoff, color="0.30", linewidth=0.9, linestyle="--",
                 zorder=2, label=f"chosen = {cutoff:.1f} MCM")

    ax_b.set_xlabel("Capacity threshold (MCM)")
    ax_b.set_ylabel("Fraction reliable\n"
                    "(grade A/B, $R^2 \\geq 0.98$, "
                    "$v_\\mathrm{ratio} \\in [0.3, 5]$, $\\geq 50$ px)")
    ax_b.set_ylim(0.84, 1.0)
    ax_b.set_zorder(ax_b_bars.get_zorder() + 1)
    ax_b.patch.set_visible(False)
    ax_b.grid(True, linewidth=0.3, color="0.88")
    ax_b.set_axisbelow(True)
    ax_b.legend(loc="upper right", frameon=True, framealpha=0.95)

    panel_label(ax_a, "a", fontsize=12, y_offset_pt=8.0)
    panel_label(ax_b, "b", fontsize=12, y_offset_pt=8.0)

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_png = out_dir / "s2_threshold_analysis.png"
    # Open axes on panel a (panel b keeps its right spine for the twin bar axis).
    ax_a.spines["top"].set_visible(False)
    ax_a.spines["right"].set_visible(False)
    ax_b.spines["top"].set_visible(False)
    ax_b_bars.spines["top"].set_visible(False)

    save_panel(fig, out_png)
    plt.close(fig)
    rc_stack.__exit__(None, None, None)
    return out_png
