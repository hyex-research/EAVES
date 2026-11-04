"""Panel s5 (supplementary): sensitivity of the trusted set to the placement and acceptance constants.

Five internal pipeline constants (``ALIGN_WEIGHT``, ``MAX_CREST_FLOW_DOT``,
``VOID_THRESHOLD``, ``DRAIN_WALL_TOLERANCE_M``, ``DRAIN_MAX_OUTLET_POSITION``)
are each perturbed by ±20% and ±30% about their baseline values, and the
pipeline is re-run on a sample of trusted fits spanning the capacity range.
Two outputs are tracked: the fraction of the sample that remains in the
trusted subset (``frac_trusted``) and the median area-volume exponent over
that subset (``median_b_trusted``). The panel draws every constant the table
holds, in the order the sweep writes them. The markers of the constants sit
side by side around each perturbation.

Panel a: ``frac_trusted`` versus perturbation fraction, one line per
constant, with the baseline (perturbation 0) marked, a horizontal
retention reference at 0.92 and the key of the constants below that line.

Panel b: ``median_b_trusted`` versus perturbation fraction, one line per
constant, with the baseline median b marked, a shaded band of ±0.03
around it and the key entry of the baseline above the band.

Reads:

- ``<CSV_DIR>/validation/sensitivity_sweep.csv``
"""

from __future__ import annotations

import itertools
import os
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.transforms import blended_transform_factory

import eaves.config as _cfg

from ._shared import (
    COL_REGI,
    COL_SRTM,
    PANEL_TEXT_RC,
    apply_style,
    mm_to_in,
    panel_label,
    save_panel,
)

# Assigns one color and one marker to each perturbed constant
_CONST_STYLE = {
    "ALIGN_WEIGHT":              (COL_SRTM, "o"),
    "MAX_CREST_FLOW_DOT":        (COL_REGI, "s"),
    "VOID_THRESHOLD":            ("#54A24B", "^"),
    "DRAIN_WALL_TOLERANCE_M":    ("#B279A2", "D"),
    "DRAIN_MAX_OUTLET_POSITION": ("#72B7B2", "v"),
}
# Styles handed out in sequence to the constants of the table that _CONST_STYLE does not name
_SPARE_STYLES = [("#9D755D", "P"), ("#FF9DA6", "X"), ("#BAB0AC", "*")]
# Key labels of the constants in sentence case
_CONST_LABEL = {
    "ALIGN_WEIGHT":              "Alignment weight",
    "MAX_CREST_FLOW_DOT":        "Maximum crest-flow dot product",
    "VOID_THRESHOLD":            "Void-fraction threshold",
    "DRAIN_WALL_TOLERANCE_M":    "Drainage wall tolerance",
    "DRAIN_MAX_OUTLET_POSITION": "Maximum outlet position",
}
_FRAC_FLOOR = 0.92
# Half-width of the shaded envelope around the baseline median b
_B_BAND = 0.03
# Horizontal step between the markers of neighboring constants at one perturbation, in units of the perturbation fraction
_DODGE = 0.012
# Key layout shared by both panels
_KEY_KW = dict(frameon=False, fontsize=10, handlelength=1.2, handletextpad=0.4,
               labelspacing=0.3, borderaxespad=0.2)


def _const_label(const: str) -> str:
    """Key label of a constant, the table name in sentence case when _CONST_LABEL does not name it."""
    return _CONST_LABEL.get(const, const.replace("_", " ").capitalize())


def _plot_constants(ax, df: pd.DataFrame, column: str, constants: list[str],
                    styles: dict, shifts: dict) -> list:
    """Draws one line per constant of ``column`` against the perturbation fraction and returns the line handles."""
    handles = []
    for const in constants:
        color, marker = styles[const]
        sub = df[df["constant"] == const].sort_values("perturbation_frac")
        x = sub["perturbation_frac"] + shifts[const] * (sub["perturbation_frac"] != 0.0)
        (line,) = ax.plot(x, sub[column],
                          color=color, marker=marker, markersize=5.5, linewidth=1.4,
                          zorder=3, label=_const_label(const))
        handles.append(line)
    return handles


def _baseline_marker(ax, y: float, label: str):
    """Open circle on the baseline value at perturbation 0."""
    return ax.scatter([0.0], [y], s=70, facecolor="white",
                      edgecolor="0.15", linewidth=1.2, zorder=5, label=label)


def _draw_panel_a(ax, df: pd.DataFrame, constants: list[str], styles: dict,
                  shifts: dict, base_frac: float | None) -> None:
    """Panel a, fraction trusted against perturbation, with the retention reference and the key of the constants."""
    handles = _plot_constants(ax, df, "frac_trusted", constants, styles, shifts)

    ax.axhline(_FRAC_FLOOR, color="0.35", linewidth=0.9, linestyle=":", zorder=2)
    ax.text(0.98, _FRAC_FLOOR + 0.003, f"Retention reference = {_FRAC_FLOOR:.2f}",
            transform=blended_transform_factory(ax.transAxes, ax.transData),
            color="0.30", ha="right", va="bottom", fontsize=10)
    if base_frac is not None:
        _baseline_marker(ax, base_frac, "_nolegend_")

    ax.set_xlabel("Perturbation fraction", fontsize=10)
    ax.set_ylabel("Fraction trusted", fontsize=10)
    # Leaves the rows of the key below the retention reference
    ax.set_ylim(0.855, 1.01)
    ax.tick_params(labelsize=10, length=2.5)
    ax.grid(True, linewidth=0.3, color="0.88")
    ax.set_axisbelow(True)
    ax.legend(handles=handles, loc="lower left", **_KEY_KW)
    panel_label(ax, "a", fontsize=12)


def _draw_panel_b(ax, df: pd.DataFrame, constants: list[str], styles: dict,
                  shifts: dict, base_b: float | None) -> None:
    """Panel b, median b over the trusted set against perturbation, with the shaded envelope and the baseline key entry."""
    _plot_constants(ax, df, "median_b_trusted", constants, styles, shifts)

    if base_b is not None:
        ax.axhline(base_b, color="0.35", linewidth=0.9, linestyle="--", zorder=2)
        marker = _baseline_marker(ax, base_b, f"Baseline ($b = {base_b:.3f}$)")
        # Shades the envelope around the baseline median b
        ax.axhspan(base_b - _B_BAND, base_b + _B_BAND, color="0.85", alpha=0.45, zorder=1)
        # Leaves one key row above the shaded envelope
        ax.set_ylim(base_b - _B_BAND - 0.01, base_b + _B_BAND + 0.013)
        ax.legend(handles=[marker], loc="upper left", **_KEY_KW)

    ax.set_xlabel("Perturbation fraction", fontsize=10)
    ax.set_ylabel(r"Median $b$ over trusted set", fontsize=10)
    ax.tick_params(labelsize=10, length=2.5)
    ax.grid(True, linewidth=0.3, color="0.88")
    ax.set_axisbelow(True)
    panel_label(ax, "b", fontsize=12)


def make_s5_sensitivity(out_dir: Path) -> Path:
    """Renders s5, the sensitivity sweep of the placement and acceptance constants in one row.

    Panel a: fraction trusted against perturbation.
    Panel b: median b over the trusted set against perturbation.
    """
    apply_style()

    df = pd.read_csv(
        os.path.join(_cfg.CSV_DIR, "validation", "sensitivity_sweep.csv")
    )
    base = df[df["constant"] == "baseline"]
    base_frac = float(base["frac_trusted"].iloc[0]) if len(base) else None
    base_b = float(base["median_b_trusted"].iloc[0]) if len(base) else None

    # Takes the constants in the order the sweep writes them
    constants = [c for c in df["constant"].unique() if c != "baseline"]
    spare = itertools.cycle(_SPARE_STYLES)
    styles = {c: _CONST_STYLE[c] if c in _CONST_STYLE else next(spare) for c in constants}
    # Sets the markers of the constants side by side around each perturbation
    shifts = {c: _DODGE * (i - 0.5 * (len(constants) - 1)) for i, c in enumerate(constants)}

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_png = out_dir / "s5_sensitivity.png"

    with plt.rc_context(PANEL_TEXT_RC):
        fig = plt.figure(figsize=(mm_to_in(187.0), mm_to_in(88.0)))
        gs = fig.add_gridspec(
            1, 2,
            wspace=0.26,
            left=0.092, right=0.986, top=0.92, bottom=0.135,
        )
        ax_a = fig.add_subplot(gs[0, 0])
        ax_b = fig.add_subplot(gs[0, 1])
        _draw_panel_a(ax_a, df, constants, styles, shifts, base_frac)
        _draw_panel_b(ax_b, df, constants, styles, shifts, base_b)

        # Puts the ticks on the perturbations of the table, the centers of the marker groups
        for _ax in (ax_a, ax_b):
            _ax.set_xticks(sorted(df["perturbation_frac"].unique()))

        # Opens the axes by hiding the top and right spines
        for _ax in fig.axes:
            _ax.spines["top"].set_visible(False)
            _ax.spines["right"].set_visible(False)

        save_panel(fig, out_png)
    plt.close(fig)
    return out_png
