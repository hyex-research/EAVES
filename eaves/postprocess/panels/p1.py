"""Panel set p1 — KSA domain map (a) + EAVES pipeline flowchart (b)."""

from __future__ import annotations

import os
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.patches import Ellipse, FancyArrowPatch, FancyBboxPatch, Polygon

import eaves.config as _cfg

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
    mm_to_in,
    panel_label,
    save_panel,
)


def _load_dam_points() -> pd.DataFrame:
    """Return DataFrame with columns: dam_id, lat, lon, capacity_mcm, source."""
    summary_csv = os.path.join(_cfg.CSV_DIR, "eaves_summary.csv")
    params_csv = os.path.join(_cfg.CSV_DIR, "eaves_params.csv")
    failed_csv = os.path.join(_cfg.CSV_DIR, "failed_dams.csv")

    summary = pd.read_csv(summary_csv, usecols=["dam_id", "lat", "lon", "capacity_mcm"])
    params = pd.read_csv(params_csv, usecols=["dam_id", "source", "capacity_mcm"])
    failed_ids = pd.read_csv(failed_csv, usecols=["dam_id"])["dam_id"].tolist()

    catalogue = pd.read_csv(
        _cfg.DAMS_CSV,
        usecols=["dam_id", "latitude", "longitude", "storage_capacity_m3"],
    ).rename(columns={"latitude": "lat", "longitude": "lon"})
    catalogue["capacity_mcm"] = catalogue["storage_capacity_m3"] / 1.0e6

    merged = summary.merge(params[["dam_id", "source"]], on="dam_id", how="left")
    merged["source"] = merged["source"].fillna("regi_multi")
    merged.loc[merged["dam_id"].isin(failed_ids), "source"] = "placement_failed"

    failed_only = catalogue[
        catalogue["dam_id"].isin(failed_ids)
        & ~catalogue["dam_id"].isin(merged["dam_id"])
    ].copy()
    failed_only["source"] = "placement_failed"
    failed_only = failed_only[["dam_id", "lat", "lon", "capacity_mcm", "source"]]

    return pd.concat([merged, failed_only], ignore_index=True).dropna(subset=["lat", "lon"])


def _marker_sizes(capacity_mcm: pd.Series) -> np.ndarray:
    """Sqrt-scaled marker areas for catalogue capacity (Mm^3): 12-85 pt^2."""
    cap = np.asarray(capacity_mcm, dtype=float)
    cap = np.where(np.isfinite(cap) & (cap > 0), cap, 1e-3)
    s_min, s_max = 12.0, 85.0
    cap_min, cap_max = 0.05, 200.0
    cap_clipped = np.clip(cap, cap_min, cap_max)
    return s_min + (np.sqrt(cap_clipped) - np.sqrt(cap_min)) / (
        np.sqrt(cap_max) - np.sqrt(cap_min)
    ) * (s_max - s_min)


def _draw_panel_a(ax) -> None:
    dams = _load_dam_points()

    world = gpd.read_file(_cfg.COUNTRY_SHP)
    if world.crs is None or world.crs.to_epsg() != 4326:
        world = world.to_crs(epsg=4326)
    name_col = getattr(_cfg, "COUNTRY_NAME_COL", "NAME")
    target = _cfg.TARGET_COUNTRY
    ksa = world[world[name_col] == target]
    minx, miny, maxx, maxy = ksa.total_bounds

    pad_x = 0.5
    pad_y = 1.5
    xlim = (minx - pad_x, maxx + pad_x)
    ylim = (miny - pad_y, maxy + pad_y)
    ax.set_xlim(*xlim)
    ax.set_ylim(*ylim)

    nbrs = world.cx[xlim[0]:xlim[1], ylim[0]:ylim[1]]
    nbrs.plot(
        ax=ax, facecolor=COL_LAND_OTHER, edgecolor=COL_BORDER,
        linewidth=0.4, zorder=1,
    )
    ksa.plot(ax=ax, facecolor=COL_LAND_KSA, edgecolor="none", zorder=1.4)
    ksa.boundary.plot(ax=ax, edgecolor=COL_KSA_BORDER, linewidth=0.8, zorder=2)

    sizes = _marker_sizes(dams["capacity_mcm"])
    counts = dams["source"].value_counts()
    groups = [
        ("srtm_derived",     COL_SRTM,   "SRTM-derived",          "v", False),
        ("regi_multi",     COL_REGI,   "Regionalization",       "v", False),
        ("placement_failed", COL_FAILED, "Placement failed",      "x", True),
    ]
    for src, colour, _label, marker, is_failed in groups:
        mask = dams["source"] == src
        if not mask.any():
            continue
        if is_failed:
            ax.scatter(
                dams.loc[mask, "lon"], dams.loc[mask, "lat"],
                s=sizes[mask.values] * 0.7,
                c=colour, linewidth=1.0,
                marker=marker, zorder=5, alpha=0.95,
            )
        else:
            ax.scatter(
                dams.loc[mask, "lon"], dams.loc[mask, "lat"],
                s=sizes[mask.values],
                facecolor=colour, edgecolor="black", linewidth=0.35,
                marker=marker, zorder=4 if src == "regi_multi" else 4.5,
                alpha=0.92,
            )

    ax.set_xlabel("Longitude (°E)", fontsize=10)
    ax.set_ylabel("Latitude (°N)", fontsize=10)
    ax.set_aspect("equal", adjustable="datalim")
    ax.tick_params(length=2.5, direction="out", labelsize=9)
    ax.grid(False)

    src_handles = []
    for src, colour, label, marker, is_failed in groups:
        n = int(counts.get(src, 0))
        if n == 0:
            continue
        if is_failed:
            src_handles.append(
                Line2D([0], [0], marker=marker, color=colour,
                       markerfacecolor="none", markeredgewidth=1.1,
                       linewidth=0, markersize=5.5,
                       label=f"{label} (n = {n})")
            )
        else:
            src_handles.append(
                Line2D([0], [0], marker=marker, color="none",
                       markerfacecolor=colour, markeredgecolor="black",
                       markersize=6, markeredgewidth=0.4,
                       label=f"{label} (n = {n})")
            )
    leg1 = ax.legend(
        handles=src_handles, loc="upper right",
        title="Parameter source", title_fontsize=10, fontsize=10,
        borderpad=0.45, handletextpad=0.45, labelspacing=0.55,
        frameon=True, fancybox=False, edgecolor=COL_BORDER, framealpha=0.92,
    )
    leg1.get_frame().set_linewidth(0.5)
    ax.add_artist(leg1)

    cap_ticks = [0.1, 1.0, 10.0, 100.0]
    cap_sz = _marker_sizes(pd.Series(cap_ticks))
    cap_handles = [
        Line2D([0], [0], marker="v", color="none",
               markerfacecolor="0.35", markeredgecolor="black",
               markeredgewidth=0.35, markersize=np.sqrt(s) * 0.95,
               label=f"{c:g}")
        for c, s in zip(cap_ticks, cap_sz)
    ]
    leg2 = ax.legend(
        handles=cap_handles, loc="lower right",
        title="Capacity (MCM)", title_fontsize=10, fontsize=10,
        borderpad=0.55, handletextpad=0.6, labelspacing=0.95,
        frameon=True, fancybox=False, edgecolor=COL_BORDER, framealpha=0.92,
    )
    leg2.get_frame().set_linewidth(0.5)

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
    """Draw an arrow from (x1, y1) to (x2, y2). If *label* is given, place
    it offset from the arrow midpoint by ``(label_dx, label_dy)`` so it
    sits beside or above the arrow line, never on top of it."""
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


def _draw_panel_b(ax) -> None:
    """Pipeline flowchart on a 0-100 canvas. Box widths match their text
    (no fixed-width forcing) so nothing overflows; Yes/No labels sit beside
    or above their arrows, never on the line."""
    ax.set_xlim(0, 100)
    ax.set_ylim(-3, 100)
    ax.set_axis_off()
    ax.set_aspect("auto")

    cx = 50.0
    w_proc = 95.0      # processing-step box width
    w_six = 95.0       # 6-stage box width
    w_out = 95.0       # output / regionalisation box width
    h_std = 5.0        # uniform sequential-box height
    arrow = 4.0        # uniform arrow length (centre-to-centre minus halves)

    # ---- Inputs (ellipses) ------------------------------------------------
    in_y = 95.0
    in_w = 30.0
    in_h = 9.0
    inputs = [
        (cx - 32.0, in_y, "SRTM"),
        (cx,        in_y, "Dam catalogue"),
        (cx + 32.0, in_y, "MERIT Hydro"),
    ]
    for (x, y, t) in inputs:
        _ellipse(ax, x, y, in_w, in_h, t,
                 facecolor=COL_BOX_INPUT, edgecolor=COL_BOX_INPUT_EDGE,
                 fontsize=10)

    conv_y = 87.5
    for (x, _, _) in inputs:
        ax.plot(
            [x, cx], [in_y - in_h / 2.0, conv_y],
            color="0.35", linewidth=0.7, zorder=1,
        )

    # ---- Snap step --------------------------------------------------------
    snap_y = 81.0
    _box(ax, cx, snap_y, w_proc, h_std,
         "Snap dam to nearest MERIT segment",
         facecolor=COL_BOX_PROC, edgecolor=COL_BOX_PROC_EDGE,
         fontsize=10)

    # ---- 6-stage wall-placement (2-column stage list) --------------------
    # 1 axis unit ~= 1.035 mm at the current figure size, so row_step here
    # is set to put ~1 mm of clear vertical space between successive stage
    # rows; six_h grows to keep the box around the (now-taller) text block.
    six_y = 67.5
    six_h = 17.0
    ax.add_patch(FancyBboxPatch(
        (cx - w_six / 2.0, six_y - six_h / 2.0),
        w_six, six_h,
        boxstyle="round,pad=0.012,rounding_size=1.5",
        linewidth=0.8, facecolor=COL_BOX_HIGHLIGHT,
        edgecolor=COL_BOX_PROC_EDGE, zorder=2,
    ))
    ax.text(
        cx, six_y + six_h / 2.0 - 2.0, "6-stage wall placement:",
        ha="center", va="center",
        fontsize=10, color="0.10", zorder=3,
    )
    stages_left = ["1. Fast path", "2. Upstream walk", "3. Quality recovery"]
    stages_right = ["4. River-direction retry", "5. Relaxed alignment", "6. Multi-direction fallback"]
    col_xs = [cx - w_six / 2.0 + 4.0, cx - 2.0]
    base_y = six_y + 2.0
    row_step = 3.6
    for col, stages in enumerate((stages_left, stages_right)):
        for row, s in enumerate(stages):
            ax.text(
                col_xs[col], base_y - row * row_step, s,
                ha="left", va="center",
                fontsize=10, color="0.10", zorder=3,
            )

    # ---- Sequential processing steps -------------------------------------
    proc = [
        ("Flood fill to spillway height",                  54.0),
        ("EAV curve: 0.5 m bins",                          45.0),
        ("Power-law fit: $V = c \\cdot A^{b}$",            36.0),
        ("Quality grade: A, B, C, D, F",                   27.0),
    ]
    proc_ys = []
    for (text, y) in proc:
        _box(ax, cx, y, w_proc, h_std, text,
             facecolor=COL_BOX_PROC, edgecolor=COL_BOX_PROC_EDGE,
             fontsize=10)
        proc_ys.append(y)

    # ---- Equal-length arrows along the main spine -----------------------
    _arrow(ax, cx, conv_y, cx, snap_y + h_std / 2.0)
    _arrow(ax, cx, snap_y - h_std / 2.0, cx, six_y + six_h / 2.0)
    _arrow(ax, cx, six_y - six_h / 2.0, cx, proc_ys[0] + h_std / 2.0)
    for i in range(len(proc_ys) - 1):
        _arrow(ax, cx, proc_ys[i] - h_std / 2.0,
               cx, proc_ys[i + 1] + h_std / 2.0)

    # ---- Decision (rhombus / diamond) -----------------------------------
    dec_y = 16.5
    dec_w = 30.0
    dec_h = 8.0
    _diamond(ax, cx, dec_y, dec_w, dec_h, "Reliable?", fontsize=10)
    _arrow(ax, cx, proc_ys[-1] - h_std / 2.0,
           cx, dec_y + dec_h / 2.0)

    # ---- Yes branch (right) — arrow same length as the spine arrows -----
    # yes_w is sized so the SRTM-derived box right edge aligns with the
    # spine and Regionalization right edges (cx + w_proc/2).
    yes_w = 28.5
    yes_h = 9.0
    yes_x = cx + dec_w / 2.0 + arrow + yes_w / 2.0
    _box(ax, yes_x, dec_y, yes_w, yes_h, "SRTM-derived",
         facecolor=COL_BOX_OUT_SRTM, edgecolor=COL_SRTM, fontsize=10)
    _arrow(
        ax,
        cx + dec_w / 2.0, dec_y,
        yes_x - yes_w / 2.0, dec_y,
        label="Yes", label_dx=-1.5, label_dy=1.8,
    )

    # ---- No branch (down) — Regionalization box: title + recipe ---------
    regi_y = 3.0
    regi_h = 9.0
    _box(ax, cx, regi_y, w_out, regi_h, "",
         facecolor=COL_BOX_OUT_REGI, edgecolor=COL_REGI)
    ax.text(
        cx, regi_y + 1.8, "Regionalization",
        ha="center", va="center",
        fontsize=10, color="0.10", zorder=3,
    )
    ax.text(
        cx, regi_y - 1.8,
        "Multi-feature LR for $A_\\mathrm{cap}$  +  regional-median $b$",
        ha="center", va="center",
        fontsize=10, color="0.10", zorder=3,
    )
    _arrow(
        ax,
        cx, dec_y - dec_h / 2.0,
        cx, regi_y + regi_h / 2.0,
        label="No", label_dx=3.0, label_dy=0.0,
    )

    panel_label(ax, "b", fontsize=12)


def make_p1_domain(output_dir: str | os.PathLike) -> Path:
    """Render p1 (domain map + flowchart). Returns the PNG path."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_png = out_dir / "p1_domain_flowchart.png"

    # p1 ships with a uniform 10 pt base across every text element; the
    # panel label sits at 10 * 1.2 = 12 pt (overridden at the call site).
    with plt.rc_context({
        "font.size":       10,
        "axes.labelsize":  10,
        "axes.titlesize":  10,
        "xtick.labelsize": 10,
        "ytick.labelsize": 10,
        "legend.fontsize": 10,
    }):
        fig = plt.figure(figsize=(mm_to_in(250.0), mm_to_in(130.0)))
        gs = fig.add_gridspec(
            1, 2,
            width_ratios=[1.10, 1.00],
            wspace=0.12, left=0.05, right=0.995, bottom=0.09, top=0.91,
        )
        _draw_panel_a(fig.add_subplot(gs[0, 0]))
        _draw_panel_b(fig.add_subplot(gs[0, 1]))

        save_panel(fig, out_png)
    plt.close(fig)
    print(f"wrote {out_png}")
    return out_png
