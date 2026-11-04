"""Panel set p5: Baish comparison and domain-wide volume ratio.

The sonar survey measures the present-day bathymetry of Baish rather than the
pre-impoundment valley that SRTM records, so the Baish comparison is a
consistency check, not ground truth.

Panel a: area-volume curves at Baish from the SRTM-derived fill, the 2025
         sonar survey and the design table, with the power-law fit of the
         SRTM curve.
Panel b: elevation-area curves at Baish from the same three sources, with
         the top of dead storage, the lowest level of the design and survey
         tables, marked.
Panel c: distribution of (recovered maximum volume / catalog capacity) over
         the dams with a recovered footprint, with the volume-ratio windows
         of grades A and B marked.
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
from ...utils import fit_power_law as _canon_fit
from ._example import example_dam_id, example_paths, example_summary_row
from ._shared import (
    COL_FAILED,
    PANEL_TEXT_RC,
    _style_legend,
    mm_to_in,
    panel_label,
    save_panel,
)

# ---- Style ----

COL_SONAR = "#6495ED"
COL_SRTM_CURVE = "#FFA500"
COL_DESIGN = "#228B22"


# ---- Data ----

def _load_bathy_validation_data() -> dict:
    """Reads the sonar bathymetry from ``BATHYMETRY_EAV_CSV`` and the SRTM EAV
    table of the example dam.
    """
    bathy_csv = getattr(_cfg, "BATHYMETRY_EAV_CSV", None)
    if not bathy_csv or not os.path.isfile(bathy_csv):
        raise RuntimeError(f"BATHYMETRY_EAV_CSV not configured or missing: {bathy_csv!r}")
    bathy = pd.read_csv(bathy_csv)
    eav_path, _ = example_paths()
    eav = pd.read_csv(eav_path)
    return {
        "elev_son": bathy["elevation_m"].to_numpy(),
        "area_son_km2": bathy["area_m2_integrated_dem"].to_numpy() / 1e6,
        "vol_son_mcm": bathy["volume_m3_integrated_dem"].to_numpy() / 1e6,
        "elev_srt": eav["elevation_m"].to_numpy(),
        "area_srt_km2": eav["area_m2"].to_numpy() / 1e6,
        "vol_srt_mcm": eav["volume_m3"].to_numpy() / 1e6,
        "area_des_km2": bathy["area_m2_design"].to_numpy() / 1e6,
        "vol_des_mcm": bathy["volume_m3_design"].to_numpy() / 1e6,
    }


# ---- Drawing ----

def _bathy_dam_label(ax, x: float, y: float, ha: str, va: str) -> None:
    """Boxed dam-name annotation of the Baish panels at (x, y) in axes coordinates."""
    ex_row = example_summary_row()
    name = ex_row.get("dam_name") or example_dam_id()
    ax.text(
        x, y, f"{name}",
        transform=ax.transAxes, ha=ha, va=va,
        fontsize=10, color="0.10",
        bbox=dict(boxstyle="round,pad=0.3", facecolor="white",
                  edgecolor="0.7", linewidth=0.5, alpha=0.9),
    )


def _draw_bathy_va(ax, data: dict) -> None:
    """Panel a, V vs A from sonar, SRTM and the design table, with the SRTM fit."""
    a_son = data["area_son_km2"]
    v_son = data["vol_son_mcm"]
    a_srt = data["area_srt_km2"]
    v_srt = data["vol_srt_mcm"]
    a_des = data["area_des_km2"]
    v_des = data["vol_des_mcm"]

    ax.plot(a_son, v_son, color=COL_SONAR, lw=1.4, label="Survey")
    ax.plot(a_srt, v_srt, color=COL_SRTM_CURVE, lw=1.4, label="SRTM")
    ax.plot(a_des, v_des, color=COL_DESIGN, lw=1.4, label="Design")

    # Fits c and b with the pipeline power-law fit behind eaves_params.csv
    c_srt_si, b_srt, _ = _canon_fit(a_srt * 1e6, v_srt * 1e6)
    # Converts c to the km^2/MCM system: V_mcm = c_si * 1e6^(b-1) * A_km2^b
    c_srt = c_srt_si * 1e6 ** (b_srt - 1)
    a_g = np.linspace(0, a_srt.max(), 200)
    ax.plot(a_g, c_srt * a_g ** b_srt, color="#8B0000", ls=(0, (4, 2.5)), lw=1.1, zorder=3,
            label=f"SRTM fit\nc = {c_srt_si:.4g}\nb = {b_srt:.4f}")

    # Leaves headroom above the curves for the key
    ax.set_ylim(-0.04 * v_srt.max(), 1.55 * max(v_son.max(), v_srt.max(), v_des.max()))
    ax.set_xlabel(r"Area (km$^2$)", fontsize=10)
    ax.set_ylabel("Volume (MCM)", fontsize=10)
    ax.xaxis.set_major_locator(MaxNLocator(nbins=5, integer=True))
    ax.tick_params(labelsize=10, length=2.5)
    ax.grid(True, ls="--", alpha=0.3, lw=0.4)
    _bathy_dam_label(ax, 0.97, 0.04, "right", "bottom")
    _style_legend(ax.legend(loc="upper left", frameon=False, fontsize=10,
                            handlelength=1.2, handletextpad=0.4, labelspacing=0.25,
                            borderaxespad=0.2))
    panel_label(ax, "a", fontsize=12)


def _draw_bathy_ea(ax, data: dict) -> None:
    """Panel b, elevation vs A from sonar, SRTM and the design table."""
    ax.plot(data["area_son_km2"], data["elev_son"],
            color=COL_SONAR, lw=1.4, label="Survey")
    ax.plot(data["area_srt_km2"], data["elev_srt"],
            color=COL_SRTM_CURVE, lw=1.4, label="SRTM")
    ax.plot(data["area_des_km2"], data["elev_son"],
            color=COL_DESIGN, lw=1.4, label="Design")
    # The design and survey tables start at the top of dead storage
    z_dead = float(data["elev_son"].min())
    ax.axhline(z_dead, color="0.45", ls="--", lw=1.2, zorder=1.5)
    ax.annotate("Dead storage", xy=(0.97, z_dead),
                xycoords=ax.get_yaxis_transform(), xytext=(0, -2),
                textcoords="offset points", ha="right", va="top",
                fontsize=10, color="0.30")
    ax.set_xlabel(r"Area (km$^2$)", fontsize=10)
    ax.set_ylabel("Elevation (m a.s.l.)", fontsize=10)
    ax.xaxis.set_major_locator(MaxNLocator(nbins=5, integer=True))
    ax.tick_params(labelsize=10, length=2.5)
    ax.grid(True, ls="--", alpha=0.3, lw=0.4)
    _bathy_dam_label(ax, 0.08, 0.97, "left", "top")
    # The key sits between the dead-storage line and the curves
    _style_legend(ax.legend(loc="center right", bbox_to_anchor=(1.0, 0.36),
                            frameon=False, fontsize=10,
                            handlelength=1.2, handletextpad=0.4, labelspacing=0.3,
                            borderaxespad=0.2))
    panel_label(ax, "b", fontsize=12)


def _draw_panel_c(ax) -> None:
    """Panel c, distribution of (recovered maximum volume / catalog capacity), with the interquartile range."""
    summary_csv = Path(_cfg.CSV_DIR) / "eaves_summary.csv"
    df = dams_with_fill(pd.read_csv(summary_csv))
    vr = df["vol_ratio"].dropna().to_numpy()
    vr = vr[vr > 0]

    n_total = len(vr)
    # Counts the fills inside the volume-ratio windows of grades A and B
    n_win_a = int(((vr >= 0.5) & (vr <= 2.0)).sum())
    n_win_b = int(((vr >= 0.3) & (vr <= 5.0)).sum())
    pct_a = 100.0 * n_win_a / n_total
    pct_b = 100.0 * n_win_b / n_total
    median_vr = float(np.median(vr))
    q25, q75 = float(np.quantile(vr, 0.25)), float(np.quantile(vr, 0.75))

    # Bins ten per decade with one bin centered on a ratio of 1, the axis spans 1.5 decades below the smallest bin for the key to just past the wider window or the largest ratio
    dec_lo = int(np.floor(np.log10(vr.min())))
    dec_hi = int(np.ceil(np.log10(max(5.0, vr.max()))))
    bins = 10.0 ** (np.arange(10 * dec_lo, 10 * dec_hi + 2) / 10.0 - 0.05)
    x_lo = 10.0 ** (dec_lo - 1.5)
    x_hi = 1.2 * max(5.0, vr.max())

    ax.axvspan(0.5, 2.0, color="#FBC678", alpha=0.6, zorder=1,
               label=f"Volume ratio\nin [0.5, 2.0]\n(n = {n_win_a}, {pct_a:.0f}%)")
    ax.axvspan(0.3, 5.0, color="#F9DC9A", alpha=0.7, zorder=0,
               label=f"Volume ratio\nin [0.3, 5.0]\n(n = {n_win_b}, {pct_b:.0f}%)")

    counts, _, _ = ax.hist(
        vr, bins=bins,
        color="0.35", edgecolor="none", zorder=2,
    )

    # Draws the reference lines under the bars, the ideal ratio as a wide gray line under the median and quartile lines
    ax.axvline(1.0, color="0.65", ls="-", lw=3.5, zorder=1.4,
               label="Ideal ratio = 1")
    ax.axvline(median_vr, color=COL_FAILED, ls="--", lw=1.7, zorder=1.6,
               label=f"Median = {median_vr:.2f}")
    ax.axvline(q25, color=COL_FAILED, ls=":", lw=1.3, zorder=1.6,
               label=f"Interquartile\nrange\n[{q25:.2f}, {q75:.2f}]")
    ax.axvline(q75, color=COL_FAILED, ls=":", lw=1.3, zorder=1.6)
    # Leaves a band over the tallest bar where the reference lines show
    ax.set_ylim(0.0, 1.15 * float(counts.max()))

    ax.set_xscale("log")
    ax.set_xlim(x_lo, x_hi)
    ax.set_xlabel(r"Volume ratio  ($V_\mathrm{SRTM}/V_\mathrm{cap}$)",
                  fontsize=10)
    ax.set_ylabel(f"Number of dams (n = {n_total})", fontsize=10)
    ax.tick_params(labelsize=10, length=2.5)
    ax.grid(True, which="both", axis="x", linestyle=":", linewidth=0.4, alpha=0.5)
    _style_legend(ax.legend(loc="upper left", frameon=False, fontsize=10,
                            handlelength=1.0, handletextpad=0.4, labelspacing=0.25,
                            borderaxespad=0.2, borderpad=0.2))
    panel_label(ax, "c", fontsize=12)


def make_p5_comparison(output_dir: str | os.PathLike) -> Path:
    """Renders p5, the Baish comparison and the domain-wide volume ratio in one row.

    Panel a: Baish area-volume curves with the SRTM fit.
    Panel b: Baish elevation-area curves.
    Panel c: volume-ratio histogram over the dams with a flood fill.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_png = out_dir / "p5_comparison.png"

    bathy = _load_bathy_validation_data()

    with plt.rc_context(PANEL_TEXT_RC):
        fig = plt.figure(figsize=(mm_to_in(187.0), mm_to_in(85.0)))
        gs = fig.add_gridspec(
            1, 3,
            width_ratios=[41.0, 40.0, 58.0],
            wspace=0.36,
            left=0.0865, right=0.986, top=0.91, bottom=0.14,
        )
        _draw_bathy_va(fig.add_subplot(gs[0, 0]), bathy)
        _draw_bathy_ea(fig.add_subplot(gs[0, 1]), bathy)
        _draw_panel_c(fig.add_subplot(gs[0, 2]))

        # Opens the axes by hiding the top and right spines across the panel set
        for _ax in fig.axes:
            _ax.spines["top"].set_visible(False)
            _ax.spines["right"].set_visible(False)

        save_panel(fig, out_png)
    plt.close(fig)
    print(f"wrote {out_png}")
    return out_png
