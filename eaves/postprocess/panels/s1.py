"""Panel s1 -- supplementary: K-means clustering of trusted SRTM dams.

Two questions the paper needs to defend:

1.  Do the trusted dams partition into morphological clusters in
    log-transformed feature space? Quantified by the mean silhouette
    coefficient across ``k = 2 .. 12``.
2.  Even if they did, would a per-cluster median ``b`` reduce out-of-sample
    error? Quantified by leave-one-out ``sigma(delta_b)`` against the
    global-median baseline.

Writes:

- ``<CSV_DIR>/validation/b_clustering_diagnostic.csv``  diagnostic data.
- ``<PLOT_DIR>/s1_b_clustering_silhouette.png``         two-panel figure.

The CSV write happens here (rather than in :mod:`eaves.postprocess.validation`)
because the diagnostic is panel-local: nothing downstream consumes it.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd

import eaves.config as _cfg

from ._shared import apply_style, mm_to_in, panel_label, save_panel


# ---------------------------------------------------------------------------
# Feature set + k range
# ---------------------------------------------------------------------------
_FEATURES: list[str] = [
    "valley_ratio", "channel_slope", "mean_catchment_slope",
    "dam_height_m", "spillway_height_m", "dam_length_m",
]
_K_RANGE = list(range(2, 13))
_CURVE_COLOR = "#D62728"   # red


# ---------------------------------------------------------------------------
# Pre-processing
# ---------------------------------------------------------------------------
def _trusted(df: pd.DataFrame) -> pd.DataFrame:
    m = (df["quality"].isin(["A", "B"])
         & (df["r_squared"] >= 0.98)
         & df["vol_ratio"].between(0.3, 5.0)
         & (df["n_pixels"] >= 50)
         & df["b"].notna())
    return df[m].copy().reset_index(drop=True)


def _design_matrix(df: pd.DataFrame, feats: list[str]) -> np.ndarray:
    X = np.log(np.clip(df[feats].values.astype(float), 1e-9, None))
    mu, sd = X.mean(axis=0), X.std(axis=0)
    sd[sd == 0] = 1.0
    return (X - mu) / sd


# ---------------------------------------------------------------------------
# Silhouette + LOO sigma(delta_b)
# ---------------------------------------------------------------------------
def _silhouette_curve(X: np.ndarray, ks: list[int], seed: int = 42) -> list[float]:
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score
    return [
        float(silhouette_score(
            X, KMeans(n_clusters=k, n_init=10, random_state=seed).fit(X).labels_
        ))
        for k in ks
    ]


def _loo_cluster_sigma(T: pd.DataFrame, feats: list[str], k: int,
                       seed: int = 42, n_init: int = 3) -> float:
    """Mean LOO sigma(delta_b) for per-cluster-median prediction at the given k.

    Uses ``n_init=3`` (rather than the silhouette curve's 10) because each
    LOO fold runs an independent KMeans on ~n-1 points; ``n_init=3`` keeps
    the cumulative cost tractable (~3,500 fits for n=322) and the resulting
    ``sigma`` is stable to <0.005 dex against ``n_init=10``.
    """
    from sklearn.cluster import KMeans
    from sklearn.model_selection import LeaveOneOut

    X = _design_matrix(T, feats)
    b = T["b"].values
    preds = np.zeros(len(T))
    for tr, te in LeaveOneOut().split(X):
        km = KMeans(n_clusters=k, n_init=n_init, random_state=seed).fit(X[tr])
        cid = km.predict(X[te])[0]
        cl = b[tr][km.labels_ == cid]
        preds[te] = float(np.median(cl)) if len(cl) else float(np.median(b[tr]))
    delta = preds - b
    return float((np.quantile(delta, 0.84) - np.quantile(delta, 0.16)) / 2.0)


def _baseline_sigma(T: pd.DataFrame) -> float:
    """LOO sigma(delta_b) for the global-median predictor (no clustering)."""
    b = T["b"].values
    preds = np.array([np.median(np.delete(b, i)) for i in range(len(b))])
    d = preds - b
    return float((np.quantile(d, 0.84) - np.quantile(d, 0.16)) / 2.0)


def _compute(summary_csv: str, out_csv_dir: str) -> pd.DataFrame:
    """Compute the diagnostic and persist to ``b_clustering_diagnostic.csv``."""
    T = _trusted(pd.read_csv(summary_csv))
    if len(T) < 10:
        raise RuntimeError(
            f"trusted SRTM set too small (n={len(T)}); the silhouette "
            "diagnostic needs ~50+ dams to be meaningful"
        )
    base = _baseline_sigma(T)
    X = _design_matrix(T, _FEATURES)
    sil = _silhouette_curve(X, _K_RANGE)
    rows = []
    for k, s in zip(_K_RANGE, sil):
        sigma = _loo_cluster_sigma(T, _FEATURES, k)
        rows.append({
            "feature_set":           "raw morphometry",
            "k":                     k,
            "silhouette":            s,
            "loo_sigma_delta_b":     sigma,
            "loo_sigma_baseline":    base,
            "loo_relative_gain_pct": 100.0 * (base - sigma) / base,
            "n_trusted":             int(len(T)),
        })
    df = pd.DataFrame(rows)
    os.makedirs(out_csv_dir, exist_ok=True)
    out = os.path.join(out_csv_dir, "b_clustering_diagnostic.csv")
    df.to_csv(out, index=False)
    return df


# ---------------------------------------------------------------------------
# Figure
# ---------------------------------------------------------------------------
def make_s1_clustering(out_dir: Path) -> Path:
    """Compute the b-clustering diagnostic and render the supplementary figure.

    The CSV write target is fixed at ``<CSV_DIR>/validation/`` rather than
    ``out_dir`` because the CSV is referenced by the report under the
    validation/ namespace; ``out_dir`` controls only the PNG destination.
    The diagnostic is *always recomputed* on each invocation -- caching it
    would silently keep stale residuals around after a pipeline rerun.
    """
    apply_style()

    summary_csv = os.path.join(_cfg.CSV_DIR, "eaves_summary.csv")
    validation_dir = os.path.join(_cfg.CSV_DIR, "validation")
    df = _compute(summary_csv, validation_dir)

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

    fig_w = mm_to_in(220.0)
    fig_h = mm_to_in(95.0)
    fig, (ax_a, ax_b) = plt.subplots(1, 2, figsize=(fig_w, fig_h))
    fig.subplots_adjust(left=0.07, right=0.985, top=0.90, bottom=0.13,
                        wspace=0.28)

    sub = df.sort_values("k")

    # ---- panel a: silhouette vs k ----
    ax_a.plot(sub["k"], sub["silhouette"],
              color=_CURVE_COLOR, marker="o", linewidth=1.2, markersize=4.0,
              label="raw morphometry")
    ax_a.axhline(0.50, color="0.45", linewidth=0.7, linestyle="--")
    ax_a.text(12.05, 0.505, "reasonable structure (0.50)",
              color="0.40", va="bottom", ha="right")
    ax_a.axhline(0.25, color="0.65", linewidth=0.7, linestyle=":")
    ax_a.text(12.05, 0.255, "weak structure (0.25)",
              color="0.55", va="bottom", ha="right")

    ax_a.set_xlabel(r"Number of clusters $k$")
    ax_a.set_ylabel("Mean silhouette coefficient")
    ax_a.set_xticks(_K_RANGE)
    ax_a.set_xlim(1.7, 12.3)
    ax_a.set_ylim(0.05, 0.75)
    ax_a.grid(True, linewidth=0.3, color="0.88")
    ax_a.set_axisbelow(True)
    ax_a.legend(loc="upper right", frameon=True, framealpha=0.95)

    # ---- panel b: LOO sigma(delta_b) vs k ----
    base = float(sub["loo_sigma_baseline"].iloc[0])
    ax_b.plot(sub["k"], sub["loo_sigma_delta_b"],
              color=_CURVE_COLOR, marker="o", linewidth=1.2, markersize=4.0,
              label="per-cluster median")
    ax_b.axhline(base, color="black", linewidth=0.9, linestyle="--",
                 label=f"global-median baseline  ({base:.3f})")

    valid = sub["loo_sigma_delta_b"].dropna()
    if len(valid) > 0:
        best_idx = sub["loo_sigma_delta_b"].idxmin()
        best_k = int(sub.at[best_idx, "k"])
        best_sigma = float(sub.at[best_idx, "loo_sigma_delta_b"])
        gain_pct = 100.0 * (base - best_sigma) / base
        ax_b.scatter([best_k], [best_sigma], s=55, facecolor="none",
                     edgecolor="0.20", linewidth=0.9, zorder=5)
        ax_b.text(
            0.02, 0.05,
            f"best: $k={best_k}$,  "
            f"$\\sigma(\\Delta b) = {best_sigma:.3f}$\n"
            f"({gain_pct:.0f}% under baseline)",
            transform=ax_b.transAxes,
            color="0.15", va="bottom", ha="left",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="white",
                      edgecolor="0.65", linewidth=0.5),
        )

    ax_b.set_xlabel(r"Number of clusters $k$")
    ax_b.set_ylabel(r"LOO $\sigma(\Delta b)$  [dex]")
    ax_b.set_xticks(_K_RANGE)
    ax_b.set_xlim(1.7, 12.3)
    ax_b.grid(True, linewidth=0.3, color="0.88")
    ax_b.set_axisbelow(True)
    ax_b.legend(loc="upper right", frameon=True, framealpha=0.95)

    panel_label(ax_a, "a", fontsize=12, y_offset_pt=8.0)
    panel_label(ax_b, "b", fontsize=12, y_offset_pt=8.0)

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_png = out_dir / "s1_b_clustering_silhouette.png"
    save_panel(fig, out_png)
    plt.close(fig)
    rc_stack.__exit__(None, None, None)
    return out_png
