"""Panel set p4: leave-one-out evaluation of the regionalization procedure.

Evaluation panel for the regionalization procedure of ``regionalization.py``.
The procedure anchors each dam without a trusted fit at the full-pool area
predicted by the multi-feature linear regression (log-space
catalog/topographic features, trained on the SRTM-derived training dams) and
back-solves the coefficient ``c = V_cap / A_cap^b``. The procedure is
evaluated by leave-one-out on the training dams. Each in turn is left out,
the full-pool area regression is refitted, the regional exponent is
recalculated as the median exponent of the remaining training dams, and the
resulting curve is compared with the SRTM-derived reference at three fill
levels, full pool (the DEM full-pool area), half pool (half of it) and tenth
pool (a tenth of it). The test therefore assesses reconstruction of the
SRTM-derived curves rather than accuracy against measured storage.

Two rows on a 187 mm canvas, 10 pt text, keys inside the panels, one color
per fill level throughout.

Panels a to c: predicted versus SRTM-derived reference volume at full, half
         and tenth pool on log axes with identical limits, with the 1:1
         line, the shaded ±factor-2 band and the dotted ±factor-3 lines.
         The inset names the level and gives the share within a factor of
         two, the median bias and the median absolute error as fractions
         of the reference volume.
Panel d: the signed error distribution (log10 V_pred / V_SRTM) at the three
         levels, the per-dam strip with the median and the P16 to P84
         interval, beside the median regionalized uncertainty band half
         width of the same level (one sigma, from the uncertainty table).
Panel e: the binned median error against catalog capacity at the three
         levels, with the number of dams in each bin.

Sources: ``<CSV_DIR>/validation/regionalization_loo.csv`` written by
``python -m eaves.postprocess.validation --settings <region>.json`` and
``<CSV_DIR>/validation/v_uncertainty.csv`` written by
``python -m eaves.postprocess.uncertainty --settings <region>.json``. The
band marks of panel d are left out when the uncertainty table is missing.
"""

from __future__ import annotations

import os
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from matplotlib.ticker import FuncFormatter, MultipleLocator

import eaves.config as _cfg

from ._shared import (
    P4_BLUE,
    PANEL_TEXT_RC,
    _style_legend,
    mm_to_in,
    panel_label,
    save_panel,
)

# Sets the column prefix of the multi-feature regression in regionalization_loo.csv
_METHOD_PREFIX = "multi"

# The three fill levels, as the percentage of the DEM full-pool area in the column names, the area fraction, the color, the marker of panel e and the name on the panels
_LEVELS = (
    dict(pct=100, frac=1.0, color=P4_BLUE, marker="o", name="Full pool",
         area="$A_\\mathrm{DEM}$", short="Full\npool"),
    dict(pct=50, frac=0.5, color="#9467BD", marker="s", name="Half pool",
         area="$0.5\\,A_\\mathrm{DEM}$", short="Half\npool"),
    dict(pct=10, frac=0.1, color="#D62728", marker="^", name="Tenth pool",
         area="$0.1\\,A_\\mathrm{DEM}$", short="Tenth\npool"),
)

# Error axis of panel e and the tick format of the error axes, in log10 units of the volume ratio
_ERR_LIM_E = 0.6
_ERR_TICKS_E = [-0.5, 0.0, 0.5]
_ERR_FMT = FuncFormatter(lambda v, _: f"{v:g}".replace("-", "−"))

# ---- Geometry ----

# Canvas and margins in mm
_FIG_W_MM = 187.0
_FIG_H_MM = 143.0
_LEFT_MM = 20.0
_RIGHT_MM = 3.0
_TOP_MM = 7.5
_BOTTOM_MM = 16.0
# Top row, three squares separated by a gap that holds only the ticks of the shared y axis
_GAP_TOP_MM = 5.0
# Bottom row, the height of its panels and the gap holding the y label of panel e
_ROW2_H_MM = 48.0
_GAP_DE_MM = 23.0
# Share of the bottom row width that goes to panel d
_D_SHARE = 0.40

_BOX_STYLE = dict(boxstyle="round,pad=0.3", facecolor="white",
                  edgecolor="0.7", linewidth=0.5)

# Panel d, the offsets of the per-dam strip and of the band bar from the level position, and the bar width
_D_STRIP_DX = -0.17
_D_BAND_DX = 0.22
_D_BAND_W = 0.16


def _loo_csv() -> Path:
    return Path(_cfg.CSV_DIR) / "validation" / "regionalization_loo.csv"


def _uncertainty_csv() -> Path:
    return Path(_cfg.CSV_DIR) / "validation" / "v_uncertainty.csv"


def _load_loo() -> pd.DataFrame:
    p = _loo_csv()
    if not p.exists():
        raise RuntimeError(
            f"Missing {p}. Run: python -m eaves.postprocess.validation "
            f"--settings <settings>.json"
        )
    return pd.read_csv(p)


def _level_stats(df: pd.DataFrame, level: dict) -> dict:
    """Reference and predicted volumes in MCM and the signed log10 error at one level."""
    v_true = (df[f"V_srtm_at_{level['pct']:03d}pct_m3"] / 1e6).values
    v_pred = (df[f"{_METHOD_PREFIX}_V_at_{level['pct']:03d}pct_m3"] / 1e6).values
    m = (v_true > 0) & (v_pred > 0) & np.isfinite(v_true) & np.isfinite(v_pred)
    r = np.log10(v_pred[m]) - np.log10(v_true[m])
    return {
        "n": int(len(r)),
        "median": float(np.median(r)),
        "p16": float(np.quantile(r, 0.16)),
        "p84": float(np.quantile(r, 0.84)),
        "within2": float(np.mean(np.abs(r) < np.log10(2.0))),
        "v_true": v_true[m],
        "v_pred": v_pred[m],
        "residuals_log10": r,
        "capacity_mcm": df["capacity_mcm"].values[m],
    }


def _band_half_widths() -> list[float | None]:
    """The median one-sigma band half width of the regionalized dams at each level, in log10 units.

    Read from the uncertainty table, the half- and tenth-pool columns as
    written and the full-pool value from the area and capacity terms, which
    are the only ones left at the anchor. None at every level when the table
    is missing.
    """
    p = _uncertainty_csv()
    if not p.exists():
        return [None for _ in _LEVELS]
    u = pd.read_csv(p)
    if "source" in u.columns:
        u = u[u["source"] == "regi_multi"]
    if not len(u):
        return [None for _ in _LEVELS]
    out = []
    for level in _LEVELS:
        if level["pct"] == 100:
            s = np.sqrt((u["b"] * u["sigma_log_acap"]) ** 2 + u["sigma_log_vcap"] ** 2)
        elif level["pct"] == 50:
            s = u["V_sigma_log10_half_pool"]
        else:
            s = u["V_sigma_log10_tenth_pool"]
        s = s.dropna()
        out.append(float(np.median(s)) if len(s) else None)
    return out


# ---- Drawing ----

def _signed(x: float) -> str:
    """Formats a signed value to two decimals with a unicode minus."""
    return f"{x:+.2f}".replace("-", "−")


def _panel_axes(fig) -> tuple:
    """Adds the five axes, three squares in the top row and two panels in the bottom row."""
    side = (_FIG_W_MM - _LEFT_MM - _RIGHT_MM - 2.0 * _GAP_TOP_MM) / 3.0
    y_top = (_FIG_H_MM - _TOP_MM - side) / _FIG_H_MM
    top = tuple(
        fig.add_axes([(_LEFT_MM + i * (side + _GAP_TOP_MM)) / _FIG_W_MM, y_top,
                      side / _FIG_W_MM, side / _FIG_H_MM])
        for i in range(3)
    )
    rest = _FIG_W_MM - _LEFT_MM - _RIGHT_MM - _GAP_DE_MM
    w_d = rest * _D_SHARE
    w_e = rest - w_d
    y_bot = _BOTTOM_MM / _FIG_H_MM
    h = _ROW2_H_MM / _FIG_H_MM
    ax_d = fig.add_axes([_LEFT_MM / _FIG_W_MM, y_bot, w_d / _FIG_W_MM, h])
    ax_e = fig.add_axes([(_LEFT_MM + w_d + _GAP_DE_MM) / _FIG_W_MM, y_bot, w_e / _FIG_W_MM, h])
    return top + (ax_d, ax_e)


def _draw_scatter(ax, stats: dict, level: dict, letter: str, lo: float, hi: float,
                  *, first: bool) -> None:
    """One top-row panel, regionalized versus reference volume at the level on log axes."""
    grid = np.geomspace(lo, hi, 200)

    ax.fill_between(grid, grid / 2.0, grid * 2.0,
                    color="0.78", alpha=0.55, zorder=0, label="±factor 2")
    ax.plot(grid, grid * 2.0, color="0.40", lw=0.7, zorder=2)
    ax.plot(grid, grid / 2.0, color="0.40", lw=0.7, zorder=2)
    ax.plot(grid, grid * 3.0, color="0.55", lw=0.6, ls=":", zorder=2)
    ax.plot(grid, grid / 3.0, color="0.55", lw=0.6, ls=":", zorder=2,
            label="±factor 3")
    ax.plot(grid, grid, color="black", lw=1.3, zorder=4, label="1:1")

    ax.scatter(
        stats["v_true"], stats["v_pred"],
        s=16, color=level["color"], alpha=0.65, edgecolor="white", linewidth=0.3,
        zorder=3,
    )

    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlim(lo, hi)
    ax.set_ylim(lo, hi)
    ax.tick_params(labelsize=10, length=2.5)
    ax.grid(True, which="both", ls=":", lw=0.4, alpha=0.5)
    if first:
        ax.set_ylabel("Predicted volume (MCM)", fontsize=10)
        # The key of the row sits in the first panel
        _style_legend(ax.legend(loc="lower right", frameon=False, fontsize=10,
                                handlelength=1.2, handletextpad=0.4, labelspacing=0.25,
                                borderaxespad=0.2))
    else:
        ax.tick_params(axis="y", labelleft=False)

    # The inset names the level and gives the share within a factor of two, the median bias and the median absolute error as fractions of the reference volume, the count being the same at every level
    r = stats["residuals_log10"]
    bias_frac = 10 ** stats["median"] - 1.0
    medape = float(np.median(np.abs(10 ** r - 1.0)))
    txt = (
        f"{level['name']} ({level['area']})\n"
        f"{100 * stats['within2']:.0f}% within ×2\n"
        f"Bias = {_signed(bias_frac)}\n"
        f"Abs. error = {medape:.2f}"
    )
    ax.text(
        0.03, 0.97, txt,
        transform=ax.transAxes, ha="left", va="top",
        fontsize=10, color="0.10",
        bbox=dict(alpha=0.55, **_BOX_STYLE),
    )

    panel_label(ax, letter, fontsize=12)


def _draw_panel_d(ax, stats_by_level: list[dict], bands: list[float | None]) -> None:
    """Panel d, the error distribution at the three levels beside the band half width of each."""
    xs = np.arange(len(_LEVELS))
    y_min, y_max = 0.0, 0.0
    for i, (level, stats) in enumerate(zip(_LEVELS, stats_by_level)):
        r = stats["residuals_log10"]
        y_min = min(y_min, float(r.min()))
        y_max = max(y_max, float(r.max()))
        x0 = xs[i] + _D_STRIP_DX
        jitter = (np.random.default_rng(i).random(len(r)) - 0.5) * 0.16
        ax.scatter(x0 + jitter, r, s=9, color=level["color"], alpha=0.35,
                   edgecolor="none", zorder=2)
        ax.errorbar(
            x0, stats["median"],
            yerr=[[stats["median"] - stats["p16"]], [stats["p84"] - stats["median"]]],
            fmt="o", markersize=6, color="black", mfc=level["color"], mec="black", mew=0.8,
            ecolor="black", elinewidth=1.4, capsize=4, capthick=1.4, zorder=5,
        )
        band = bands[i]
        if band is not None:
            y_max = max(y_max, band)
            x1 = xs[i] + _D_BAND_DX
            ax.fill_between([x1 - _D_BAND_W / 2.0, x1 + _D_BAND_W / 2.0], -band, band,
                            color="0.72", alpha=0.75, linewidth=0, zorder=1)
            ax.annotate(
                f"±{band:.2f}",
                xy=(x1, band), xytext=(0, 3), textcoords="offset points",
                color="0.10", fontsize=10, ha="center", va="bottom",
            )

    # The upper limit leaves the key above the marks
    ax.set_ylim(y_min - 0.1, y_max + 0.75)
    ax.axhline(0.0, color="black", lw=1.2, zorder=3)
    ax.axhline(np.log10(2.0), color="0.30", lw=0.9, ls="--", zorder=3)
    ax.axhline(-np.log10(2.0), color="0.30", lw=0.9, ls="--", zorder=3)

    ax.set_xticks(xs)
    ax.set_xticklabels([level["short"] for level in _LEVELS])
    ax.set_xlim(-0.55, len(xs) - 0.45)
    ax.yaxis.set_major_locator(MultipleLocator(0.5))
    ax.yaxis.set_major_formatter(_ERR_FMT)
    ax.set_ylabel(r"$\log_{10}(V_\mathrm{pred}\,/\,V_\mathrm{SRTM})$", fontsize=10)
    ax.tick_params(labelsize=10, length=2.5)
    ax.grid(True, axis="y", ls=":", lw=0.4, alpha=0.5)
    ax.set_axisbelow(True)

    handles = [
        Line2D([], [], color="black", marker="o", mfc="white", mec="black", mew=0.8,
               markersize=6, lw=1.4, label="Median, P16 to P84"),
        Line2D([], [], color="0.30", lw=0.9, ls="--", label="±factor 2"),
        Patch(facecolor="0.72", alpha=0.75, label="Uncertainty band, ±1σ"),
    ]
    _style_legend(ax.legend(handles=handles, loc="upper left", frameon=False, fontsize=10,
                            handlelength=1.2, handletextpad=0.4, labelspacing=0.25,
                            borderaxespad=0.2))

    panel_label(ax, "d", fontsize=12)


def _draw_panel_e(ax, stats_by_level: list[dict]) -> None:
    """Panel e, the binned median error against catalog capacity at the three levels."""
    cap_all = np.concatenate([s["capacity_mcm"] for s in stats_by_level])
    cap_all = cap_all[np.isfinite(cap_all) & (cap_all > 0)]
    edges = np.geomspace(max(cap_all.min(), 1e-3), cap_all.max(), 11)
    centers = np.sqrt(edges[:-1] * edges[1:])

    ax.axhline(0.0, color="black", lw=1.2, zorder=3)
    ax.axhline(np.log10(2.0), color="0.30", lw=0.9, ls="--", zorder=3)
    ax.axhline(-np.log10(2.0), color="0.30", lw=0.9, ls="--", zorder=3)
    ax.axhline(np.log10(3.0), color="0.55", lw=0.6, ls=":", zorder=3)
    ax.axhline(-np.log10(3.0), color="0.55", lw=0.6, ls=":", zorder=3)

    counts = None
    for level, stats in zip(_LEVELS, stats_by_level):
        cap = stats["capacity_mcm"]
        err = stats["residuals_log10"]
        ok = np.isfinite(cap) & (cap > 0)
        cap, err = cap[ok], err[ok]
        med, ns = [], []
        # The last bin closes at and includes the largest capacity
        for k, (a, b) in enumerate(zip(edges[:-1], edges[1:])):
            inside = (cap >= a) & ((cap <= b) if k == len(edges) - 2 else (cap < b))
            sub = err[inside]
            med.append(float(np.median(sub)) if len(sub) >= 3 else np.nan)
            ns.append(len(sub))
        med = np.asarray(med)
        valid = np.isfinite(med)
        ax.plot(centers[valid], med[valid], color=level["color"], lw=1.6,
                marker=level["marker"], ms=5, mfc="white", mec=level["color"], mew=1.2,
                zorder=5, label=level["name"])
        if counts is None:
            counts = ns

    # The number of dams in each bin runs along the bottom edge, the same at every level
    y_n = -_ERR_LIM_E + 0.03
    ax.text(centers[0] / 1.35, y_n, "n =", ha="right", va="bottom", fontsize=10,
            color="0.35", zorder=4)
    for x, n in zip(centers, counts):
        if n >= 3:
            ax.text(x, y_n, f"{n}", ha="center", va="bottom", fontsize=10,
                    color="0.35", zorder=4)

    ax.set_xscale("log")
    # The left margin holds the prefix of the first count
    ax.set_xlim(edges[0] / 2.2, edges[-1] * 1.5)
    ax.set_ylim(-_ERR_LIM_E, _ERR_LIM_E)
    ax.set_yticks(_ERR_TICKS_E)
    ax.yaxis.set_major_formatter(_ERR_FMT)
    ax.set_xlabel("Catalog capacity (MCM)", fontsize=10)
    ax.set_ylabel("Binned median\n$\\log_{10}(V_\\mathrm{pred}\\,/\\,V_\\mathrm{SRTM})$",
                  fontsize=10)
    ax.tick_params(labelsize=10, length=2.5)
    ax.grid(True, which="both", ls=":", lw=0.4, alpha=0.5)
    ax.set_axisbelow(True)

    _style_legend(ax.legend(loc="upper right", frameon=False, fontsize=10, ncol=3,
                            handlelength=1.6, handletextpad=0.4, columnspacing=1.0,
                            borderaxespad=0.2))

    panel_label(ax, "e", fontsize=12)


def make_p4_validation(output_dir: str | os.PathLike) -> Path:
    """Renders p4, the leave-one-out evaluation of the regionalization procedure at three fill levels.

    Panels a to c: predicted versus reference volume at full, half and tenth pool.
    Panel d: the error distribution at the three levels beside the band half width of each.
    Panel e: the binned median error against catalog capacity at the three levels.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_png = out_dir / "p4_regionalization_validation.png"

    df = _load_loo()
    stats_by_level = [_level_stats(df, level) for level in _LEVELS]
    bands = _band_half_widths()

    # Identical limits across the top row, from the smallest to the largest volume at any level
    lo = max(1e-4, min(min(s["v_true"].min(), s["v_pred"].min()) for s in stats_by_level) * 0.5)
    hi = max(max(s["v_true"].max(), s["v_pred"].max()) for s in stats_by_level) * 2.0

    with plt.rc_context(PANEL_TEXT_RC):
        fig = plt.figure(figsize=(mm_to_in(_FIG_W_MM), mm_to_in(_FIG_H_MM)))
        ax_a, ax_b, ax_c, ax_d, ax_e = _panel_axes(fig)
        for ax, stats, level, letter in zip((ax_a, ax_b, ax_c), stats_by_level, _LEVELS, "abc"):
            _draw_scatter(ax, stats, level, letter, lo, hi, first=(letter == "a"))
        # One x label for the top row, centered under the middle panel
        ax_b.set_xlabel("SRTM-derived reference volume (MCM)", fontsize=10)
        _draw_panel_d(ax_d, stats_by_level, bands)
        _draw_panel_e(ax_e, stats_by_level)

        # Opens the axes by hiding the top and right spines across the panel set
        for _ax in fig.axes:
            _ax.spines["top"].set_visible(False)
            _ax.spines["right"].set_visible(False)

        save_panel(fig, out_png)
    plt.close(fig)
    print(f"wrote {out_png}")
    return out_png
