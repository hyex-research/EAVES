"""QC plotting helpers — styled for the Scientific Data submission.

Panel labels use bold lowercase letters (a, b, c, ...).
Font sizes: 5-7 pt (Nature max 7 pt), Arial / Helvetica.
Figure widths: 89 mm / 3.5 in (single column), 183 mm / 7.2 in (double column).
Colourblind-safe palette throughout; viridis as default sequential cmap.
Flood QC maps stay at 100 DPI (not for publication).
"""

from __future__ import annotations

import os

import numpy as np
import matplotlib as mpl
import matplotlib.pyplot as plt

import eaves.config as _cfg


# --- Flood map (QC only, 100 DPI, not publication) ---

_QC_RC = {
    "font.size": 12,
    "axes.titlesize": 12,
    "axes.labelsize": 11,
    "xtick.labelsize": 10,
    "ytick.labelsize": 10,
    "legend.fontsize": 10,
    "axes.linewidth": 1.0,
}


def save_flood_map(result, flood_dir, dam_id=None, dam_name=None):
    file_label = dam_id if dam_id else result.get("dam_id", "unknown")
    dem = result["dem_utm"]
    fp = result["footprint"]
    dam_r, dam_c = result["dam_rc"]

    with mpl.rc_context(_QC_RC):
        fig, ax = plt.subplots(figsize=(10, 8), tight_layout=True)

        masked_dem = np.where(np.isnan(dem), np.nan, dem)
        im = ax.imshow(masked_dem, cmap="cubehelix", interpolation="nearest")
        cbar = plt.colorbar(im, ax=ax, shrink=0.8, pad=0.02)
        cbar.set_label("Elevation (m)")

        flood_overlay = np.ma.masked_where(~fp, np.ones_like(dem))
        ax.imshow(flood_overlay, cmap="Blues", alpha=0.8, interpolation="nearest")

        ax.plot(dam_c, dam_r, "v", color="red", markersize=10, markeredgecolor="k",
                markeredgewidth=0.8, zorder=10)

        wall_vec = result.get("wall_vec")
        eff_length_m = result.get("eff_length_m")
        pixel_size = result.get("pixel_size")
        if wall_vec is not None and eff_length_m and pixel_size:
            half_len_px = (float(eff_length_m) / float(pixel_size)) / 2.0
            wr, wc = wall_vec
            r1 = dam_r - wr * half_len_px
            c1 = dam_c - wc * half_len_px
            r2 = dam_r + wr * half_len_px
            c2 = dam_c + wc * half_len_px
            ax.plot([c1, c2], [r1, r2], color="darkorange", lw=2.2, alpha=0.95,
                    solid_capstyle="round", zorder=9)

        river = result.get("flood_river_overlay")
        if river is not None:
            lc, lr = river["line_cc"], river["line_rr"]
            if lc.size >= 2:
                ax.plot(
                    lc, lr, color="cyan", lw=2.2, alpha=0.92, zorder=6,
                    solid_capstyle="round",
                )
            if river["arrow_cc"].size > 0:
                ax.quiver(
                    river["arrow_cc"],
                    river["arrow_rr"],
                    river["arrow_uc"],
                    river["arrow_vr"],
                    angles="xy",
                    scale_units="xy",
                    scale=1.0,
                    color="gold",
                    width=0.0045,
                    zorder=7,
                    headwidth=4.5,
                    headlength=5.0,
                    linewidth=0.4,
                    edgecolor="darkgoldenrod",
                )

        cap_tag = " [capped]" if result["capped"] else ""
        id_label = file_label
        if dam_name:
            id_label = f"{file_label}, {dam_name}"
        year = result.get("construction_year")
        year_tag = f"year={int(year)}" if year is not None and np.isfinite(year) else ""
        ax.set_title(f"{id_label}{cap_tag}\n"
                     f"{year_tag}\n"
                     f"A={result['footprint_area_km2']:.2f} km\u00b2, "
                     f"V={result['vol_m3'][-1]/1e6:.1f} MCM, "
                     f"Cap={result['capacity_mcm']:.1f} MCM")
        ax.set_xlabel("Column (px)")
        ax.set_ylabel("Row (px)")

        plt.savefig(os.path.join(flood_dir, f"{file_label}_flood.png"),
                    dpi=100, bbox_inches="tight")
        plt.close(fig)


