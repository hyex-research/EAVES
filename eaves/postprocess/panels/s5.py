"""Panel s5 (supplementary): sensitivity sweep of the placement and drainage constants.

Five internal pipeline constants (``ALIGN_WEIGHT``, ``MAX_CREST_FLOW_DOT``,
``VOID_THRESHOLD``, ``DRAIN_WALL_TOLERANCE_M``, ``DRAIN_MAX_OUTLET_POSITION``)
are each perturbed by $\\pm 20\\%$ and $\\pm 30\\%$ about their baseline
values, and the flood fill is re-run over a sample of trusted dams. Two outputs
are tracked: the fraction of the sample that remains in the trusted subset
(``frac_trusted``) and the median area–volume exponent over that subset
(``median_b_trusted``). The panel draws every constant the table holds, in the
order the sweep writes them. The markers of the constants sit side by side
around each perturbation, which keeps equal values visible.

Panel a: ``frac_trusted`` versus perturbation fraction, one line per
constant, with the baseline (perturbation 0) marked and a horizontal
reference at the $0.92$ retention floor.

Panel b: ``median_b_trusted`` versus perturbation fraction, one line per
constant, with the baseline median $b$ marked, a shaded band of $\\pm 0.01$
around it and the key of both panels.

Reads:

- ``<CSV_DIR>/validation/sensitivity_sweep.csv``
"""

from __future__ import annotations

import itertools
import os
from pathlib import Path

import pandas as pd

import eaves.config as _cfg

from ._shared import COL_REGI, COL_SRTM, apply_style, mm_to_in, panel_label, save_panel


# Assigns one color and one marker to each perturbed constant
_CONST_STYLE = {
    "ALIGN_WEIGHT":              (COL_SRTM, "o"),
    "MAX_CREST_FLOW_DOT":        (COL_REGI, "s"),
    "VOID_THRESHOLD":            ("#54A24B", "^"),
    "DRAIN_WALL_TOLERANCE_M":    ("#B279A2", "D"),
    "DRAIN_MAX_OUTLET_POSITION": ("#72B7B2", "v"),
}
# Styles handed in order to the constants of the table that _CONST_STYLE does not name
_SPARE_STYLES = [("#9D755D", "P"), ("#FF9DA6", "X"), ("#BAB0AC", "*")]
# Human-readable legend labels, without underscores in figure text
_CONST_LABEL = {
    "ALIGN_WEIGHT":              "alignment weight",
    "MAX_CREST_FLOW_DOT":        "maximum crest-flow dot product",
    "VOID_THRESHOLD":            "void-fraction threshold",
    "DRAIN_WALL_TOLERANCE_M":    "drainage wall tolerance",
    "DRAIN_MAX_OUTLET_POSITION": "maximum outlet position",
}
_FRAC_FLOOR = 0.92
# Horizontal step between the markers of neighboring constants at one perturbation, in units of the perturbation fraction
_DODGE = 0.012


def make_s5_sensitivity(out_dir: Path) -> Path:
    apply_style()

    df = pd.read_csv(
        os.path.join(_cfg.CSV_DIR, "validation", "sensitivity_sweep.csv")
    )
    base = df[df["constant"] == "baseline"]
    base_frac = float(base["frac_trusted"].iloc[0]) if len(base) else None
    base_b = float(base["median_b_trusted"].iloc[0]) if len(base) else None

    import matplotlib.pyplot as plt

    # Sets uniform 12 pt text across every element. Panel labels are overridden to 14
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
    fig.subplots_adjust(left=0.085, right=0.985, top=0.93, bottom=0.135,
                        wspace=0.28)

    # Takes the constants in the order the sweep writes them
    constants = [c for c in df["constant"].unique() if c != "baseline"]
    spare = itertools.cycle(_SPARE_STYLES)
    styles = {c: _CONST_STYLE[c] if c in _CONST_STYLE else next(spare) for c in constants}
    # Sets the markers of the constants side by side around each perturbation, which keeps equal values visible
    shifts = {c: _DODGE * (i - 0.5 * (len(constants) - 1)) for i, c in enumerate(constants)}

    # ---- Panel a: frac_trusted vs perturbation ----
    for const in constants:
        color, marker = styles[const]
        sub = df[df["constant"] == const].sort_values("perturbation_frac")
        x = sub["perturbation_frac"] + shifts[const] * (sub["perturbation_frac"] != 0.0)
        ax_a.plot(x, sub["frac_trusted"],
                  color=color, marker=marker, markersize=5.5, linewidth=1.4,
                  zorder=3, label=_CONST_LABEL.get(const, const.replace("_", " ").lower()))

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

    # ---- Panel b: median_b_trusted vs perturbation ----
    for const in constants:
        color, marker = styles[const]
        sub = df[df["constant"] == const].sort_values("perturbation_frac")
        x = sub["perturbation_frac"] + shifts[const] * (sub["perturbation_frac"] != 0.0)
        ax_b.plot(x, sub["median_b_trusted"],
                  color=color, marker=marker, markersize=5.5, linewidth=1.4,
                  zorder=3, label=_CONST_LABEL.get(const, const.replace("_", " ").lower()))

    if base_b is not None:
        ax_b.axhline(base_b, color="0.35", linewidth=0.9, linestyle="--",
                     zorder=2)
        ax_b.scatter([0.0], [base_b], s=70, facecolor="white",
                     edgecolor="0.15", linewidth=1.2, zorder=5,
                     label=f"baseline ($b = {base_b:.3f}$)")
        # Shades the +/- 0.01 envelope around the baseline median b
        ax_b.axhspan(base_b - 0.01, base_b + 0.01, color="0.85", alpha=0.45,
                     zorder=1)

    ax_b.set_xlabel("Perturbation fraction")
    ax_b.set_ylabel(r"Median $b$ over trusted subset")
    ax_b.grid(True, linewidth=0.3, color="0.88")
    ax_b.set_axisbelow(True)
    if base_b is not None:
        # Leaves one key row for each constant and for the baseline above the shaded envelope
        ax_b.set_ylim(base_b - 0.03, base_b + 0.012 + 0.005 * (len(constants) + 1))
    # Places the key of both panels in the free band at the top of panel b
    ax_b.legend(loc="upper left", frameon=True, framealpha=0.95, labelspacing=0.3)

    # Puts the ticks on the perturbations of the table, the centers of the marker groups
    for _ax in (ax_a, ax_b):
        _ax.set_xticks(sorted(df["perturbation_frac"].unique()))

    panel_label(ax_a, "a", fontsize=14, y_offset_pt=8.0)
    panel_label(ax_b, "b", fontsize=14, y_offset_pt=8.0)

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_png = out_dir / "s5_sensitivity.png"
    # Opens the axes by hiding the top and right spines
    for _ax in fig.axes:
        _ax.spines["top"].set_visible(False)
        _ax.spines["right"].set_visible(False)

    save_panel(fig, out_png)
    plt.close(fig)
    rc_stack.__exit__(None, None, None)
    return out_png
