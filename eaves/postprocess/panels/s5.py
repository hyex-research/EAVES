"""Panel s5 -- supplementary: magic-number sensitivity sweep.

Three internal pipeline constants (``ALIGN_WEIGHT``, ``MAX_CREST_FLOW_DOT``,
``VOID_THRESHOLD``) are each perturbed by $\\pm 20\\%$ and $\\pm 30\\%$ about
their baseline values, and the pipeline is re-run end-to-end. Two outputs are
tracked: the fraction of dams that remain in the trusted subset
(``frac_trusted``) and the median area--volume exponent over that subset
(``median_b_trusted``).

Panel a -- ``frac_trusted`` versus perturbation fraction, one line per
constant, with the baseline (perturbation 0) marked and a horizontal
reference at the $0.92$ retention floor.

Panel b -- ``median_b_trusted`` versus perturbation fraction, one line per
constant, with the baseline median $b$ marked. Outputs barely move: the
trusted fraction stays $\\geq 0.92$ and the median $b$ stays within $0.01$ of
baseline.

Reads:

- ``<CSV_DIR>/validation/sensitivity_sweep.csv``
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

import eaves.config as _cfg

from ._shared import COL_REGI, COL_SRTM, apply_style, mm_to_in, panel_label, save_panel


# One color + marker per perturbed constant.
_CONST_STYLE = {
    "ALIGN_WEIGHT":       (COL_SRTM, "o"),
    "MAX_CREST_FLOW_DOT": (COL_REGI, "s"),
    "VOID_THRESHOLD":     ("#54A24B", "^"),
}
# Human-readable legend labels (no underscores in figure text).
_CONST_LABEL = {
    "ALIGN_WEIGHT":       "alignment weight",
    "MAX_CREST_FLOW_DOT": "maximum crest-flow dot product",
    "VOID_THRESHOLD":     "void-fraction threshold",
}
_FRAC_FLOOR = 0.92


def make_s5_sensitivity(out_dir: Path) -> Path:
    apply_style()

    df = pd.read_csv(
        os.path.join(_cfg.CSV_DIR, "validation", "sensitivity_sweep.csv")
    )
    base = df[df["constant"] == "baseline"]
    base_frac = float(base["frac_trusted"].iloc[0]) if len(base) else None
    base_b = float(base["median_b_trusted"].iloc[0]) if len(base) else None

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
    fig_h = mm_to_in(110.0)
    fig, (ax_a, ax_b) = plt.subplots(1, 2, figsize=(fig_w, fig_h))
    fig.subplots_adjust(left=0.085, right=0.985, top=0.93, bottom=0.26,
                        wspace=0.28)

    constants = [c for c in _CONST_STYLE if c in set(df["constant"])]

    # ---- panel a: frac_trusted vs perturbation ----
    for const in constants:
        color, marker = _CONST_STYLE[const]
        sub = df[df["constant"] == const].sort_values("perturbation_frac")
        ax_a.plot(sub["perturbation_frac"], sub["frac_trusted"],
                  color=color, marker=marker, markersize=5.5, linewidth=1.4,
                  zorder=3, label=_CONST_LABEL.get(const, const))

    ax_a.axhline(_FRAC_FLOOR, color="0.35", linewidth=0.9, linestyle=":",
                 zorder=2)
    ax_a.text(0.30, _FRAC_FLOOR - 0.004,
              rf"retention floor $= {_FRAC_FLOOR:.2f}$",
              color="0.30", ha="right", va="top")
    if base_frac is not None:
        ax_a.scatter([0.0], [base_frac], s=70, facecolor="white",
                     edgecolor="0.15", linewidth=1.2, zorder=5,
                     label="baseline")

    ax_a.set_xlabel("Perturbation fraction")
    ax_a.set_ylabel("Fraction trusted")
    ax_a.set_ylim(0.88, 1.01)
    ax_a.grid(True, linewidth=0.3, color="0.88")
    ax_a.set_axisbelow(True)

    # ---- panel b: median_b_trusted vs perturbation ----
    for const in constants:
        color, marker = _CONST_STYLE[const]
        sub = df[df["constant"] == const].sort_values("perturbation_frac")
        ax_b.plot(sub["perturbation_frac"], sub["median_b_trusted"],
                  color=color, marker=marker, markersize=5.5, linewidth=1.4,
                  zorder=3, label=_CONST_LABEL.get(const, const))

    if base_b is not None:
        ax_b.axhline(base_b, color="0.35", linewidth=0.9, linestyle="--",
                     zorder=2)
        ax_b.scatter([0.0], [base_b], s=70, facecolor="white",
                     edgecolor="0.15", linewidth=1.2, zorder=5,
                     label=f"baseline ($b = {base_b:.3f}$)")
        # +/- 0.01 envelope so a reader sees the outputs stay within 0.01.
        ax_b.axhspan(base_b - 0.01, base_b + 0.01, color="0.85", alpha=0.45,
                     zorder=1)

    ax_b.set_xlabel("Perturbation fraction")
    ax_b.set_ylabel(r"Median $b$ over trusted subset")
    ax_b.grid(True, linewidth=0.3, color="0.88")
    ax_b.set_axisbelow(True)
    if base_b is not None:
        ax_b.set_ylim(base_b - 0.03, base_b + 0.03)
    # One shared legend below both panels; the long constant names do not fit per-panel boxes.
    handles, labels = ax_a.get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=4,
               frameon=True, framealpha=0.95, bbox_to_anchor=(0.5, 0.0))

    panel_label(ax_a, "a", fontsize=14, y_offset_pt=8.0)
    panel_label(ax_b, "b", fontsize=14, y_offset_pt=8.0)

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_png = out_dir / "s5_sensitivity.png"
    # Open axes: no top/right spines.
    for _ax in fig.axes:
        _ax.spines["top"].set_visible(False)
        _ax.spines["right"].set_visible(False)

    save_panel(fig, out_png)
    plt.close(fig)
    rc_stack.__exit__(None, None, None)
    return out_png
