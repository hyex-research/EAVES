"""Shared style + colour palette for the EAVES Data Descriptor panel figures.

All figure modules in this package import from here so that fontsizes,
panel-label placement, and the colour vocabulary stay consistent across
figures 1-4.
"""

from __future__ import annotations

import matplotlib as mpl


# ---------------------------------------------------------------------------
# Shared style — Scientific Data / Nature portfolio conventions.
# ---------------------------------------------------------------------------
_PANEL_LBL_FS = 16

PANEL_RCPARAMS: dict = {
    "font.family": "sans-serif",
    "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans", "sans-serif"],
    "font.size": 7,
    "axes.labelsize": 8,
    "axes.titlesize": 8,
    "axes.linewidth": 0.8,
    "axes.unicode_minus": True,
    "xtick.labelsize": 7,
    "ytick.labelsize": 7,
    "legend.fontsize": 7,
    "figure.dpi": 300,
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
    "pdf.fonttype": 42,
    "ps.fonttype": 42,
    "mathtext.fontset": "dejavusans",
}


def apply_style() -> None:
    """Apply the shared Nature-portfolio rcParams to the current session."""
    mpl.rcParams.update(PANEL_RCPARAMS)


def panel_label(ax, letter: str, *, x: float = 0.0, y_offset_pt: float = 8.0,
                fontsize: float | None = None) -> None:
    """Bold lowercase panel label at a fixed pixel offset above the axes top.

    Uses ``offset_points`` so the label sits the same absolute distance above
    every plot, regardless of axes height (axes-fraction y values would scale
    with each panel's individual height and produce visually-uneven labels
    across a multi-panel figure). Horizontally pinned to ``x=0`` in axes
    coordinates so the letter aligns with the y-axis.
    """
    ax.annotate(
        letter,
        xy=(x, 1.0), xycoords="axes fraction",
        xytext=(0, y_offset_pt), textcoords="offset points",
        fontsize=_PANEL_LBL_FS if fontsize is None else fontsize,
        fontweight="bold",
        ha="left", va="bottom",
        annotation_clip=False,
    )


def mm_to_in(mm: float) -> float:
    return mm / 25.4


# ---------------------------------------------------------------------------
# Colour palettes
# ---------------------------------------------------------------------------
# Vega-10 categorical palette (figure 1 panel a).
VEGA = {
    "teal":   "#72B7B2",
    "green":  "#54A24B",
    "red":    "#E45756",
    "blue":   "#4C78A8",
    "purple": "#B279A2",
    "orange": "#F58518",
}
# Parameter source — srtm-derived blue, regionalised orange, failed red.
COL_SRTM = VEGA["blue"]
COL_REGI = VEGA["orange"]
COL_FAILED = VEGA["red"]
# Geographic supporting greys.
COL_LAND_OTHER = "#DCDCDC"
COL_LAND_KSA = "#F7F0E0"
COL_BORDER = "0.40"
COL_KSA_BORDER = "0.10"
# Flowchart palette — Sci Data clean / neutral.
COL_BOX_INPUT = "#FAF3DD"        # pale cream
COL_BOX_INPUT_EDGE = "#C4A565"   # muted gold accent
COL_BOX_PROC = "#EDEDED"         # light neutral gray
COL_BOX_PROC_EDGE = "#707070"    # medium neutral gray border
COL_BOX_HIGHLIGHT = "#DCDCDC"    # deeper gray for the multi-stage block
COL_BOX_DECISION = "#FBEAE5"     # lighter pale red, lets the edge dominate
COL_BOX_DECISION_EDGE = "#B83A2A"  # red edge
COL_BOX_OUT_SRTM = "#DCE7F5"     # pale blue, matches panel a SRTM markers
COL_BOX_OUT_REGI = "#FBE3D2"     # pale orange
# Curve / fit palette (p3 + p4).
COL_DATA_BLUE = "#1f77b4"
COL_DATA_ORANGE = "#ff7f0e"
COL_FIT_BLACK = "black"
COL_GRADE_A_BAND = "olive"
COL_GRADE_B_BAND = "darkkhaki"
# Placement panel colours (p2).
COL_DAM = "#E45756"              # red star — catalogue dam location (Vega slot 3)
COL_WALL = "#FFB300"             # amber — accepted wall segment
COL_BASIN = "#4C78A8"            # Vega blue — flooded basin fill + edge
COL_RIVER = (0.52, 0.49, 0.46)   # warm grey — MERIT Hydro polylines
COL_LAND = "gainsboro"           # background land tint

# Validation-figure (p4) accents.
P4_BLUE = "#0072B2"   # NATURE_COLORS blue  — GRDL / bathymetry
P4_VERM = "#D55E00"   # NATURE_COLORS vermillion — SRTM / EAVES


apply_style()
