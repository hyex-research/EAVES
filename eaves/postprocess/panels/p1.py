"""Panel set p1: domain map (a) + EAVES pipeline flowchart (b).

Panel a maps the retained dams over the country from ``eaves_summary.csv``,
``eaves_params.csv`` and ``failed_dams.csv``, colored by the parameter
source, with the key inside the map and an inset of the southwestern
escarpment between Jeddah and Jizan in the southeast corner. Panel b
draws the pipeline flowchart from static stage definitions on a millimeter
canvas, so every box holds 10 pt text. The map takes the left part of the
187 mm row at its plate carree aspect and the flowchart the right part.
"""

from __future__ import annotations

import os
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.patches import Ellipse, FancyArrowPatch, FancyBboxPatch, Polygon, Rectangle
from matplotlib.ticker import MultipleLocator
from shapely.geometry import box
from shapely.ops import unary_union

import eaves.config as _cfg

from ...utils import dams_with_fill
from ._shared import (
    COL_BORDER,
    COL_BOX_DECISION,
    COL_BOX_DECISION_EDGE,
    COL_BOX_HIGHLIGHT,
    COL_BOX_INPUT,
    COL_BOX_INPUT_EDGE,
    COL_BOX_OUT_REGI,
    COL_BOX_OUT_SRTM,
    COL_BOX_PROC,
    COL_BOX_PROC_EDGE,
    COL_FAILED,
    COL_KSA_BORDER,
    COL_LAND_KSA,
    COL_LAND_OTHER,
    COL_REGI,
    COL_SRTM,
    COL_WATER,
    PANEL_TEXT_RC,
    mm_to_in,
    panel_label,
    save_panel,
)

# ---- Figure layout in millimeters ----

FIG_W = 187.0        # canvas width
MAP_LEFT = 13.9      # map axes left edge, after the latitude labels
MAP_W = 85.6         # map axes width
GAP = 5.0            # gap between the map and the flowchart
FLOW_W = 80.0        # flowchart axes width
TOP = 9.5            # room above the axes for the panel letters
XAXIS = 10.3         # longitude tick labels and axis label under the map
BOTTOM = 2.5         # clearance under the row

# Map padding around the country bounds in degrees, the north pad keeps the Gulf corner free for the parameter-source key and the south pad sets the map height that the flowchart follows
PAD_LON = 0.5
PAD_S = 4.0
PAD_N = 4.0

# Marker area of every dam in pt^2, one size for the whole catalog
MARKER_PT2 = 8.0

# Inset of the southwestern escarpment between Jeddah and Jizan, the window on the main map and the side and margin of the square in the southeast corner, all in degrees
INSET_WINDOW = ((38.9, 44.4), (16.6, 22.1))
INSET_SIDE = 9.2
INSET_MARGIN = 0.35
INSET_EDGE = "0.25"

# Veil over everything outside the country, sea included
DIM_ALPHA = 0.35

# Parameter-source groups, the regionalized dams are drawn above the SRTM-derived ones and the failed dams above both
GROUPS = [
    ("srtm_derived",     COL_SRTM,   "SRTM-derived",                  "v", False, 4.0),
    ("regi_multi",       COL_REGI,   "Regionalized",                  "v", False, 4.5),
    ("placement_failed", COL_FAILED, "Placement, fill or\nfit failed", "x", True,  5.0),
]

# ---- Flowchart geometry in millimeters, one axis unit is one millimeter ----

FLOW_BOX_W = 79.5    # full-width box
H_IN = 7.0           # input ellipse height
H_STD = 5.0          # single-line box height
H_SIX = 16.5         # six-stage box height
H_DEC = 7.5          # decision diamond height
H_REGI = 13.0        # regionalization box height
CONV = 2.5           # drop of the input lines to their junction
NO_EXTRA = 1.0       # extra length of the No arrow that holds its label clear of the boxes
MARGIN = 0.5         # clearance to the axes edge


def _load_dam_points() -> pd.DataFrame:
    """Return DataFrame with columns: dam_id, lat, lon, source."""
    summary_csv = os.path.join(_cfg.CSV_DIR, "eaves_summary.csv")
    params_csv = os.path.join(_cfg.CSV_DIR, "eaves_params.csv")
    failed_csv = os.path.join(_cfg.CSV_DIR, "failed_dams.csv")

    summary = dams_with_fill(pd.read_csv(summary_csv, usecols=["dam_id", "lat", "lon", "n_pixels"])).drop(columns="n_pixels")
    params = pd.read_csv(params_csv, usecols=["dam_id", "source"])
    failed_ids = pd.read_csv(failed_csv, usecols=["dam_id"])["dam_id"].tolist()

    catalog = pd.read_csv(
        _cfg.DAMS_CSV,
        usecols=["dam_id", "latitude", "longitude"],
    ).rename(columns={"latitude": "lat", "longitude": "lon"})

    merged = summary.merge(params[["dam_id", "source"]], on="dam_id", how="left")
    merged["source"] = merged["source"].fillna("regi_multi")
    merged.loc[merged["dam_id"].isin(failed_ids), "source"] = "placement_failed"

    failed_only = catalog[
        catalog["dam_id"].isin(failed_ids)
        & ~catalog["dam_id"].isin(merged["dam_id"])
    ].copy()
    failed_only["source"] = "placement_failed"
    failed_only = failed_only[["dam_id", "lat", "lon", "source"]]

    return pd.concat([merged, failed_only], ignore_index=True).dropna(subset=["lat", "lon"])


def _load_country() -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """Return the country layer in EPSG:4326 and the target country."""
    world = gpd.read_file(_cfg.COUNTRY_SHP)
    if world.crs is None or world.crs.to_epsg() != 4326:
        world = world.to_crs(epsg=4326)
    name_col = getattr(_cfg, "COUNTRY_NAME_COL", "NAME")
    ksa = world[world[name_col] == _cfg.TARGET_COUNTRY]
    return world, ksa


def _map_extent(ksa) -> tuple[tuple[float, float], tuple[float, float]]:
    """Return the (xlim, ylim) of the map, the country bounds plus the padding."""
    minx, miny, maxx, maxy = ksa.total_bounds
    return (minx - PAD_LON, maxx + PAD_LON), (miny - PAD_S, maxy + PAD_N)


def _draw_basemap(ax, world, ksa, xlim, ylim) -> None:
    """Draw the neighbors, the country fill, the veil over everything outside the country and its boundary inside the given extent."""
    ax.set_xlim(*xlim)
    ax.set_ylim(*ylim)
    ax.set_facecolor(COL_WATER)
    nbrs = world.cx[xlim[0]:xlim[1], ylim[0]:ylim[1]]
    nbrs.plot(
        ax=ax, facecolor=COL_LAND_OTHER, edgecolor=COL_BORDER,
        linewidth=0.4, zorder=1,
    )
    ksa.plot(ax=ax, facecolor=COL_LAND_KSA, edgecolor="none", zorder=1.4)
    outside = box(xlim[0], ylim[0], xlim[1], ylim[1]).difference(unary_union(ksa.geometry))
    gpd.GeoSeries([outside], crs=ksa.crs).plot(
        ax=ax, facecolor="black", edgecolor="none", alpha=DIM_ALPHA, zorder=1.6,
    )
    ksa.boundary.plot(ax=ax, edgecolor=COL_KSA_BORDER, linewidth=0.8, zorder=2)
    ax.set_aspect("equal", adjustable="datalim")


def _draw_dams(ax, dams: pd.DataFrame) -> None:
    """Scatter the dams of every parameter-source group at one marker size."""
    for src, color, _label, marker, is_failed, zorder in GROUPS:
        mask = dams["source"] == src
        if not mask.any():
            continue
        if is_failed:
            ax.scatter(
                dams.loc[mask, "lon"], dams.loc[mask, "lat"],
                s=MARKER_PT2 * 0.7,
                c=color, linewidth=1.0,
                marker=marker, zorder=zorder, alpha=0.95,
            )
        else:
            ax.scatter(
                dams.loc[mask, "lon"], dams.loc[mask, "lat"],
                s=MARKER_PT2,
                facecolor=color, edgecolor="black", linewidth=0.35,
                marker=marker, zorder=zorder, alpha=0.92,
            )


def _draw_inset(ax, world, ksa, dams: pd.DataFrame, xlim, ylim) -> None:
    """Draw the window rectangle on the main map and the zoomed square in its southeast corner."""
    (wx0, wx1), (wy0, wy1) = INSET_WINDOW
    ax.add_patch(Rectangle(
        (wx0, wy0), wx1 - wx0, wy1 - wy0,
        facecolor="none", edgecolor=INSET_EDGE, linewidth=0.8, zorder=6,
    ))
    x0 = xlim[1] - INSET_MARGIN - INSET_SIDE
    y0 = ylim[0] + INSET_MARGIN
    ax_in = ax.inset_axes([x0, y0, INSET_SIDE, INSET_SIDE], transform=ax.transData)
    _draw_basemap(ax_in, world, ksa, (wx0, wx1), (wy0, wy1))
    _draw_dams(ax_in, dams)
    ax_in.set_xticks([])
    ax_in.set_yticks([])
    for spine in ax_in.spines.values():
        spine.set_edgecolor(INSET_EDGE)
        spine.set_linewidth(0.8)
    ax_in.set_zorder(7)


def _draw_panel_a(ax, world, ksa, xlim, ylim) -> None:
    """Panel a, the dams over the country map with the parameter-source key in the Gulf corner and the inset in the southeast corner."""
    dams = _load_dam_points()
    _draw_basemap(ax, world, ksa, xlim, ylim)
    _draw_dams(ax, dams)

    ax.set_xlabel("Longitude (°E)", fontsize=10)
    ax.set_ylabel("Latitude (°N)", fontsize=10)
    ax.xaxis.set_major_locator(MultipleLocator(5.0))
    ax.yaxis.set_major_locator(MultipleLocator(5.0))
    ax.tick_params(length=2.5, direction="out", labelsize=10)
    ax.grid(False)

    counts = dams["source"].value_counts()
    src_handles = []
    for src, color, label, marker, is_failed, _zorder in GROUPS:
        n = int(counts.get(src, 0))
        if n == 0:
            continue
        if is_failed:
            src_handles.append(
                Line2D([0], [0], marker=marker, color=color,
                       markerfacecolor="none", markeredgewidth=1.1,
                       linewidth=0, markersize=4.0,
                       label=f"{label} (n = {n})")
            )
        else:
            src_handles.append(
                Line2D([0], [0], marker=marker, color="none",
                       markerfacecolor=color, markeredgecolor="black",
                       markersize=4, markeredgewidth=0.4,
                       label=f"{label} (n = {n})")
            )
    ax.legend(
        handles=src_handles, loc="upper right",
        title="Parameter source", title_fontsize=10, fontsize=10,
        alignment="left", frameon=False,
        handlelength=1.0, handletextpad=0.4, labelspacing=0.3,
        borderpad=0.2, borderaxespad=0.5,
    )

    _draw_inset(ax, world, ksa, dams, xlim, ylim)
    panel_label(ax, "a", fontsize=12)


def _box(ax, x, y, w, h, text, *,
         facecolor=COL_BOX_PROC, edgecolor=COL_BOX_PROC_EDGE,
         fontsize=10, fontweight="normal",
         rounding=1.5, zorder=2, text_color="0.10") -> None:
    patch = FancyBboxPatch(
        (x - w / 2.0, y - h / 2.0), w, h,
        boxstyle=f"round,pad=0.012,rounding_size={rounding}",
        linewidth=0.8, facecolor=facecolor, edgecolor=edgecolor,
        zorder=zorder,
    )
    ax.add_patch(patch)
    ax.text(
        x, y, text,
        ha="center", va="center",
        fontsize=fontsize, fontweight=fontweight, color=text_color,
        zorder=zorder + 1,
    )


def _ellipse(ax, x, y, w, h, text, *,
             facecolor=COL_BOX_INPUT, edgecolor=COL_BOX_INPUT_EDGE,
             fontsize=10, fontweight="normal",
             zorder=2, text_color="0.10") -> None:
    patch = Ellipse(
        (x, y), w, h,
        linewidth=0.8, facecolor=facecolor, edgecolor=edgecolor,
        zorder=zorder,
    )
    ax.add_patch(patch)
    ax.text(
        x, y, text,
        ha="center", va="center",
        fontsize=fontsize, fontweight=fontweight, color=text_color,
        zorder=zorder + 1,
    )


def _diamond(ax, x, y, w, h, text, *,
             facecolor=COL_BOX_DECISION, edgecolor=COL_BOX_DECISION_EDGE,
             fontsize=10, fontweight="normal",
             zorder=2, text_color="0.10") -> None:
    pts = [(x, y + h / 2.0), (x + w / 2.0, y),
           (x, y - h / 2.0), (x - w / 2.0, y)]
    patch = Polygon(
        pts, closed=True,
        linewidth=0.8, facecolor=facecolor, edgecolor=edgecolor,
        zorder=zorder,
    )
    ax.add_patch(patch)
    ax.text(
        x, y, text,
        ha="center", va="center",
        fontsize=fontsize, fontweight=fontweight, color=text_color,
        zorder=zorder + 1,
    )


def _arrow(ax, x1, y1, x2, y2, *,
           color="0.20", label=None, lw=0.8,
           label_dx: float = 0.0, label_dy: float = 1.6) -> None:
    """Draw an arrow from (x1, y1) to (x2, y2), with an optional label offset from its midpoint by ``(label_dx, label_dy)``."""
    ax.add_patch(FancyArrowPatch(
        (x1, y1), (x2, y2),
        arrowstyle="-|>", mutation_scale=9,
        linewidth=lw, color=color, zorder=1,
    ))
    if label is not None:
        ax.text(
            0.5 * (x1 + x2) + label_dx,
            0.5 * (y1 + y2) + label_dy,
            label,
            ha="center", va="center",
            fontsize=10, color="0.10",
            zorder=3,
        )


def _draw_panel_b(ax, height: float) -> None:
    """Panel b, the pipeline flowchart on a canvas of FLOW_W by ``height`` millimeters, the arrows share the height the boxes leave."""
    ax.set_xlim(0.0, FLOW_W)
    ax.set_ylim(0.0, height)
    ax.set_aspect("equal")
    ax.set_axis_off()

    cx = FLOW_W / 2.0
    boxes = H_IN + H_STD + H_SIX + 4 * H_STD + H_DEC + H_REGI
    arrow = (height - 2 * MARGIN - CONV - NO_EXTRA - boxes) / 8.0

    # ---- Inputs (ellipses) ----
    in_y = height - MARGIN - H_IN / 2.0
    inputs = [
        (7.5, 14.0, "SRTM"),
        (34.0, 27.0, "Dam catalog"),
        (66.5, 26.0, "MERIT-Basins"),
    ]
    for (x, w, t) in inputs:
        _ellipse(ax, x, in_y, w, H_IN, t,
                 facecolor=COL_BOX_INPUT, edgecolor=COL_BOX_INPUT_EDGE,
                 fontsize=10)

    conv_y = in_y - H_IN / 2.0 - CONV
    for (x, _, _) in inputs:
        ax.plot(
            [x, cx], [in_y - H_IN / 2.0, conv_y],
            color="0.35", linewidth=0.7, zorder=1,
        )

    # ---- Snap step ----
    snap_y = conv_y - arrow - H_STD / 2.0
    _box(ax, cx, snap_y, FLOW_BOX_W, H_STD,
         "Snap dam to nearest MERIT-Basins reach",
         facecolor=COL_BOX_PROC, edgecolor=COL_BOX_PROC_EDGE,
         fontsize=10)
    _arrow(ax, cx, conv_y, cx, snap_y + H_STD / 2.0)

    # ---- Six-stage wall placement box, the stages in two columns ----
    six_y = snap_y - H_STD / 2.0 - arrow - H_SIX / 2.0
    six_top = six_y + H_SIX / 2.0
    ax.add_patch(FancyBboxPatch(
        (cx - FLOW_BOX_W / 2.0, six_y - H_SIX / 2.0),
        FLOW_BOX_W, H_SIX,
        boxstyle="round,pad=0.012,rounding_size=1.5",
        linewidth=0.8, facecolor=COL_BOX_HIGHLIGHT,
        edgecolor=COL_BOX_PROC_EDGE, zorder=2,
    ))
    ax.text(
        cx, six_top - 2.4, "6-stage wall placement:",
        ha="center", va="center",
        fontsize=10, color="0.10", zorder=3,
    )
    stages_left = ["1. Direct placement", "2. Upstream walk", "3. Quality recovery"]
    stages_right = ["4. River-direction retry", "5. Relaxed alignment", "6. Synthetic fallback"]
    col_xs = [cx - FLOW_BOX_W / 2.0 + 1.2, cx - 1.5]
    row_step = 3.8
    base_y = six_top - 2.4 - row_step
    for col, stages in enumerate((stages_left, stages_right)):
        for row, s in enumerate(stages):
            ax.text(
                col_xs[col], base_y - row * row_step, s,
                ha="left", va="center",
                fontsize=10, color="0.10", zorder=3,
            )
    _arrow(ax, cx, snap_y - H_STD / 2.0, cx, six_top)

    # ---- Sequential processing steps ----
    proc = [
        "Flood fill to spillway or capacity",
        "EAV levels every 0.5 m",
        "Power-law fit: $V = c \\cdot A^{b}$",
        "Quality grade: A, B, C, D, F",
    ]
    prev_bottom = six_y - H_SIX / 2.0
    for text in proc:
        y = prev_bottom - arrow - H_STD / 2.0
        _box(ax, cx, y, FLOW_BOX_W, H_STD, text,
             facecolor=COL_BOX_PROC, edgecolor=COL_BOX_PROC_EDGE,
             fontsize=10)
        _arrow(ax, cx, prev_bottom, cx, y + H_STD / 2.0)
        prev_bottom = y - H_STD / 2.0

    # ---- Decision (rhombus / diamond) ----
    dec_w = 34.0
    dec_y = prev_bottom - arrow - H_DEC / 2.0
    _diamond(ax, cx, dec_y, dec_w, H_DEC, "Reliable?", fontsize=10)
    _arrow(ax, cx, prev_bottom, cx, dec_y + H_DEC / 2.0)

    # ---- Yes branch (right) ----
    yes_w = 14.0
    yes_gap = 5.0
    yes_x = cx + dec_w / 2.0 + yes_gap + yes_w / 2.0
    _box(ax, yes_x, dec_y, yes_w, H_DEC, "SRTM",
         facecolor=COL_BOX_OUT_SRTM, edgecolor=COL_SRTM, fontsize=10)
    _arrow(
        ax,
        cx + dec_w / 2.0, dec_y,
        yes_x - yes_w / 2.0, dec_y,
        label="Yes", label_dx=-0.8, label_dy=2.5,
    )

    # ---- No branch (down) to the regionalization box ----
    regi_y = dec_y - H_DEC / 2.0 - arrow - NO_EXTRA - H_REGI / 2.0
    _box(ax, cx, regi_y, FLOW_BOX_W, H_REGI, "",
         facecolor=COL_BOX_OUT_REGI, edgecolor=COL_REGI)
    regi_lines = [
        (4.0, "Regionalization"),
        (0.0, "Multi-feature regression for $A_\\mathrm{cap}$"),
        (-4.0, "+ regional-median $b$"),
    ]
    for dy, text in regi_lines:
        ax.text(
            cx, regi_y + dy, text,
            ha="center", va="center",
            fontsize=10, color="0.10", zorder=3,
        )
    _arrow(
        ax,
        cx, dec_y - H_DEC / 2.0,
        cx, regi_y + H_REGI / 2.0,
        label="No", label_dx=4.2, label_dy=0.0,
    )

    panel_label(ax, "b", fontsize=12)


def make_p1_domain(output_dir: str | os.PathLike) -> Path:
    """Render p1 (domain map + flowchart) as one 187 mm row. Returns the PNG path.

    The map axes keeps the plate carree aspect of its extent, the flowchart
    axes is as tall as the map plus its longitude axis, so both panels end
    on one line.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_png = out_dir / "p1_domain_flowchart.png"

    world, ksa = _load_country()
    xlim, ylim = _map_extent(ksa)
    map_h = MAP_W * (ylim[1] - ylim[0]) / (xlim[1] - xlim[0])
    flow_h = map_h + XAXIS
    fig_h = TOP + flow_h + BOTTOM
    flow_left = MAP_LEFT + MAP_W + GAP

    with plt.rc_context(PANEL_TEXT_RC):
        fig = plt.figure(figsize=(mm_to_in(FIG_W), mm_to_in(fig_h)))
        ax_a = fig.add_axes([
            MAP_LEFT / FIG_W, (fig_h - TOP - map_h) / fig_h,
            MAP_W / FIG_W, map_h / fig_h,
        ])
        ax_b = fig.add_axes([
            flow_left / FIG_W, (fig_h - TOP - flow_h) / fig_h,
            FLOW_W / FIG_W, flow_h / fig_h,
        ])
        _draw_panel_a(ax_a, world, ksa, xlim, ylim)
        _draw_panel_b(ax_b, flow_h)

        save_panel(fig, out_png)
    plt.close(fig)
    print(f"wrote {out_png}")
    return out_png
