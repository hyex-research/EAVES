"""Panel set p6: EAVES against the GRDL reference curves.

GRDL reconstructs reservoir bathymetry from the surrounding terrain using a
deep-learning model, with the reservoir boundaries defined mainly by
Landsat-observed water extents. Because both products use SRTM and GRDL is
itself a reconstruction, the comparison assesses consistency rather than
accuracy against measured bathymetry. Each row holds one reference reservoir
of ``GRDL_NAME_MAP``.

Panel a: area-volume curves of GRDL and EAVES.
Panel b: depth-area curves of GRDL and EAVES.
"""

from __future__ import annotations

import os
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import MaxNLocator

import eaves.config as _cfg

from ...utils import dams_with_fill
from ._shared import PANEL_TEXT_RC, mm_to_in, panel_label, save_panel

# ---- Style ----

COL_GRDL = "#9370DB"
COL_EAVES = "#FFA500"


# ---- Data ----

def _read_grdl_csv(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Parses a GRDL csv into (depth_m, area_km2, vol_mcm)."""
    with open(path) as fh:
        lines = fh.readlines()
    data_lines = [l.strip() for l in lines[5:] if l.strip()]
    if not data_lines:
        data_lines = [l.strip() for l in lines[4:] if l.strip()]
    depth, area, vol = [], [], []
    for dl in data_lines:
        parts = dl.split(";")
        if len(parts) >= 3:
            try:
                depth.append(float(parts[0]))
                area.append(float(parts[1]))
                vol.append(float(parts[2]))
            except ValueError:
                continue
    return np.asarray(depth), np.asarray(area), np.asarray(vol)


def load_grdl_comparisons() -> list:
    """Reads the GRDL curve and the EAVES EAV table of every reference dam with a GRDL file."""
    grdl_dir = getattr(_cfg, "GRDL_DIR", None)
    if not grdl_dir:
        raise RuntimeError("GRDL_DIR not configured.")
    name_map = getattr(_cfg, "GRDL_NAME_MAP", {})
    summary = dams_with_fill(pd.read_csv(Path(_cfg.CSV_DIR) / "eaves_summary.csv"))
    out = []
    for stem, dam_id in name_map.items():
        grdl_path = Path(grdl_dir) / f"{stem}.csv"
        if not grdl_path.exists():
            continue
        grdl_depth, grdl_area_km2, grdl_vol_mcm = _read_grdl_csv(grdl_path)
        eav = pd.read_csv(Path(_cfg.EAV_DIR) / f"{dam_id}_eav.csv")
        row = summary[summary["dam_id"] == dam_id]
        dam_name = stem.capitalize()
        if not row.empty:
            dn = row.iloc[0].get("dam_name")
            if dn and str(dn).strip():
                dam_name = str(dn)
        eaves_area_km2 = eav["area_m2"].to_numpy() / 1e6
        eaves_vol_mcm = eav["volume_m3"].to_numpy() / 1e6
        eaves_elev = eav["elevation_m"].to_numpy()
        eaves_depth = eaves_elev - eaves_elev.min()
        out.append({
            "dam_id": dam_id, "dam_name": dam_name,
            "grdl_depth": grdl_depth,
            "grdl_area_km2": grdl_area_km2,
            "grdl_vol_mcm": grdl_vol_mcm,
            "eaves_area_km2": eaves_area_km2,
            "eaves_vol_mcm": eaves_vol_mcm,
            "eaves_depth": eaves_depth,
        })
    return out


# ---- Drawing ----

def _finish_axes(ax, comp: dict, ylabel: str, show_xlabel: bool, show_legend: bool) -> None:
    """Axis labels, grid, the optional key and the dam-name box of one GRDL axes."""
    if show_xlabel:
        ax.set_xlabel(r"Area (km$^2$)", fontsize=10)
    ax.set_ylabel(ylabel, fontsize=10)
    ax.xaxis.set_major_locator(MaxNLocator(nbins=7, steps=[1, 2, 5, 10], integer=True))
    ax.tick_params(labelsize=10, length=2.5)
    ax.grid(True, ls="--", alpha=0.3, lw=0.4)
    if show_legend:
        leg = ax.legend(loc="upper left", frameon=False, fontsize=10,
                        handlelength=1.4, labelspacing=0.3)
        for txt in leg.get_texts():
            txt.set_color("0.10")
    ax.text(
        0.97, 0.04, comp["dam_name"],
        transform=ax.transAxes, ha="right", va="bottom",
        fontsize=10, color="0.10",
        bbox=dict(boxstyle="round,pad=0.3", facecolor="white",
                  edgecolor="0.7", linewidth=0.5, alpha=0.9),
    )


def _draw_grdl_va(ax, comp: dict, show_xlabel: bool = False,
                  show_legend: bool = False) -> None:
    """V vs A, GRDL vs EAVES."""
    ax.plot(comp["grdl_area_km2"], comp["grdl_vol_mcm"],
            color=COL_GRDL, marker="o", lw=1.2, ms=3, label="GRDL")
    ax.plot(comp["eaves_area_km2"], comp["eaves_vol_mcm"],
            color=COL_EAVES, lw=1.2, label="EAVES")
    _finish_axes(ax, comp, "Volume (MCM)", show_xlabel, show_legend)


def _draw_grdl_da(ax, comp: dict, show_xlabel: bool = False,
                  show_legend: bool = False) -> None:
    """Depth vs A, GRDL vs EAVES."""
    ax.plot(comp["grdl_area_km2"], comp["grdl_depth"],
            color=COL_GRDL, marker="o", lw=1.2, ms=3, label="GRDL")
    ax.plot(comp["eaves_area_km2"], comp["eaves_depth"],
            color=COL_EAVES, lw=1.2, label="EAVES")
    _finish_axes(ax, comp, "Depth (m)", show_xlabel, show_legend)


def make_p6_grdl_comparison(output_dir: str | os.PathLike) -> Path:
    """Renders p6, the GRDL comparison with one row per reference reservoir.

    Left column:  panel a (area-volume curves of GRDL and EAVES).
    Right column: panel b (depth-area curves of GRDL and EAVES).
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_png = out_dir / "p6_grdl_comparison.png"

    grdl = load_grdl_comparisons()
    if not grdl:
        raise RuntimeError(f"No GRDL curve of GRDL_NAME_MAP found in {_cfg.GRDL_DIR}")
    n_dams = len(grdl)

    with plt.rc_context(PANEL_TEXT_RC):
        fig, axes = plt.subplots(
            n_dams, 2, squeeze=False,
            figsize=(mm_to_in(187.0), mm_to_in(62.0 * n_dams + 3.0)),
        )
        fig.subplots_adjust(left=0.087, right=0.983, top=0.965, bottom=0.075,
                            hspace=0.22, wspace=0.24)
        for i, comp in enumerate(grdl):
            is_first, is_last = i == 0, i == n_dams - 1
            _draw_grdl_va(axes[i, 0], comp, show_xlabel=is_last, show_legend=is_first)
            _draw_grdl_da(axes[i, 1], comp, show_xlabel=is_last, show_legend=is_first)
        panel_label(axes[0, 0], "a", fontsize=12)
        panel_label(axes[0, 1], "b", fontsize=12)

        # Opens the axes by hiding the top and right spines across the panel set
        for _ax in fig.axes:
            _ax.spines["top"].set_visible(False)
            _ax.spines["right"].set_visible(False)

        save_panel(fig, out_png)
    plt.close(fig)
    print(f"wrote {out_png}")
    return out_png
