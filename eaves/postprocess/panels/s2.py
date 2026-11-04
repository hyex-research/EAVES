"""Panel s2 (supplementary): V uncertainty propagation from ``b_sigma``.

Two-panel illustration of how the population-level 1σ uncertainty on b
propagates to a volume confidence band:

Panel a: Baish reservoir, SRTM-derived V(A) curve with the ±b_σ fan band of
the geometric term alone, all curves pinned through the catalog full-pool
anchor (A_cap, V_cap). Band and curve span the full SRTM data range.

Panel b: Upper bound 10^σ − 1 of the two σ(log10 V) tiers as a function of
normalized area. The SRTM-derived tier combines the band term
b_σ·|log10(A/A_cap)| in quadrature with the catalog-capacity term σ_logVcap.
The regionalized tier adds the predicted-area term,
σ_regi(A) = √((b·σ_logAcap)² + (b_σ·log10(A/A_cap))² + σ_logVcap²).
The regionalized constants are the ``regi_multi`` medians read from
``<CSV_DIR>/validation/v_uncertainty.csv``. The regional typical operational
fill level is marked on the SRTM-derived curve, with the value of that curve.
"""

from __future__ import annotations

import os
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import eaves.config as _cfg

from ...utils import dams_with_fill
from ..uncertainty import compute_b_sigma
from ._example import example_dam_id
from ._shared import (
    COL_REGI,
    COL_SRTM,
    PANEL_TEXT_RC,
    apply_style,
    mm_to_in,
    panel_label,
    save_panel,
)

_CURVE_COLOR  = "#1F77B4"   # blue (central curve)
_BAND_COLOR   = "#9ECAE1"   # light blue (uncertainty band)
_ANCHOR_COLOR = "#D62728"   # red (full-pool anchor marker)


def _load_baish() -> tuple[dict, pd.DataFrame]:
    params = pd.read_csv(os.path.join(_cfg.CSV_DIR, "eaves_params.csv"))
    summary = dams_with_fill(pd.read_csv(os.path.join(_cfg.CSV_DIR, "eaves_summary.csv")))
    dam_id = example_dam_id()
    p = params[params["dam_id"] == dam_id]
    s = summary[summary["dam_id"] == dam_id]
    if p.empty or s.empty:
        raise RuntimeError(f"Example dam {dam_id!r} absent from params/summary CSVs.")
    c = float(p.iloc[0]["c"])
    b = float(p.iloc[0]["b"])
    V_cap_m3 = float(s.iloc[0]["capacity_mcm"]) * 1e6
    A_cap_m2 = float((V_cap_m3 / c) ** (1.0 / b))   # reference area A_cap defined by V_cap = c * A_cap^b
    info = {
        "c":         c,
        "b":         b,
        "b_sigma":   compute_b_sigma(summary),
        "V_cap_m3":  V_cap_m3,
        "A_cap_m2":  A_cap_m2,
        "dam_name":  str(s.iloc[0].get("dam_name", dam_id)).strip(),
    }
    eav_path = Path(_cfg.CSV_DIR) / "eav_tables" / f"{dam_id}_eav.csv"
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
    ``sigma_acap_term`` is the predicted-area term b·σ_logAcap,
    ``sigma_log_vcap`` is the catalog-capacity term, and ``b_sigma`` is the
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


def make_s2_uncertainty(out_dir: Path) -> Path:
    apply_style()

    info, eav = _load_baish()
    typical_fill = _typical_fill_level()
    regi = _regi_constants()

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_png = out_dir / "s2_uncertainty_band.png"

    with plt.rc_context(PANEL_TEXT_RC):
        fig_w = mm_to_in(187.0)
        fig_h = mm_to_in(90.0)
        fig, (ax_a, ax_b) = plt.subplots(1, 2, figsize=(fig_w, fig_h))
        fig.subplots_adjust(left=0.0960, right=0.9730, top=0.90, bottom=0.15,
                            wspace=0.24)

        c, b, b_sigma = info["c"], info["b"], info["b_sigma"]
        A_cap, V_cap  = info["A_cap_m2"], info["V_cap_m3"]

        # ---- Panel a: Baish V(A) with +/- b_sigma band ----
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
                          label=rf"$\pm b_\sigma$ band ($b_\sigma = {b_sigma:.2f}$)")
        ax_a.plot(A_grid / 1e6, V_pred / 1e6,
                  color=_CURVE_COLOR, linewidth=1.4,
                  label=rf"$V = c\,A^{{b}}$ ($b = {b:.4f}$)")
        if len(A_data) > 0:
            ax_a.scatter(A_data / 1e6, V_data / 1e6,
                         s=11, color="0.35", alpha=0.55, edgecolor="none",
                         zorder=2, label="SRTM area-volume pairs")
        ax_a.scatter([A_cap / 1e6], [V_cap / 1e6],
                     marker="*", s=125, facecolor=_ANCHOR_COLOR,
                     edgecolor="white", linewidth=0.6, zorder=5,
                     label=r"Anchor $(A_\mathrm{cap}, V_\mathrm{cap})$")

        ax_a.text(0.02, 0.97, info["dam_name"], transform=ax_a.transAxes,
                  ha="left", va="top",
                  bbox=dict(facecolor="white", alpha=0.85,
                            edgecolor="0.85", linewidth=0.5, pad=2.0))

        ax_a.set_xscale("log")
        ax_a.set_yscale("log")
        ax_a.set_xlabel(r"Area (km$^2$)")
        ax_a.set_ylabel(r"Volume (MCM)")
        ax_a.grid(True, which="both", linewidth=0.3, color="0.88")
        ax_a.set_axisbelow(True)
        ax_a.legend(loc="lower right", frameon=False,
                    handlelength=1.4, handletextpad=0.5, labelspacing=0.3,
                    borderpad=0.4, borderaxespad=0.3)

        # ---- Panel b: SRTM-derived vs regionalized sigma(log10 V) vs A/A_cap ----
        sig_acap = regi["sigma_acap_term"]   # b * sigma_log_acap
        sig_vcap = regi["sigma_log_vcap"]
        regi_floor = float(np.hypot(sig_acap, sig_vcap))

        frac = np.geomspace(0.03, 1.0, 240)
        # The SRTM tier combines the geometric b_sigma term with the catalog-capacity floor, as in v_uncertainty
        sigma_srtm = np.sqrt((b_sigma * np.log10(frac)) ** 2 + sig_vcap ** 2)
        sigma_regi = np.sqrt(
            sig_acap**2 + (b_sigma * np.log10(frac))**2 + sig_vcap**2
        )

        unc_srtm = 10.0 ** sigma_srtm - 1.0
        unc_regi = 10.0 ** sigma_regi - 1.0
        unc_floor = 10.0 ** regi_floor - 1.0

        ax_b.plot(frac, unc_regi,
                  color=COL_REGI, linewidth=1.6, zorder=3,
                  label="Regionalized")
        ax_b.plot(frac, unc_srtm,
                  color=COL_SRTM, linewidth=1.6, zorder=3,
                  label="SRTM-derived")

        ax_b.axhline(unc_floor, color=COL_REGI, linewidth=1.7,
                     linestyle=(0, (1, 3)), dash_capstyle="round", zorder=2)
        ax_b.text(frac.max(), unc_floor - 0.04,
                  "Regionalized\n" rf"floor $\approx {unc_floor:.2f}$",
                  color="black", ha="right", va="top", multialignment="right")

        if typical_fill is not None and 0.02 < typical_fill < 1.0:
            # Uses the same expression as the SRTM-derived curve
            sig_typ = float(np.hypot(b_sigma * np.log10(typical_fill), sig_vcap))
            unc_typ = 10.0 ** sig_typ - 1.0
            ax_b.axvline(typical_fill, color="0.30", linewidth=0.8,
                         linestyle="--", zorder=4)
            ax_b.scatter([typical_fill], [unc_typ], s=42, facecolor="white",
                         edgecolor=COL_SRTM, linewidth=0.9, zorder=5)
            ax_b.annotate(
                rf"Typical" "\n" rf"operational fill" "\n"
                rf"$A/A_\mathrm{{cap}}={typical_fill:.2f}$" "\n"
                rf"SRTM ${unc_typ:.2f}$",
                xy=(typical_fill, unc_typ), xytext=(-12, -16),
                textcoords="offset points", color="0.15", ha="right", va="top",
                multialignment="center",
                bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.78,
                          edgecolor="0.65", linewidth=0.5),
                arrowprops=dict(arrowstyle="-", color="0.40", lw=0.6),
            )

        ax_b.set_xscale("log")
        ax_b.set_xlabel(r"$A / A_\mathrm{cap}$ (normalized area)")
        ax_b.set_ylabel("Volume uncertainty, upper bound")
        ax_b.set_xlim(frac.min(), 1.05)
        y_top = (10.0 ** max(
            b_sigma * abs(np.log10(frac.min())),
            float(sigma_regi.max()),
        ) - 1.0) * 1.05
        ax_b.set_ylim(0.0, y_top)
        ax_b.grid(True, which="both", linewidth=0.3, color="0.88")
        ax_b.set_axisbelow(True)
        ax_b.legend(loc="upper right", frameon=False)

        panel_label(ax_a, "a", fontsize=12, y_offset_pt=8.0)
        panel_label(ax_b, "b", fontsize=12, y_offset_pt=8.0)

        # Opens the axes by hiding the top and right spines
        for _ax in fig.axes:
            _ax.spines["top"].set_visible(False)
            _ax.spines["right"].set_visible(False)

        save_panel(fig, out_png)
    plt.close(fig)
    return out_png
