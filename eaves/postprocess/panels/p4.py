"""Panel set p4 — comparison against independently-produced datasets.

Not a validation in the strict sense: both anchors below use methodologies
distinct from EAVES (sonar measures the current operational bathymetry,
GRDL fuses Landsat extents with an external DEM) so we present them as
cross-references rather than ground truth.

Panel a — sonar bathymetry vs SRTM for the Baish reservoir (V-A and E-A).
Panel b — GRDL Landsat-derived extents vs EAVES SRTM for three reference dams.
Panel c — distribution of (SRTM spillway volume / catalogue capacity) over the
          full domain, with Grade A/B reliability bands.
"""

from __future__ import annotations

import os
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import eaves.config as _cfg

from ._example import example_dam_id, example_summary_row
from ._shared import (
    COL_FAILED,
    COL_GRADE_A_BAND,
    COL_GRADE_B_BAND,
    P4_BLUE,
    P4_VERM,
    mm_to_in,
    panel_label,
    save_panel,
)


def _read_grdl_csv(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Parse a GRDL csv. Returns (depth_m, area_km2, vol_mcm)."""
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


def _load_bathy_validation_data() -> dict:
    """Read sonar bathymetry from ``BATHYMETRY_EAV_CSV`` and the example dam's
    SRTM EAV table directly. No intermediate ``bathymetry_validation.csv`` is
    required.
    """
    bathy_csv = getattr(_cfg, "BATHYMETRY_EAV_CSV", None)
    if not bathy_csv or not os.path.isfile(bathy_csv):
        raise RuntimeError(f"BATHYMETRY_EAV_CSV not configured or missing: {bathy_csv!r}")
    bathy = pd.read_csv(bathy_csv)
    eav_path = Path(_cfg.EAV_DIR) / f"{example_dam_id()}_eav.csv"
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


def _load_grdl_comparisons() -> list:
    grdl_dir = getattr(_cfg, "GRDL_DIR", None)
    if not grdl_dir:
        raise RuntimeError("GRDL_DIR not configured.")
    name_map = getattr(_cfg, "GRDL_NAME_MAP", {})
    summary = pd.read_csv(Path(_cfg.CSV_DIR) / "eaves_summary.csv")
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


def _bathy_dam_label(ax) -> None:
    """Bottom-right dam-name annotation for panel a (Baish bathy plots)."""
    ex_row = example_summary_row()
    name = ex_row.get("dam_name") or example_dam_id()
    ax.text(
        0.97, 0.04, f"{name}",
        transform=ax.transAxes, ha="right", va="bottom",
        fontsize=10, color="0.10",
        bbox=dict(boxstyle="round,pad=0.3", facecolor="white",
                  edgecolor="0.7", linewidth=0.5, alpha=0.9),
    )


def _draw_bathy_va(ax, data: dict, panel_label_char=None) -> None:
    """V vs A for sonar vs SRTM."""
    a_son = data["area_son_km2"]
    v_son = data["vol_son_mcm"]
    a_srt = data["area_srt_km2"]
    v_srt = data["vol_srt_mcm"]
    a_des = data["area_des_km2"]
    v_des = data["vol_des_mcm"]

    ax.plot(a_son, v_son, color="#6495ED", lw=1.4, label="Bathymetry (2025 sonar)")
    ax.plot(a_srt, v_srt, color="#FFA500", lw=1.4, label="SRTM (pre-dam valley)")
    ax.plot(a_des, v_des, color="#228B22", lw=1.4, label="Design (documented)")

    # Canonical pipeline fit so c, b match the shipped eaves_params.csv.
    from ...utils import fit_power_law as _canon_fit
    c_son_si, b_son, _ = _canon_fit(a_son * 1e6, v_son * 1e6)
    c_srt_si, b_srt, _ = _canon_fit(a_srt * 1e6, v_srt * 1e6)
    # Convert c to the km^2/MCM system: V_mcm = c_si * 1e6^(b-1) * A_km2^b.
    c_son = c_son_si * 1e6 ** (b_son - 1)
    c_srt = c_srt_si * 1e6 ** (b_srt - 1)
    a_g = np.linspace(0, a_son.max(), 200)
    ax.plot(a_g, c_son * a_g ** b_son, color="#6495ED", ls="--", lw=0.8, alpha=0.7,
            label=f"Bathy fit: c={c_son_si:.4g}, b={b_son:.4f}")
    a_g = np.linspace(0, a_srt.max(), 200)
    ax.plot(a_g, c_srt * a_g ** b_srt, color="#FFA500", ls="--", lw=0.8, alpha=0.7,
            label=f"SRTM fit: c={c_srt_si:.4g}, b={b_srt:.4f}")

    ax.set_xlabel(r"Area (km$^2$)", fontsize=10)
    ax.set_ylabel("Volume (MCM)", fontsize=10)
    ax.tick_params(labelsize=10, length=2.5)
    ax.grid(True, ls="--", alpha=0.3, lw=0.4)
    _bathy_dam_label(ax)
    leg = ax.legend(loc="upper left", frameon=False, fontsize=10,
                    handlelength=1.4, labelspacing=0.3)
    for txt in leg.get_texts():
        txt.set_color("0.10")
    if panel_label_char:
        panel_label(ax, panel_label_char, fontsize=12)


def _draw_bathy_ea(ax, data: dict) -> None:
    """Elevation vs A for sonar vs SRTM."""
    ax.plot(data["area_son_km2"], data["elev_son"],
            color="#6495ED", lw=1.4, label="Bathymetry")
    ax.plot(data["area_srt_km2"], data["elev_srt"],
            color="#FFA500", lw=1.4, label="SRTM")
    ax.plot(data["area_des_km2"], data["elev_son"],
            color="#228B22", lw=1.4, label="Design")
    ax.set_xlabel(r"Area (km$^2$)", fontsize=10)
    ax.set_ylabel("Elevation (m asl)", fontsize=10)
    ax.tick_params(labelsize=10, length=2.5)
    ax.grid(True, ls="--", alpha=0.3, lw=0.4)
    _bathy_dam_label(ax)
    leg = ax.legend(loc="upper left", frameon=False, fontsize=10,
                    handlelength=1.4, labelspacing=0.3)
    for txt in leg.get_texts():
        txt.set_color("0.10")


def _draw_grdl_va(ax, comp: dict, show_xlabel: bool = False,
                  panel_label_char=None) -> None:
    """V vs A — GRDL vs EAVES."""
    ax.plot(comp["grdl_area_km2"], comp["grdl_vol_mcm"],
            color="#9370DB", marker="o", lw=1.2, ms=3, label="GRDL")
    ax.plot(comp["eaves_area_km2"], comp["eaves_vol_mcm"],
            color="#FFA500", lw=1.2, label="SRTM")
    if show_xlabel:
        ax.set_xlabel(r"Area (km$^2$)", fontsize=10)
    ax.set_ylabel("Volume (MCM)", fontsize=10)
    ax.tick_params(labelsize=10, length=2.5)
    if not show_xlabel:
        ax.tick_params(labelbottom=False)
    ax.grid(True, ls="--", alpha=0.3, lw=0.4)
    leg = ax.legend(loc="upper left", frameon=False, fontsize=10,
                    handlelength=1.4, labelspacing=0.3)
    for txt in leg.get_texts():
        txt.set_color("0.10")
    if panel_label_char:
        panel_label(ax, panel_label_char, fontsize=12)


def _draw_grdl_da(ax, comp: dict, show_xlabel: bool = True,
                  show_ylabel: bool = True) -> None:
    """Depth vs A — GRDL vs EAVES."""
    ax.plot(comp["grdl_area_km2"], comp["grdl_depth"],
            color="#9370DB", marker="o", lw=1.2, ms=3, label="GRDL")
    ax.plot(comp["eaves_area_km2"], comp["eaves_depth"],
            color="#FFA500", lw=1.2, label="SRTM")
    if show_xlabel:
        ax.set_xlabel(r"Area (km$^2$)", fontsize=10)
    if show_ylabel:
        ax.set_ylabel("Depth (m)", fontsize=10)
    ax.tick_params(labelsize=10, length=2.5)
    ax.grid(True, ls="--", alpha=0.3, lw=0.4)
    leg = ax.legend(loc="upper left", frameon=False, fontsize=10,
                    handlelength=1.4, labelspacing=0.3)
    for txt in leg.get_texts():
        txt.set_color("0.10")


def _draw_panel_c(ax) -> None:
    """Distribution of (SRTM spillway volume / catalogue capacity), with IQR."""
    summary_csv = Path(_cfg.CSV_DIR) / "eaves_summary.csv"
    df = pd.read_csv(summary_csv)
    vr = df["vol_ratio"].dropna().to_numpy()
    vr = vr[vr > 0]

    n_total = len(vr)
    n_grade_a = int(((vr >= 0.5) & (vr <= 2.0)).sum())
    n_grade_b = int(((vr >= 0.3) & (vr <= 5.0)).sum())
    pct_a = 100.0 * n_grade_a / n_total
    pct_b = 100.0 * n_grade_b / n_total
    median_vr = float(np.median(vr))
    q25, q75 = float(np.quantile(vr, 0.25)), float(np.quantile(vr, 0.75))

    x_lo, x_hi = 0.01, 100.0
    bins = np.logspace(np.log10(x_lo), np.log10(x_hi), 41)

    ax.axvspan(0.5, 2.0, color="#FBC678", alpha=0.6, zorder=1,
               label=f"Grade A [0.5, 2.0]   (n = {n_grade_a}, {pct_a:.0f}%)")
    ax.axvspan(0.3, 5.0, color="#FCEAC0", alpha=0.5, zorder=0,
               label=f"Grade B [0.3, 5.0]   (n = {n_grade_b}, {pct_b:.0f}%)")

    ax.hist(
        vr, bins=bins,
        color="0.35", edgecolor="white", linewidth=0.3, zorder=2,
    )

    ax.axvline(1.0, color="black", ls="-", lw=1.5, zorder=3,
               label="Ideal ratio = 1")
    ax.axvline(median_vr, color=COL_FAILED, ls="--", lw=1.7, zorder=3,
               label=f"Median = {median_vr:.2f}")
    ax.axvline(q25, color=COL_FAILED, ls=":", lw=1.3, zorder=3,
               label=f"IQR = [{q25:.2f}, {q75:.2f}]")
    ax.axvline(q75, color=COL_FAILED, ls=":", lw=1.3, zorder=3)

    ax.set_xscale("log")
    ax.set_xlim(x_lo, x_hi)
    ax.set_xlabel(r"Volume ratio  ($V_\mathrm{SRTM}/V_\mathrm{catalogue}$)",
                  fontsize=10)
    ax.set_ylabel(f"Number of dams (n = {n_total})", fontsize=10)
    ax.tick_params(labelsize=10, length=2.5)
    ax.grid(True, which="both", axis="x", linestyle=":", linewidth=0.4, alpha=0.5)
    leg = ax.legend(loc="upper left", frameon=False, fontsize=10,
                    handlelength=1.2, labelspacing=0.25, borderaxespad=0.3)
    for txt in leg.get_texts():
        txt.set_color("0.10")

    panel_label(ax, "c", fontsize=12)


def make_p4_comparison(output_dir: str | os.PathLike) -> Path:
    """Render p4 (cross-reference comparison panels).

    Left column  — panel a (sonar vs SRTM: A-V scatter + E-A) stacked above
                   panel c (vol-ratio histogram).
    Right column — panel b (GRDL comparison: A-V + D-A for each dam, 3 rows).
    """
    from matplotlib.gridspec import GridSpecFromSubplotSpec

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_png = out_dir / "p4_comparison.png"

    bathy = _load_bathy_validation_data()
    grdl = _load_grdl_comparisons()
    n_dams = len(grdl)

    with plt.rc_context({
        "font.size":       10,
        "axes.labelsize":  10,
        "axes.titlesize":  10,
        "xtick.labelsize": 10,
        "ytick.labelsize": 10,
        "legend.fontsize": 10,
    }):
        fig = plt.figure(figsize=(mm_to_in(400), mm_to_in(160)))
        gs = fig.add_gridspec(
            1, 2,
            width_ratios=[1.4, 1.5],
            wspace=0.14,
            left=0.06, right=0.985, top=0.97, bottom=0.06,
        )

        # ---- left column: panel a (same height as 1 GRDL row) + panel c ----
        gs_left = GridSpecFromSubplotSpec(
            2, 1, subplot_spec=gs[0, 0],
            height_ratios=[1.7, 1.3],
            hspace=0.30,
        )
        gs_a = GridSpecFromSubplotSpec(1, 2, subplot_spec=gs_left[0], wspace=0.25)
        _draw_bathy_va(fig.add_subplot(gs_a[0]), bathy, panel_label_char="a")
        _draw_bathy_ea(fig.add_subplot(gs_a[1]), bathy)
        _draw_panel_c(fig.add_subplot(gs_left[1]))

        # ---- right column: panel b (n_dams rows × 2 cols) ----
        gs_b = GridSpecFromSubplotSpec(
            n_dams, 2, subplot_spec=gs[0, 1],
            hspace=0.10, wspace=0.20,
        )
        for i, comp in enumerate(grdl):
            is_last = (i == n_dams - 1)
            ax_va = fig.add_subplot(gs_b[i, 0])
            ax_da = fig.add_subplot(gs_b[i, 1])
            _draw_grdl_va(ax_va, comp, show_xlabel=is_last,
                          panel_label_char="b" if i == 0 else None)
            _draw_grdl_da(ax_da, comp, show_xlabel=is_last, show_ylabel=True)
            for _ax in (ax_va, ax_da):
                _ax.text(
                    0.97, 0.04, comp["dam_name"],
                    transform=_ax.transAxes, ha="right", va="bottom",
                    fontsize=10, color="0.10",
                    bbox=dict(boxstyle="round,pad=0.3", facecolor="white",
                              edgecolor="0.7", linewidth=0.5, alpha=0.9),
                )
            if not is_last:
                ax_da.tick_params(labelbottom=False)

        # Open axes: no top/right spines anywhere in the panel set.
        for _ax in fig.axes:
            _ax.spines["top"].set_visible(False)
            _ax.spines["right"].set_visible(False)

        save_panel(fig, out_png)
    plt.close(fig)
    print(f"wrote {out_png}")
    return out_png
