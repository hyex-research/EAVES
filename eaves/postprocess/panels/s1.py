"""Panel s1 (supplementary): K-means clustering of training dams.

Three questions:

1.  Do the training dams partition into morphological clusters in
    log-transformed feature space? Quantified by the mean silhouette
    coefficient across ``k = 2 .. 12``.
2.  Even if they did, would a per-cluster median ``b`` reduce out-of-sample
    error? Quantified by leave-one-out ``sigma(delta_b)`` against the
    global-median baseline and by the leave-one-out R² of the per-cluster
    median.
3.  Does ``b`` follow a continuous gradient of the features instead?
    Quantified by the variance shares of the first two principal components
    of the features and the Spearman correlation of ``b`` with the first.

Writes:

- ``<CSV_DIR>/validation/b_clustering_diagnostic.csv``  diagnostic data.
- ``<PLOT_DIR>/s1_b_clustering_silhouette.png``         three-panel figure.

The diagnostic CSV is written here and read by :mod:`eaves.postprocess.report`.
"""

from __future__ import annotations

import os
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D
from scipy.stats import spearmanr
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.metrics import silhouette_score
from sklearn.model_selection import LeaveOneOut

import eaves.config as _cfg

from ...utils import dams_with_fill, round_released_columns
from ..reliability import training_mask
from ._shared import PANEL_TEXT_RC, apply_style, mm_to_in, panel_label, save_panel

# ---- Feature set and k range ----
CLUSTER_FEATURES: list[str] = [
    "valley_ratio", "channel_slope", "mean_catchment_slope",
    "dam_height_m", "spillway_height_m", "dam_length_m",
]
_K_RANGE = list(range(2, 13))
_CURVE_COLOR = "#D62728"   # red
_B_CMAP = "viridis"
_CLUSTER_MARKERS = ["o", "s", "^", "D", "v", "P", "X", "<", ">", "h", "p", "*"]


# ---- Preprocessing ----
def _trusted(df: pd.DataFrame) -> pd.DataFrame:
    # Selects the training population (trusted-set criteria and post-SRTM construction), the dams the regionalization procedure is trained on
    return df[training_mask(df)].copy().reset_index(drop=True)


def _design_matrix(df: pd.DataFrame, feats: list[str]) -> np.ndarray:
    X = np.log(np.clip(df[feats].values.astype(float), 1e-9, None))
    mu, sd = X.mean(axis=0), X.std(axis=0)
    sd[sd == 0] = 1.0
    return (X - mu) / sd


# ---- Silhouette and LOO sigma(delta b) ----
def _silhouette_curve(X: np.ndarray, ks: list[int], seed: int = 42) -> list[float]:
    return [
        float(silhouette_score(
            X, KMeans(n_clusters=k, n_init=10, random_state=seed).fit(X).labels_
        ))
        for k in ks
    ]


def _loo_cluster_sigma(T: pd.DataFrame, feats: list[str], k: int,
                       seed: int = 42, n_init: int = 3) -> tuple[float, float]:
    """LOO sigma(delta_b) and LOO R² of the per-cluster-median prediction at the given k.

    Each LOO fold runs its own KMeans with ``n_init`` initializations (3 by
    default, against 10 for the silhouette curve). The resulting ``sigma`` is
    within 0.005 of its value at ``n_init=10``. The R² is one minus the mean
    squared error of the predictions over the variance of ``b``.
    """
    X = _design_matrix(T, feats)
    b = T["b"].values
    preds = np.zeros(len(T))
    for tr, te in LeaveOneOut().split(X):
        km = KMeans(n_clusters=k, n_init=n_init, random_state=seed).fit(X[tr])
        cid = km.predict(X[te])[0]
        cl = b[tr][km.labels_ == cid]
        preds[te] = float(np.median(cl)) if len(cl) else float(np.median(b[tr]))
    delta = preds - b
    sigma = float((np.quantile(delta, 0.84) - np.quantile(delta, 0.16)) / 2.0)
    r2 = float(1.0 - np.mean(delta ** 2) / np.var(b))
    return sigma, r2


def _baseline_sigma(T: pd.DataFrame) -> float:
    """LOO sigma(delta_b) for the global-median predictor (no clustering)."""
    b = T["b"].values
    preds = np.array([np.median(np.delete(b, i)) for i in range(len(b))])
    d = preds - b
    return float((np.quantile(d, 0.84) - np.quantile(d, 0.16)) / 2.0)


# ---- Principal components ----
def _principal_components(X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Scores of the rows of ``X`` on its principal components and the variance share of each component."""
    pca = PCA().fit(X)
    return pca.transform(X), pca.explained_variance_ratio_


def _cluster_labels(X: np.ndarray, pc1: np.ndarray, k: int, seed: int = 42) -> np.ndarray:
    """K-means labels at the given k, numbered by increasing mean score of the cluster on the first principal component."""
    labels = KMeans(n_clusters=k, n_init=10, random_state=seed).fit(X).labels_
    order = np.argsort([pc1[labels == i].mean() for i in range(k)])
    return np.argsort(order)[labels]


def _compute(summary_csv: str, out_csv_dir: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Computes the diagnostic, writes it to ``b_clustering_diagnostic.csv`` and returns it with the training dams."""
    T = _trusted(dams_with_fill(pd.read_csv(summary_csv)))
    if len(T) < 10:
        raise RuntimeError(
            f"training set too small (n={len(T)}). The silhouette "
            "diagnostic needs ~50+ dams to be meaningful"
        )
    base = _baseline_sigma(T)
    X = _design_matrix(T, CLUSTER_FEATURES)
    sil = _silhouette_curve(X, _K_RANGE)
    scores, var_share = _principal_components(X)
    pc1_rho = float(spearmanr(scores[:, 0], T["b"].values).statistic)
    rows = []
    for k, s in zip(_K_RANGE, sil):
        sigma, r2 = _loo_cluster_sigma(T, CLUSTER_FEATURES, k)
        rows.append({
            "feature_set":           "raw morphometry",
            "k":                     k,
            "silhouette":            s,
            "loo_sigma_delta_b":     sigma,
            "loo_sigma_baseline":    base,
            "loo_relative_gain_pct": 100.0 * (base - sigma) / base,
            "loo_r2":                r2,
            "n_trusted":             int(len(T)),
            "pc1_var_share":         float(var_share[0]),
            "pc2_var_share":         float(var_share[1]),
            "pc1_spearman_b":        pc1_rho,
        })
    df = pd.DataFrame(rows)
    os.makedirs(out_csv_dir, exist_ok=True)
    out = os.path.join(out_csv_dir, "b_clustering_diagnostic.csv")
    round_released_columns(df).to_csv(out, index=False)
    return df, T


# ---- Figure ----
def make_s1_clustering(out_dir: Path) -> Path:
    """Computes the b-clustering diagnostic and renders the supplementary figure.

    The diagnostic is recomputed on every call and its CSV is written to
    ``<CSV_DIR>/validation/``, where the report reads it. ``out_dir`` sets only
    the PNG destination.
    """
    apply_style()

    summary_csv = os.path.join(_cfg.CSV_DIR, "eaves_summary.csv")
    validation_dir = os.path.join(_cfg.CSV_DIR, "validation")
    df, T = _compute(summary_csv, validation_dir)

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_png = out_dir / "s1_b_clustering_silhouette.png"

    with plt.rc_context(PANEL_TEXT_RC):
        fig_w = mm_to_in(187.0)
        fig_h = mm_to_in(72.0)
        fig, (ax_a, ax_b, ax_c) = plt.subplots(1, 3, figsize=(fig_w, fig_h))
        fig.subplots_adjust(left=0.0822, right=0.986, top=0.91, bottom=0.17,
                            wspace=0.42)

        sub = df.sort_values("k")

        # ---- Panel a: silhouette vs k ----
        ax_a.plot(sub["k"], sub["silhouette"],
                  color=_CURVE_COLOR, marker="o", linewidth=1.2, markersize=4.0)
        ax_a.axhline(0.50, color="0.45", linewidth=0.7, linestyle="--")
        ax_a.text(12.2, 0.505, "Reasonable structure",
                  color="0.40", va="bottom", ha="right")
        ax_a.axhline(0.25, color="0.65", linewidth=0.7, linestyle=":")
        ax_a.text(12.2, 0.255, "Weak structure",
                  color="0.55", va="bottom", ha="right")

        ax_a.set_xlabel(r"Number of clusters $k$")
        ax_a.set_ylabel("Mean silhouette coefficient")
        ax_a.set_xticks(_K_RANGE[::2])
        ax_a.set_xlim(1.7, 12.3)
        # Spans the curve and both reference lines, with room for the label over the upper line
        sil = sub["silhouette"]
        ax_a.set_ylim(min(0.25, float(sil.min())) - 0.06, max(0.50, float(sil.max())) + 0.06)
        ax_a.grid(True, linewidth=0.3, color="0.88")
        ax_a.set_axisbelow(True)

        # ---- Panel b: LOO sigma(delta_b) vs k ----
        base = float(sub["loo_sigma_baseline"].iloc[0])
        ax_b.plot(sub["k"], sub["loo_sigma_delta_b"],
                  color=_CURVE_COLOR, marker="o", linewidth=1.2, markersize=4.0,
                  label="Cluster median")
        ax_b.axhline(base, color="black", linewidth=0.9, linestyle="--",
                     label="Global median")

        best_idx = sub["loo_sigma_delta_b"].idxmin()
        best_k = int(sub.at[best_idx, "k"])
        best_sigma = float(sub.at[best_idx, "loo_sigma_delta_b"])
        ax_b.scatter([best_k], [best_sigma], s=55, facecolor="none",
                     edgecolor="0.20", linewidth=0.9, zorder=5)
        gain = f"{-float(sub.at[best_idx, 'loo_relative_gain_pct']):+.0f}%".replace("-", "\N{MINUS SIGN}")
        ax_b.annotate(
            f"{gain}, "
            f"$R^2_{{\\mathrm{{LOO}}}} = {sub.at[best_idx, 'loo_r2']:.2f}$",
            xy=(best_k, best_sigma), xytext=(-4, -8), textcoords="offset points",
            color="0.15", va="top", ha="left",
        )
        # Leaves a band under the curve for the best-k note and a band over the baseline for the key
        span = base - float(sub["loo_sigma_delta_b"].min())
        ax_b.set_ylim(best_sigma - 0.45 * span, base + 0.65 * span)

        ax_b.set_xlabel(r"Number of clusters $k$")
        ax_b.set_ylabel(r"Leave-one-out $\sigma(\Delta b)$")
        ax_b.set_xticks(_K_RANGE[::2])
        ax_b.set_xlim(1.7, 12.3)
        ax_b.grid(True, linewidth=0.3, color="0.88")
        ax_b.set_axisbelow(True)
        ax_b.legend(loc="upper right", frameon=False,
                    handlelength=1.5, borderaxespad=0.2)

        # ---- Panel c: PC1 vs PC2 colored by b, marker shape by cluster ----
        X = _design_matrix(T, CLUSTER_FEATURES)
        scores, _ = _principal_components(X)
        labels = _cluster_labels(X, scores[:, 0], best_k)
        b = T["b"].values
        norm = plt.Normalize(vmin=float(b.min()), vmax=float(b.max()))
        handles = []
        for i in range(best_k):
            sel = labels == i
            marker = _CLUSTER_MARKERS[i % len(_CLUSTER_MARKERS)]
            mappable = ax_c.scatter(
                scores[sel, 0], scores[sel, 1], c=b[sel], cmap=_B_CMAP, norm=norm,
                marker=marker, s=14, edgecolor="0.25", linewidth=0.3, zorder=3,
            )
            handles.append(Line2D([], [], linestyle="none", marker=marker,
                                  markersize=4.5, markerfacecolor="0.75",
                                  markeredgecolor="0.25", markeredgewidth=0.5,
                                  label=f"Cluster {i + 1}" if i == 0 else f"{i + 1}"))
        ax_c.legend(handles=handles, loc="upper left", ncol=best_k, frameon=False,
                    handlelength=0.8, handletextpad=0.3, columnspacing=0.7,
                    borderaxespad=0.2)

        # Leaves a band over the cloud for the cluster key and a band under it for the colorbar
        y_lo, y_hi = float(scores[:, 1].min()), float(scores[:, 1].max())
        y_span = y_hi - y_lo
        ax_c.set_ylim(y_lo - 0.22 * y_span, y_hi + 0.16 * y_span)
        cax = ax_c.inset_axes([0.52, 0.12, 0.45, 0.04])
        cbar = fig.colorbar(mappable, cax=cax, orientation="horizontal")
        cax.text(-0.04, 0.5, "$b$", transform=cax.transAxes, ha="right", va="center")
        cbar.ax.xaxis.set_major_locator(plt.MultipleLocator(0.5))
        cbar.ax.xaxis.set_major_formatter(plt.FormatStrFormatter("%g"))
        cbar.ax.tick_params(length=2.0, pad=1.5)
        cbar.outline.set_linewidth(0.5)

        ax_c.set_xlabel(f"PC1 ({100.0 * float(sub['pc1_var_share'].iloc[0]):.0f}% of variance)")
        ax_c.set_ylabel(f"PC2 ({100.0 * float(sub['pc2_var_share'].iloc[0]):.0f}% of variance)")
        ax_c.xaxis.set_major_locator(plt.MultipleLocator(2))
        ax_c.yaxis.set_major_locator(plt.MultipleLocator(2))
        ax_c.grid(True, linewidth=0.3, color="0.88")
        ax_c.set_axisbelow(True)

        panel_label(ax_a, "a", fontsize=12, y_offset_pt=8.0)
        panel_label(ax_b, "b", fontsize=12, y_offset_pt=8.0)
        panel_label(ax_c, "c", fontsize=12, y_offset_pt=8.0)

        # Opens the axes by hiding the top and right spines
        for _ax in fig.axes:
            _ax.spines["top"].set_visible(False)
            _ax.spines["right"].set_visible(False)

        save_panel(fig, out_png)
    plt.close(fig)
    return out_png
