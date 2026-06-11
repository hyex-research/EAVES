"""Panel set p3 — worked example for the bathymetry-validated reservoir (Baish).

Panel a — SRTM DEM with inundated footprint.
Panel b — Area–volume curve on log-log axes with the fitted power law.
Panel c — Histogram of the power-law exponent ``b`` across the trusted set.
"""

from __future__ import annotations

import os
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import eaves.config as _cfg

from ._example import example_dam_id, example_paths, example_summary_row
from ._shared import (
    COL_DATA_BLUE,
    COL_DATA_ORANGE,
    COL_FAILED,
    COL_FIT_BLACK,
    mm_to_in,
    panel_label,
    save_panel,
)


_EXAMPLE_RESULT_CACHE: dict = {}


def _compute_example_dam_result() -> dict:
    """Re-run the placement/flood-fill pipeline for the worked-example dam.

    Returns the `result` dict produced by `process_dam`, containing `dem_utm`,
    `footprint`, `dam_rc`, `footprint_area_km2`, `vol_m3`, `capacity_mcm`,
    `capped`, `construction_year`, etc. Cached so panel rendering only pays the
    cost once per session.
    """
    dam_id = example_dam_id()
    if dam_id in _EXAMPLE_RESULT_CACHE:
        return _EXAMPLE_RESULT_CACHE[dam_id]

    from shapely.geometry import Point
    from ...pipeline.curves import process_dam
    from ...pipeline.terrain import load_srtm_tiles
    from ...utils import buffer_deg_for_dam

    catalogue = pd.read_csv(_cfg.DAMS_CSV)
    cat = catalogue[catalogue["dam_id"] == dam_id]
    if cat.empty:
        raise RuntimeError(f"Dam {dam_id!r} not found in {_cfg.DAMS_CSV}")
    cat = cat.iloc[0]

    dam_height = float(cat["dam_height_m"])
    capacity = float(cat["storage_capacity_m3"])
    spillway = float(cat.get("spillway_height_m", dam_height * 0.75))
    if not np.isfinite(spillway) or spillway <= 0:
        spillway = dam_height * 0.75
    lat = float(cat["latitude"])
    lon = float(cat["longitude"])

    class _Row:
        def __init__(self, data, geom):
            self._d = data
            self.geometry = geom
        def __getitem__(self, k):
            return self._d[k]
        def get(self, k, default=None):
            return self._d.get(k, default)

    dam_data = {k: cat[k] for k in cat.index}
    dam_data["dam_id"] = dam_id
    dam_data["dam_height_m"] = dam_height
    dam_data["spillway_height_m"] = spillway
    dam_data["storage_capacity_m3"] = capacity
    dam_data["latitude"] = lat
    dam_data["longitude"] = lon
    dam_row = _Row(dam_data, Point(lon, lat))

    buf_deg = buffer_deg_for_dam(capacity)
    srtm_data, srtm_tf, srtm_crs = load_srtm_tiles(lat, lon, buffer_deg=buf_deg + 0.02)
    result = process_dam(dam_row, None, srtm_data, srtm_tf, srtm_crs)
    result["dam_id"] = dam_id
    result["dam_name_latin"] = cat.get("dam_name_latin", "") or cat.get("dam_name", "")

    for src in getattr(_cfg, "_srtm_cache", {}).values():
        try:
            src.close()
        except Exception:
            pass

    _EXAMPLE_RESULT_CACHE[dam_id] = result
    return result


def _draw_panel_a(ax) -> "matplotlib.axes.Axes":
    """SRTM DEM around the worked-example reservoir, with the inundated
    footprint outlined and the dam pixel marked. Returns the colorbar axes
    so the caller can shift it in lockstep with ``ax`` if needed."""
    result = _compute_example_dam_result()
    dem = np.asarray(result["dem_utm"], dtype=float)
    fp = np.asarray(result["footprint"], dtype=bool)
    dam_r, dam_c = result["dam_rc"]

    masked = np.where(np.isnan(dem), np.nan, dem)
    im = ax.imshow(masked, cmap="cubehelix", interpolation="nearest")

    flood_overlay = np.ma.masked_where(~fp, np.ones_like(dem))
    ax.imshow(flood_overlay, cmap="Blues", alpha=0.8,
              interpolation="nearest", zorder=4)

    ax.plot(dam_c, dam_r, marker="v",
            markerfacecolor=COL_FAILED, markeredgecolor="black",
            markeredgewidth=0.5, markersize=5, linestyle="none", zorder=5)

    cbar = plt.colorbar(im, ax=ax, shrink=0.85, pad=0.025, aspect=22)
    cbar.set_label("Elevation (m)", fontsize=10)
    cbar.ax.tick_params(labelsize=9, length=2.0)
    cbar.outline.set_linewidth(0.5)

    ax.set_xlabel("Column (px)", fontsize=10)
    ax.set_ylabel("Row (px)", fontsize=10)
    ax.tick_params(labelsize=9, length=2.5)

    capped = bool(result.get("capped", False))
    cap_tag = " [capped]" if capped else ""
    name = result.get("dam_name_latin") or example_dam_id()
    year = result.get("construction_year")
    year_str = f"{int(year)}" if year is not None and np.isfinite(year) else "—"
    area_km2 = float(result["footprint_area_km2"])
    vol_mcm = float(result["vol_m3"][-1]) / 1e6
    cap_mcm = float(result["capacity_mcm"])
    info = (
        f"{name}\n"
        f"Year = {year_str}\n"
        f"Area = {area_km2:.2f} km$^2$\n"
        f"Capacity = {cap_mcm:.1f} MCM"
    )
    ax.text(
        0.02, 0.02, info,
        transform=ax.transAxes, ha="left", va="bottom",
        fontsize=10, color="0.10",
        bbox=dict(boxstyle="round,pad=0.3",
                  facecolor="white", edgecolor="0.6", linewidth=0.5,
                  alpha=0.85),
    )

    panel_label(ax, "a", fontsize=12)


def _draw_panel_b(ax) -> None:
    """Area–volume curve on log-log axes with the fitted power law overlaid."""
    eav_csv, _ = example_paths()
    row = example_summary_row()
    c_fit = float(row["c"])
    b_fit = float(row["b"])
    r2_fit = float(row["r_squared"])

    eav = pd.read_csv(eav_csv)
    mask = (eav["area_m2"] > 0) & (eav["volume_m3"] > 0)
    area = eav.loc[mask, "area_m2"].to_numpy()
    volume = eav.loc[mask, "volume_m3"].to_numpy()

    ax.scatter(
        area, volume,
        s=12, facecolor=COL_DATA_BLUE, edgecolor="white",
        linewidth=0.3, alpha=0.9, zorder=3,
        label="SRTM samples",
    )
    a_grid = np.geomspace(area.min(), area.max(), 200)
    ax.plot(
        a_grid, c_fit * np.power(a_grid, b_fit),
        linestyle="--", color=COL_FIT_BLACK, linewidth=1.2, zorder=4,
        label=r"$V = c \cdot A^{b}$",
    )

    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel(r"Inundated area $A$ (m$^2$)", fontsize=10)
    ax.set_ylabel(r"Storage volume $V$ (m$^3$)", fontsize=10)
    ax.tick_params(labelsize=9, length=2.5)
    ax.grid(True, which="both", linestyle=":", linewidth=0.4, alpha=0.5)

    annotation = (
        f"$c$ = {c_fit:.3g}\n"
        f"$b$ = {b_fit:.3f}\n"
        f"$R^2$ = {r2_fit:.4f}"
    )
    ax.text(
        0.04, 0.96, annotation,
        transform=ax.transAxes, ha="left", va="top",
        fontsize=10, color="0.10",
        bbox=dict(boxstyle="round,pad=0.3",
                  facecolor="white", edgecolor="0.6", linewidth=0.5),
    )
    leg = ax.legend(loc="lower right", frameon=False, fontsize=10)
    for txt in leg.get_texts():
        txt.set_color("0.10")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    panel_label(ax, "b", fontsize=12)


def _draw_panel_c(ax) -> None:
    """Histogram of the power-law exponent b across the trusted-set reservoirs."""
    _, summary_csv = example_paths()
    summary = pd.read_csv(summary_csv)
    ex_row = example_summary_row()
    b_example = float(ex_row["b"])
    example_name = (
        ex_row.get("dam_name_latin")
        or ex_row.get("dam_name")
        or example_dam_id()
    )

    # Canonical trusted-set gates, so n and median b match domain_characterization.csv.
    trusted = summary[
        summary["quality"].isin(["A", "B"])
        & (summary["r_squared"] >= 0.98)
        & summary["vol_ratio"].between(0.3, 5.0)
        & (summary["n_pixels"] >= 50)
        & summary["b"].notna()
    ]
    b_values = trusted["b"].to_numpy()
    n_ab = b_values.size
    median_b = float(np.median(b_values))

    x_min, x_max = 0.5, 3.0
    bins = np.linspace(x_min, x_max, 41)
    b_clipped = np.clip(b_values, x_min, x_max)

    ax.hist(
        b_clipped, bins=bins,
        color=COL_DATA_BLUE, edgecolor="white",
        linewidth=0.4, alpha=0.85,
    )

    for i, bound in enumerate((1.1, 2.0)):
        ax.axvline(
            bound, color="0.45", linestyle="--", linewidth=0.7, zorder=3,
            label="Regional median clip $[1.1, 2.0]$" if i == 0 else None,
        )

    ax.axvline(
        median_b, color=COL_DATA_ORANGE, linestyle="--", linewidth=1.0, zorder=4,
        label=f"Regional median $b$ = {median_b:.2f}",
    )
    ax.axvline(
        b_example, color=COL_FAILED, linestyle="-", linewidth=1.4, zorder=4,
        label=f"{example_name}: $b$ = {b_example:.2f} (n = {n_ab})",
    )

    ax.set_xlim(x_min, x_max)
    ax.set_xlabel(r"Power-law exponent $b$", fontsize=10)
    ax.set_ylabel("Number of reservoirs", fontsize=10)
    ax.tick_params(labelsize=9, length=2.5)
    ax.grid(True, axis="y", linestyle=":", linewidth=0.4, alpha=0.5)
    leg = ax.legend(loc="upper right", frameon=False, fontsize=10)
    for txt in leg.get_texts():
        txt.set_color("0.10")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    panel_label(ax, "c", fontsize=12)


def make_p3_baish(output_dir: str | os.PathLike) -> Path:
    """Render p3 (worked example) as a 2-row panel: DEM (a) + log-log
    fit (b) on the top row, exponent histogram (c) full-width on the bottom.
    Returns the PNG path."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_png = out_dir / "p3_baish_example.png"

    with plt.rc_context({
        "font.size":       10,
        "axes.labelsize":  10,
        "axes.titlesize":  10,
        "xtick.labelsize": 10,
        "ytick.labelsize": 10,
        "legend.fontsize": 10,
    }):
        fig = plt.figure(figsize=(mm_to_in(230), mm_to_in(170)))
        gs = fig.add_gridspec(
            2, 2,
            width_ratios=[1.0, 1.28],
            height_ratios=[1.05, 0.85],
            wspace=0.24, hspace=0.32,
            left=0.07, right=0.985, top=0.95, bottom=0.09,
        )
        ax_a = fig.add_subplot(gs[0, 0])
        _draw_panel_a(ax_a)
        _draw_panel_b(fig.add_subplot(gs[0, 1]))
        ax_c = fig.add_subplot(gs[1, :])
        _draw_panel_c(ax_c)

        # Re-anchor ax_a and its colorbar flush with ax_c's left edge (colorbar steals width).
        fig.canvas.draw()
        pos_a = ax_a.get_position()
        pos_c = ax_c.get_position()
        dx = pos_c.x0 - pos_a.x0
        if abs(dx) > 1e-4:
            ax_a.set_position([pos_a.x0 + dx, pos_a.y0, pos_a.width, pos_a.height])
            for sib in fig.axes:
                if sib is ax_a:
                    continue
                sp = sib.get_position()
                # Colorbar lives just right of panel a (same row, narrow width).
                if sp.y0 > 0.45 and sp.x0 < 0.5 and sp.width < 0.06:
                    sib.set_position([sp.x0 + dx, sp.y0, sp.width, sp.height])

        save_panel(fig, out_png)
    plt.close(fig)
    print(f"wrote {out_png}")
    return out_png
