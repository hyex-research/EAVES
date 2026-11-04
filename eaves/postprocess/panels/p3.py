"""Panel set p3: EAVES outputs at the reservoir with sonar bathymetry (Baish) and the distribution of fitted exponents.

Panel a: SRTM DEM with inundated footprint.
Panel b: Area-volume curve on log-log axes with the fitted power law, its
    coefficients, R² on untransformed volumes and the root-mean-square
    fractional residual.
Panel c: Histogram of the unconstrained power-law exponent ``b`` across the trusted set,
    with the trusted-set median, the example dam and the lower bound of the
    released exponent marked.
"""

from __future__ import annotations

import os
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from shapely.geometry import Point

import eaves.config as _cfg

from ...pipeline.curves import DamRow, process_dam
from ...pipeline.terrain import load_srtm_tiles
from ...utils import buffer_deg_for_dam, dams_with_fill
from ..reliability import trusted_mask
from ._example import example_dam_id, example_paths, example_summary_row
from ._shared import (
    COL_DATA_BLUE,
    COL_DATA_ORANGE,
    COL_FAILED,
    COL_FIT_BLACK,
    PANEL_TEXT_RC,
    mm_to_in,
    panel_label,
    save_panel,
)

_EXAMPLE_RESULT_CACHE: dict = {}


def _compute_example_dam_result() -> dict:
    """Re-run the placement/flood-fill pipeline for the worked-example dam.

    Returns the ``result`` dict of ``process_dam``, with ``dem_utm``,
    ``footprint``, ``dam_rc``, ``footprint_area_km2``, ``capacity_mcm`` and
    ``construction_year`` among its keys, cached per session.
    """
    dam_id = example_dam_id()
    if dam_id in _EXAMPLE_RESULT_CACHE:
        return _EXAMPLE_RESULT_CACHE[dam_id]

    catalog = pd.read_csv(_cfg.DAMS_CSV)
    cat = catalog[catalog["dam_id"] == dam_id]
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

    dam_data = {k: cat[k] for k in cat.index}
    dam_data["dam_id"] = dam_id
    dam_data["dam_height_m"] = dam_height
    dam_data["spillway_height_m"] = spillway
    dam_data["storage_capacity_m3"] = capacity
    dam_data["latitude"] = lat
    dam_data["longitude"] = lon
    dam_row = DamRow(dam_data, Point(lon, lat))

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


def _draw_panel_a(ax) -> None:
    """SRTM DEM around the worked-example reservoir, with the inundated footprint overlaid and the dam pixel marked."""
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
    cbar.ax.tick_params(labelsize=10, length=2.0)
    cbar.outline.set_linewidth(0.5)

    ax.set_xlabel("Column (grid cells)", fontsize=10)
    ax.set_ylabel("Row (grid cells)", fontsize=10)
    ax.tick_params(labelsize=10, length=2.5)

    name = result.get("dam_name_latin") or example_dam_id()
    year = result.get("construction_year")
    year_str = f"{int(year)}" if year is not None and np.isfinite(year) else "n/a"
    area_km2 = float(result["footprint_area_km2"])
    cap_mcm = float(result["capacity_mcm"])
    info = (
        f"{name}\n"
        f"Year = {year_str}\n"
        f"Area = {area_km2:.2f} km$^2$\n"
        f"Capacity = {cap_mcm:.2f} MCM"
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


def _example_rms_frac_resid() -> float:
    """Root-mean-square fractional residual of the worked-example fit, read from
    ``<CSV_DIR>/validation/goodness_of_fit.csv``."""
    p = Path(_cfg.CSV_DIR) / "validation" / "goodness_of_fit.csv"
    if not p.exists():
        raise RuntimeError(
            f"Missing {p}. Run: python -m eaves.postprocess.validation "
            f"--settings <settings>.json"
        )
    gof = pd.read_csv(p)
    row = gof[gof["dam_id"] == example_dam_id()]
    if row.empty:
        raise RuntimeError(f"Dam {example_dam_id()!r} not found in {p}")
    return float(row.iloc[0]["rms_frac_resid"])


def _draw_panel_b(ax) -> None:
    """Area-volume curve on log-log axes with the fitted power law overlaid,
    annotated with c, b, R² on untransformed volumes and the root-mean-square
    fractional residual."""
    eav_csv, _ = example_paths()
    row = example_summary_row()
    c_fit = float(row["c"])
    b_fit = float(row["b"])
    r2_fit = float(row["r_squared"])
    rms_frac = _example_rms_frac_resid()

    eav = pd.read_csv(eav_csv)
    mask = (eav["area_m2"] > 0) & (eav["volume_m3"] > 0)
    area = eav.loc[mask, "area_m2"].to_numpy()
    volume = eav.loc[mask, "volume_m3"].to_numpy()

    ax.scatter(
        area, volume,
        s=12, facecolor=COL_DATA_BLUE, edgecolor="white",
        linewidth=0.3, alpha=0.9, zorder=3,
        label="SRTM area-volume pairs",
    )
    a_grid = np.geomspace(area.min(), area.max(), 200)
    ax.plot(
        a_grid, c_fit * np.power(a_grid, b_fit),
        linestyle="--", color=COL_FIT_BLACK, linewidth=1.2, zorder=4,
        label=r"$V = c \cdot A^{b}$",
    )

    ax.set_xscale("log")
    ax.set_yscale("log")
    # Leaves headroom above the curve for the annotation box
    log_lo, log_hi = np.log10(volume.min()), np.log10(volume.max())
    span = log_hi - log_lo
    ax.set_ylim(10.0 ** (log_lo - 0.05 * span), 10.0 ** (log_hi + 0.5 * span))
    ax.set_xlabel(r"Inundated area $A$ (m$^2$)", fontsize=10)
    ax.set_ylabel(r"Storage volume $V$ (m$^3$)", fontsize=10)
    ax.tick_params(labelsize=10, length=2.5)
    ax.grid(True, which="both", linestyle=":", linewidth=0.4, alpha=0.5)

    annotation = (
        f"$c$ = {c_fit:.4g}\n"
        f"$b$ = {b_fit:.4f}\n"
        f"$R^2$ (untransformed) = {r2_fit:.4f}\n"
        f"RMS fractional residual = {rms_frac:.2f}"
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
    """Histogram of the unconstrained power-law exponent b across the trusted dams."""
    _, summary_csv = example_paths()
    summary = dams_with_fill(pd.read_csv(summary_csv))
    ex_row = example_summary_row()
    b_example = float(ex_row["b"])
    example_name = (
        ex_row.get("dam_name_latin")
        or ex_row.get("dam_name")
        or example_dam_id()
    )

    # The trusted set, the same as in domain_characterization.csv
    trusted = summary[trusted_mask(summary)]
    b_values = trusted["b"].to_numpy()
    n_ab = b_values.size
    median_b = float(np.median(b_values))

    bin_lo, bin_hi = 0.5, 3.0
    bins = np.linspace(bin_lo, bin_hi, 41)
    b_clipped = np.clip(b_values, bin_lo, bin_hi)
    # Axis limits one bin outside the bins that hold the trusted-set exponents
    width = bins[1] - bins[0]
    x_min = bins[np.searchsorted(bins, b_clipped.min(), side="right") - 1] - width
    x_max = bins[np.searchsorted(bins, b_clipped.max(), side="left")] + width

    ax.hist(
        b_clipped, bins=bins,
        color=COL_DATA_BLUE, edgecolor="white",
        linewidth=0.4, alpha=0.85,
    )

    ax.axvline(
        _cfg.B_LOWER_BOUND, color="0.45", linestyle="--", linewidth=1.2, zorder=3,
        label="Lower bound of released $b$",
    )

    ax.axvline(
        median_b, color=COL_DATA_ORANGE, linestyle="--", linewidth=1.6, zorder=4,
        label=f"Trusted-set median $b$ = {median_b:.2f} (n = {n_ab})",
    )
    ax.axvline(
        b_example, color=COL_FAILED, linestyle="-", linewidth=2.0, zorder=4,
        label=f"{example_name}: $b$ = {b_example:.4f}",
    )

    ax.set_xlim(x_min, x_max)
    ax.set_xlabel(r"Power-law exponent $b$", fontsize=10)
    ax.set_ylabel("Number of reservoirs", fontsize=10)
    ax.tick_params(labelsize=10, length=2.5)
    ax.grid(True, axis="y", linestyle=":", linewidth=0.4, alpha=0.5)
    leg = ax.legend(loc="upper right", frameon=False, fontsize=10)
    for txt in leg.get_texts():
        txt.set_color("0.10")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    panel_label(ax, "c", fontsize=12)


def make_p3_baish(output_dir: str | os.PathLike) -> Path:
    """Renders p3 (worked example) as a 2-row panel: DEM (a) + log-log
    fit (b) on the top row, exponent histogram (c) full-width on the bottom.
    Returns the PNG path."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_png = out_dir / "p3_baish_example.png"

    with plt.rc_context(PANEL_TEXT_RC):
        fig = plt.figure(figsize=(mm_to_in(187.0), mm_to_in(148.0)))
        gs = fig.add_gridspec(
            2, 2,
            width_ratios=[1.0, 1.0],
            height_ratios=[1.0, 0.85],
            wspace=0.42, hspace=0.32,
            left=0.0864, right=0.9771, top=0.95, bottom=0.09,
        )
        ax_a = fig.add_subplot(gs[0, 0])
        _draw_panel_a(ax_a)
        ax_b = fig.add_subplot(gs[0, 1])
        _draw_panel_b(ax_b)
        ax_c = fig.add_subplot(gs[1, :])
        _draw_panel_c(ax_c)

        # Re-anchors ax_a and its colorbar flush with the left edge of ax_c and the top of ax_b
        fig.canvas.draw()
        pos_a = ax_a.get_position()
        pos_b = ax_b.get_position()
        pos_c = ax_c.get_position()
        dx = pos_c.x0 - pos_a.x0
        dy = pos_b.y1 - pos_a.y1
        if abs(dx) > 1e-4 or abs(dy) > 1e-4:
            ax_a.set_position([pos_a.x0 + dx, pos_a.y0 + dy, pos_a.width, pos_a.height])
            for sib in fig.axes:
                if sib is ax_a:
                    continue
                sp = sib.get_position()
                # The colorbar sits just right of panel a (same row, narrow width)
                if sp.y0 > 0.45 and sp.x0 < 0.5 and sp.width < 0.06:
                    sib.set_position([sp.x0 + dx, sp.y0 + dy, sp.width, sp.height])

        save_panel(fig, out_png)
    plt.close(fig)
    print(f"wrote {out_png}")
    return out_png
