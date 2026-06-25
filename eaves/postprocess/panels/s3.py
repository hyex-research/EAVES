"""Panel s3 -- supplementary: V uncertainty propagation from ``b_sigma``.

Two-panel illustration of how the population-level 1$\\sigma$ uncertainty
on $b$ propagates to a volume confidence band:

Panel a -- Baish reservoir: SRTM-derived $V(A)$ curve with the $\\pm b_\\sigma$
fan band, all curves pinned through the catalogue full-pool anchor
$(A_\\mathrm{cap}, V_\\mathrm{cap})$. Band and curve span the full SRTM
data range so the fan is visible end-to-end.

Panel b -- Two $\\sigma(\\log_{10}V)$ tiers as a function of normalized area.
The SRTM-derived tier follows the band algebra
($\\sigma_{\\log V} = b_\\sigma \\cdot |\\log_{10}(A/A_\\mathrm{cap})|$) and
vanishes at the anchor because the curve is pinned to a known
$(A_\\mathrm{cap}, V_\\mathrm{cap})$. The regionalized tier adds the
anchor-parameter uncertainty,
$\\sigma_\\mathrm{regi}(A) = \\sqrt{(b\\,\\sigma_{\\log A_\\mathrm{cap}})^2
+ (b_\\sigma\\,\\log_{10}(A/A_\\mathrm{cap}))^2 + \\sigma_{\\log V_\\mathrm{cap}}^2}$,
so it does not vanish at the anchor and instead floors near 0.79. The
regionalized constants are the ``regi_multi`` medians read from
``<CSV_DIR>/validation/v_uncertainty.csv``. The regional typical operational
fill level is overlaid so a reader can read off the V uncertainty at the
level most reservoirs actually operate at.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd

import eaves.config as _cfg

from ._shared import (
    COL_REGI,
    COL_SRTM,
    apply_style,
    mm_to_in,
    panel_label,
    save_panel,
)


_BAISH_ID = "id_120000"
_CURVE_COLOR  = "#1F77B4"   # blue (central curve)
_BAND_COLOR   = "#9ECAE1"   # light blue (uncertainty band)
_ANCHOR_COLOR = "#D62728"   # red (full-pool anchor marker)


def _load_baish() -> tuple[dict, pd.DataFrame]:
    from eaves.postprocess.uncertainty import compute_b_sigma
    params = pd.read_csv(os.path.join(_cfg.CSV_DIR, "eaves_params.csv"))
    summary = pd.read_csv(os.path.join(_cfg.CSV_DIR, "eaves_summary.csv"))
    p = params[params["dam_id"] == _BAISH_ID]
    s = summary[summary["dam_id"] == _BAISH_ID]
    if p.empty or s.empty:
        raise RuntimeError(f"Baish ({_BAISH_ID}) absent from params/summary CSVs.")
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
    eav_path = Path(_cfg.CSV_DIR) / "eav_tables" / f"{_BAISH_ID}_eav.csv"
    eav = pd.read_csv(eav_path) if eav_path.exists() else pd.DataFrame()
    return info, eav


def _typical_fill_level() -> float | None:
    p = Path(_cfg.CSV_DIR) / "validation" / "dem_vs_sat_area.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p)
    d = df["sat_over_dem"].dropna()
    return float(d.median()) if len(d) else None


def _regi_constants() -> dict:
    """Regionalized-tier sigma constants (``regi_multi`` medians).

    Read from ``<CSV_DIR>/validation/v_uncertainty.csv``. These are the
    population-level anchor-parameter uncertainties that the regionalized
    volume estimate carries on top of the SRTM geometric band:
    ``sigma_acap_term`` is the area-anchor term $b\\,\\sigma_{\\log A_\\mathrm{cap}}$,
    ``sigma_log_vcap`` is the volume-anchor term, and ``b_sigma`` is the
    exponent spread.
    """
    p = Path(_cfg.CSV_DIR) / "validation" / "v_uncertainty.csv"
    df = pd.read_csv(p)
    regi = df[df["source"] == "regi_multi"]
    if regi.empty:
        regi = df
    return {
        "sigma_acap_term": float(regi["sigma_acap_term"].median()),
        "sigma_log_vcap":  float(regi["sigma_log_vcap"].median()),
        "b_sigma":         float(regi["b_sigma"].median()),
    }


def make_s3_uncertainty(out_dir: Path) -> Path:
    apply_style()

    info, eav = _load_baish()
    typical_fill = _typical_fill_level()
    regi = _regi_constants()

    import matplotlib.pyplot as plt

    # Uniform 12 pt text across every element; panel labels overridden to 14.
    rc_override = {
        "font.size":       12,
        "axes.labelsize":  12,
        "axes.titlesize":  12,
        "xtick.labelsize": 12,
        "ytick.labelsize": 12,
        "legend.fontsize": 12,
    }
    rc_stack = plt.rc_context(rc_override)
    rc_stack.__enter__()

    fig_w = mm_to_in(265.0)
    fig_h = mm_to_in(105.0)
    fig, (ax_a, ax_b) = plt.subplots(1, 2, figsize=(fig_w, fig_h))
    fig.subplots_adjust(left=0.085, right=0.985, top=0.88, bottom=0.16,
                        wspace=0.18)

    c, b, b_sigma = info["c"], info["b"], info["b_sigma"]
    A_cap, V_cap  = info["A_cap_m2"], info["V_cap_m3"]

    # ---- panel a: Baish V(A) with +/- b_sigma band ----
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
                     s=11, color="0.35", alpha=0.55, edgecolor="none",
                     zorder=2, label="SRTM samples")
    ax_a.scatter([A_cap / 1e6], [V_cap / 1e6],
                 marker="*", s=125, facecolor=_ANCHOR_COLOR,
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

    # ---- panel b: SRTM-derived vs regionalized sigma(log10 V) vs A/A_cap ----
    sig_acap = regi["sigma_acap_term"]   # b * sigma_log_acap
    sig_vcap = regi["sigma_log_vcap"]
    regi_floor = float(np.hypot(sig_acap, sig_vcap))

    frac = np.geomspace(0.03, 1.0, 240)
    # SRTM tier: geometric b_sigma term plus the catalog-capacity floor (matches v_uncertainty).
    sigma_srtm = np.sqrt((b_sigma * np.log10(frac)) ** 2 + sig_vcap ** 2)
    sigma_regi = np.sqrt(
        sig_acap**2 + (b_sigma * np.log10(frac))**2 + sig_vcap**2
    )

    unc_srtm = 10.0 ** sigma_srtm - 1.0
    unc_regi = 10.0 ** sigma_regi - 1.0
    unc_floor = 10.0 ** regi_floor - 1.0

    ax_b.plot(frac, unc_regi,
              color=COL_REGI, linewidth=1.6, zorder=3,
              label="regionalized")
    ax_b.plot(frac, unc_srtm,
              color=COL_SRTM, linewidth=1.6, zorder=3,
              label="SRTM-derived")

    ax_b.axhline(unc_floor, color=COL_REGI, linewidth=1.7,
                 linestyle=(0, (1, 3)), dash_capstyle="round", zorder=2)
    ax_b.text(frac.min() * 1.05, unc_floor + 0.03,
              rf"regionalized floor $\approx {unc_floor:.2f}$",
              color="black", ha="left", va="bottom")

    if typical_fill is not None and 0.02 < typical_fill < 1.0:
        sig_typ = b_sigma * abs(np.log10(typical_fill))
        unc_typ = 10.0 ** sig_typ - 1.0
        ax_b.axvline(typical_fill, color="0.30", linewidth=0.8,
                     linestyle="--", zorder=4)
        ax_b.scatter([typical_fill], [unc_typ], s=42, facecolor="white",
                     edgecolor=COL_SRTM, linewidth=0.9, zorder=5)
        ax_b.annotate(
            rf"typical operational fill" "\n"
            rf"$A/A_\mathrm{{cap}}={typical_fill:.2f}$" "\n"
            rf"SRTM ${unc_typ:.2f}$",
            xy=(typical_fill, unc_typ), xytext=(-58, -12),
            textcoords="offset points", color="0.15", ha="center", va="top",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.78,
                      edgecolor="0.65", linewidth=0.5),
            arrowprops=dict(arrowstyle="-", color="0.40", lw=0.6),
        )

    ax_b.set_xscale("log")
    ax_b.set_xlabel(r"$A / A_\mathrm{cap}$  (normalized area)")
    ax_b.set_ylabel("Volume uncertainty")
    ax_b.set_xlim(frac.min(), 1.05)
    y_top = (10.0 ** max(
        b_sigma * abs(np.log10(frac.min())),
        float(sigma_regi.max()),
    ) - 1.0) * 1.05
    ax_b.set_ylim(0.0, y_top)
    ax_b.grid(True, which="both", linewidth=0.3, color="0.88")
    ax_b.set_axisbelow(True)
    ax_b.legend(loc="upper right", frameon=True, framealpha=0.95)

    panel_label(ax_a, "a", fontsize=14, y_offset_pt=8.0)
    panel_label(ax_b, "b", fontsize=14, y_offset_pt=8.0)

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_png = out_dir / "s3_uncertainty_band.png"
    # Open axes: no top/right spines.
    for _ax in fig.axes:
        _ax.spines["top"].set_visible(False)
        _ax.spines["right"].set_visible(False)

    save_panel(fig, out_png)
    plt.close(fig)
    rc_stack.__exit__(None, None, None)
    return out_png
