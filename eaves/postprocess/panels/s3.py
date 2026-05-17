"""Panel s3 -- supplementary: V uncertainty propagation from ``b_sigma``.

Two-panel illustration of how the population-level 1$\\sigma$ uncertainty
on $b$ propagates to a volume confidence band:

Panel a -- Baysh reservoir: SRTM-derived $V(A)$ curve with the $\\pm b_\\sigma$
fan band, all curves pinned through the catalogue full-pool anchor
$(A_\\mathrm{cap}, V_\\mathrm{cap})$. Band and curve span the full SRTM
data range so the fan is visible end-to-end.

Panel b -- The universal $\\sigma(\\log_{10}V)$ curve derived from the band
algebra ($\\sigma_{\\log V} = b_\\sigma \\cdot |\\log_{10}(A/A_\\mathrm{cap})|$),
with the regional typical operational fill level overlaid so a reader can
read off the V uncertainty at the level most reservoirs actually operate at.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd

import eaves.config as _cfg

from ._shared import apply_style, mm_to_in, panel_label, save_panel


_BAYSH_ID = "id_120000"
_CURVE_COLOR  = "#1F77B4"   # blue (central curve)
_BAND_COLOR   = "#9ECAE1"   # light blue (uncertainty band)
_ANCHOR_COLOR = "#D62728"   # red (full-pool anchor marker)


def _load_baysh() -> tuple[dict, pd.DataFrame]:
    from eaves.postprocess.uncertainty import compute_b_sigma
    params = pd.read_csv(os.path.join(_cfg.CSV_DIR, "eaves_params.csv"))
    summary = pd.read_csv(os.path.join(_cfg.CSV_DIR, "eaves_summary.csv"))
    p = params[params["dam_id"] == _BAYSH_ID]
    s = summary[summary["dam_id"] == _BAYSH_ID]
    if p.empty or s.empty:
        raise RuntimeError(f"Baysh ({_BAYSH_ID}) absent from params/summary CSVs.")
    c = float(p.iloc[0]["c"])
    b = float(p.iloc[0]["b"])
    V_cap_m3 = float(s.iloc[0]["capacity_mcm"]) * 1e6
    A_cap_m2 = float((V_cap_m3 / c) ** (1.0 / b))   # implicit anchor used by the recipe
    info = {
        "c":         c,
        "b":         b,
        "b_sigma":   compute_b_sigma(summary),
        "V_cap_m3":  V_cap_m3,
        "A_cap_m2":  A_cap_m2,
        "dam_name":  str(s.iloc[0].get("dam_name", "Baish")).strip(),
    }
    eav_path = Path(_cfg.CSV_DIR) / "eav_tables" / f"{_BAYSH_ID}_eav.csv"
    eav = pd.read_csv(eav_path) if eav_path.exists() else pd.DataFrame()
    return info, eav


def _typical_fill_level() -> float | None:
    p = Path(_cfg.CSV_DIR) / "validation" / "dem_vs_sat_area.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p)
    d = df["sat_over_dem"].dropna()
    return float(d.median()) if len(d) else None


def make_s3_uncertainty(out_dir: Path) -> Path:
    apply_style()

    info, eav = _load_baysh()
    typical_fill = _typical_fill_level()

    import matplotlib.pyplot as plt

    # Uniform 10 pt text across every element; panel labels overridden to 12.
    rc_override = {
        "font.size":       10,
        "axes.labelsize":  10,
        "axes.titlesize":  10,
        "xtick.labelsize": 10,
        "ytick.labelsize": 10,
        "legend.fontsize": 10,
    }
    rc_stack = plt.rc_context(rc_override)
    rc_stack.__enter__()

    fig_w = mm_to_in(230.0)
    fig_h = mm_to_in(105.0)
    fig, (ax_a, ax_b) = plt.subplots(1, 2, figsize=(fig_w, fig_h))
    fig.subplots_adjust(left=0.085, right=0.985, top=0.88, bottom=0.16,
                        wspace=0.32)

    c, b, b_sigma = info["c"], info["b"], info["b_sigma"]
    A_cap, V_cap  = info["A_cap_m2"], info["V_cap_m3"]

    # ---- panel a: Baysh V(A) with +/- b_sigma band ----
    if not eav.empty:
        m = (eav["area_m2"] > 0) & (eav["volume_m3"] > 0)
        A_data = eav.loc[m, "area_m2"].values
        V_data = eav.loc[m, "volume_m3"].values
        A_min = float(A_data.min())
    else:
        A_data, V_data = np.empty(0), np.empty(0)
        A_min = 0.03 * A_cap

    A_grid = np.geomspace(A_min, A_cap, 240)
    V_pred = c * A_grid**b
    V_lo   = V_cap * (A_grid / A_cap)**(b + b_sigma)
    V_hi   = V_cap * (A_grid / A_cap)**(b - b_sigma)

    ax_a.fill_between(A_grid / 1e6, V_lo / 1e6, V_hi / 1e6,
                      color=_BAND_COLOR, alpha=0.55,
                      label=rf"$\pm b_\sigma$ band  ($b_\sigma = {b_sigma:.2f}$)")
    ax_a.plot(A_grid / 1e6, V_pred / 1e6,
              color=_CURVE_COLOR, linewidth=1.4,
              label=rf"$V = c\,A^{{b}}$  ($b = {b:.2f}$)")
    if len(A_data) > 0:
        ax_a.scatter(A_data / 1e6, V_data / 1e6,
                     s=7, color="0.35", alpha=0.55, edgecolor="none",
                     zorder=2, label="SRTM samples")
    ax_a.scatter([A_cap / 1e6], [V_cap / 1e6],
                 marker="*", s=95, facecolor=_ANCHOR_COLOR,
                 edgecolor="white", linewidth=0.6, zorder=5,
                 label=r"anchor $(A_\mathrm{cap}, V_\mathrm{cap})$")

    ax_a.text(0.02, 0.97, info["dam_name"], transform=ax_a.transAxes,
              ha="left", va="top",
              bbox=dict(facecolor="white", alpha=0.85,
                        edgecolor="0.85", linewidth=0.5, pad=2.0))

    ax_a.set_xscale("log")
    ax_a.set_yscale("log")
    ax_a.set_xlabel(r"Area  (km$^2$)")
    ax_a.set_ylabel(r"Volume  (MCM)")
    ax_a.grid(True, which="both", linewidth=0.3, color="0.88")
    ax_a.set_axisbelow(True)
    ax_a.legend(loc="lower right", frameon=True, framealpha=0.95)

    # ---- panel b: universal sigma(log10 V) vs A/A_cap ----
    frac = np.geomspace(0.03, 1.0, 240)
    sigma_log = b_sigma * np.abs(np.log10(frac))

    ax_b.fill_between(frac, 0.0, sigma_log,
                      color=_BAND_COLOR, alpha=0.50,
                      label=rf"$\sigma_{{\log V}} = b_\sigma \cdot |\log_{{10}}(A/A_\mathrm{{cap}})|$")
    ax_b.plot(frac, sigma_log,
              color=_CURVE_COLOR, linewidth=1.4)

    if typical_fill is not None and 0.02 < typical_fill < 1.0:
        sig_typ = b_sigma * abs(np.log10(typical_fill))
        pct_up = (10**sig_typ - 1.0) * 100.0
        ax_b.axvline(typical_fill, color="0.30", linewidth=0.8,
                     linestyle="--", zorder=4)
        ax_b.scatter([typical_fill], [sig_typ], s=42, facecolor="white",
                     edgecolor="0.20", linewidth=0.9, zorder=5)
        ax_b.annotate(
            rf"typical operational fill" "\n"
            rf"$A/A_\mathrm{{cap}}={typical_fill:.2f}$" "\n"
            rf"$\sigma = {sig_typ:.2f}$ dex  ($+{pct_up:.0f}\%$)",
            xy=(typical_fill, sig_typ), xytext=(10, -6),
            textcoords="offset points", color="0.15",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="white",
                      edgecolor="0.65", linewidth=0.5),
            arrowprops=dict(arrowstyle="-", color="0.40", lw=0.6),
        )

    ax_b.set_xscale("log")
    ax_b.set_xlabel(r"$A / A_\mathrm{cap}$  (normalised area)")
    ax_b.set_ylabel(r"$\sigma(\log_{10} V)$  (dex)")
    ax_b.set_xlim(frac.min(), 1.05)
    ax_b.set_ylim(0.0, b_sigma * abs(np.log10(frac.min())) * 1.08)
    ax_b.grid(True, which="both", linewidth=0.3, color="0.88")
    ax_b.set_axisbelow(True)
    ax_b.legend(loc="upper right", frameon=True, framealpha=0.95)

    panel_label(ax_a, "a", fontsize=12, y_offset_pt=8.0)
    panel_label(ax_b, "b", fontsize=12, y_offset_pt=8.0)

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_png = out_dir / "s3_uncertainty_band.png"
    save_panel(fig, out_png)
    plt.close(fig)
    rc_stack.__exit__(None, None, None)
    return out_png
