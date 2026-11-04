"""Shared style, text sizes and color palette of the EAVES panel figures.

``PANEL_RCPARAMS`` sets the session defaults, ``PANEL_TEXT_RC`` the 10 pt
text of the figures, ``panel_label`` the bold panel letters and the ``COL_*``
constants the palette.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib as mpl

# ---- Shared style ----
_PANEL_LBL_FS = 12

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

# Text sizes of the figures, 10 pt for every element, with the panel letters at 12 pt through panel_label
PANEL_TEXT_RC: dict = {
    "font.size":       10,
    "axes.labelsize":  10,
    "axes.titlesize":  10,
    "xtick.labelsize": 10,
    "ytick.labelsize": 10,
    "legend.fontsize": 10,
}


def apply_style() -> None:
    """Applies the shared panel rcParams to the current session."""
    mpl.rcParams.update(PANEL_RCPARAMS)


def panel_label(ax, letter: str, *, x: float = 0.0, y_offset_pt: float = 8.0,
                fontsize: float | None = None) -> None:
    """Bold lowercase panel label at a fixed offset in points above the axes top.

    The offset is the same for every axes whatever its height. The label sits
    at ``x`` in axes coordinates, by default aligned with the y-axis.
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


def save_panel(fig, out_png, *, dpi: int = 300, bbox: str = "tight") -> None:
    """Save ``fig`` as a 300-dpi PNG and a vector PDF alongside it."""
    p = Path(out_png)
    fig.savefig(p, dpi=dpi, bbox_inches=bbox)
    fig.savefig(p.with_suffix(".pdf"), bbox_inches=bbox)


def _style_legend(leg) -> None:
    """Sets the key text of a legend to the dark gray of the panel figures."""
    for txt in leg.get_texts():
        txt.set_color("0.10")


# ---- Color palettes ----

# Parameter source: SRTM blue, regionalized orange, failed red (the Vega-10 slots panel 1 uses)
COL_SRTM = "#4C78A8"
COL_REGI = "#F58518"
COL_FAILED = "#E45756"
# Geographic supporting colors
COL_LAND_OTHER = "#DCDCDC"
COL_LAND_KSA = "#FAEBD7"
COL_WATER = "#F0F8FF"
COL_BORDER = "0.40"
COL_KSA_BORDER = "0.10"
# Flowchart palette, neutral tones
COL_BOX_INPUT = "#FAF3DD"        # pale cream
COL_BOX_INPUT_EDGE = "#C4A565"   # muted gold accent
COL_BOX_PROC = "#EDEDED"         # light neutral gray
COL_BOX_PROC_EDGE = "#707070"    # medium neutral gray border
COL_BOX_HIGHLIGHT = "#DCDCDC"    # deeper gray for the multi-stage block
COL_BOX_DECISION = "#FBEAE5"     # lighter pale red
COL_BOX_DECISION_EDGE = "#B83A2A"  # red edge
COL_BOX_OUT_SRTM = "#DCE7F5"     # pale blue, matches panel a SRTM markers
COL_BOX_OUT_REGI = "#FBE3D2"     # pale orange
# Curve / fit palette (p3)
COL_DATA_BLUE = "#1f77b4"
COL_DATA_ORANGE = "#ff7f0e"
COL_FIT_BLACK = "black"
# Placement panel colors (p2)
COL_DAM = "#E45756"              # red star, catalog dam location (Vega slot 3)
COL_WALL = "#FFB300"             # amber, accepted wall segment
COL_BASIN = "#4C78A8"            # Vega blue, flooded basin fill + edge
COL_RIVER = (0.52, 0.49, 0.46)   # warm gray, MERIT-Basins river reaches
COL_LAND = "gainsboro"           # background land tint

# Validation-figure (p4) accent
P4_BLUE = "#0072B2"   # Okabe-Ito blue


apply_style()
