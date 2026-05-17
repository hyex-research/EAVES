"""Unit tests for s1 and s2 supplementary-panel helper functions.

All checks run on small synthetic data (no disk I/O, no config loading).
Total runtime is dominated by the LOO KMeans loop: ~0.5 s on a workstation.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Shared synthetic data
# ---------------------------------------------------------------------------

def _synthetic_trusted(n: int = 40, seed: int = 0) -> pd.DataFrame:
    """DataFrame with the six s1 feature columns plus a 'b' column."""
    rng = np.random.default_rng(seed)
    return pd.DataFrame({
        "valley_ratio":         np.exp(rng.normal(3.5, 0.6, n)),
        "channel_slope":        np.exp(rng.normal(-5.0, 0.6, n)),
        "mean_catchment_slope": np.exp(rng.normal(-2.0, 0.5, n)),
        "dam_height_m":         np.exp(rng.normal(2.5, 0.4, n)),
        "spillway_height_m":    np.exp(rng.normal(2.2, 0.4, n)),
        "dam_length_m":         np.exp(rng.normal(5.5, 0.5, n)),
        "b":                    rng.normal(1.5, 0.25, n),
    })


def _threshold_df(thresholds=(1.0, 2.0, 5.0, 10.0, 25.0)) -> pd.DataFrame:
    """Synthetic threshold-sweep table with monotone frac_reliable."""
    rows = []
    n_total = 400
    for thr in thresholds:
        n_above = max(5, int(n_total * (1.0 - thr / 30.0)))
        frac = min(0.99, 0.60 + thr / 40.0)
        rows.append({"threshold_mcm": thr, "frac_reliable": frac, "n_above": n_above})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# s1 helpers
# ---------------------------------------------------------------------------

from eaves.postprocess.panels.s1 import (
    _FEATURES,
    _baseline_sigma,
    _design_matrix,
    _loo_cluster_sigma,
    _silhouette_curve,
)


class TestDesignMatrix:

    def test_output_shape(self):
        T = _synthetic_trusted(n=20)
        X = _design_matrix(T, _FEATURES)
        assert X.shape == (20, len(_FEATURES))

    def test_columns_are_standardized(self):
        T = _synthetic_trusted(n=100)
        X = _design_matrix(T, _FEATURES)
        assert np.abs(X.mean(axis=0)).max() == pytest.approx(0.0, abs=1e-10)
        assert np.abs(X.std(axis=0) - 1.0).max() == pytest.approx(0.0, abs=1e-10)

    def test_constant_column_not_nan(self):
        T = _synthetic_trusted(n=10)
        T["dam_length_m"] = 100.0
        X = _design_matrix(T, _FEATURES)
        assert not np.isnan(X).any()


class TestSilhouetteCurve:

    def test_returns_correct_length(self):
        T = _synthetic_trusted(n=50)
        X = _design_matrix(T, _FEATURES)
        ks = [2, 3, 4]
        scores = _silhouette_curve(X, ks)
        assert len(scores) == 3

    def test_scores_in_valid_range(self):
        T = _synthetic_trusted(n=50)
        X = _design_matrix(T, _FEATURES)
        scores = _silhouette_curve(X, [2, 3])
        assert all(-1.0 <= s <= 1.0 for s in scores)

    def test_reproducible_with_same_seed(self):
        T = _synthetic_trusted(n=50)
        X = _design_matrix(T, _FEATURES)
        s1 = _silhouette_curve(X, [2, 3], seed=7)
        s2 = _silhouette_curve(X, [2, 3], seed=7)
        assert s1 == s2

    def test_returns_floats(self):
        T = _synthetic_trusted(n=30)
        X = _design_matrix(T, _FEATURES)
        scores = _silhouette_curve(X, [2])
        assert all(isinstance(s, float) for s in scores)


class TestBaselineSigma:

    def test_constant_b_returns_zero(self):
        T = _synthetic_trusted(n=20)
        T["b"] = 1.5
        sigma = _baseline_sigma(T)
        assert sigma == pytest.approx(0.0, abs=1e-6)

    def test_returns_positive_for_spread_b(self):
        T = _synthetic_trusted(n=40)
        sigma = _baseline_sigma(T)
        assert sigma > 0.0

    def test_returns_finite_float(self):
        T = _synthetic_trusted(n=20)
        sigma = _baseline_sigma(T)
        assert np.isfinite(sigma)

    def test_larger_spread_gives_larger_sigma(self):
        rng = np.random.default_rng(99)
        T_narrow = _synthetic_trusted(n=40)
        T_wide = T_narrow.copy()
        T_narrow["b"] = rng.normal(1.5, 0.1, len(T_narrow))
        T_wide["b"]   = rng.normal(1.5, 1.0, len(T_wide))
        assert _baseline_sigma(T_wide) > _baseline_sigma(T_narrow)


class TestLooClusterSigma:

    def test_returns_positive_finite_float(self):
        T = _synthetic_trusted(n=30)
        sigma = _loo_cluster_sigma(T, _FEATURES, k=2, n_init=1)
        assert np.isfinite(sigma) and sigma >= 0.0

    def test_perfectly_separable_groups_give_small_sigma(self):
        n = 30
        rng = np.random.default_rng(1)
        T = _synthetic_trusted(n=n)
        T["valley_ratio"] = np.concatenate([
            np.full(n // 2, 5.0),
            np.full(n - n // 2, 100.0),
        ])
        T["b"] = np.concatenate([
            np.full(n // 2, 1.1),
            np.full(n - n // 2, 2.1),
        ])
        sigma = _loo_cluster_sigma(T, _FEATURES, k=2, n_init=3)
        baseline = _baseline_sigma(T)
        assert sigma < baseline

    def test_sigma_with_k1_equals_baseline(self):
        T = _synthetic_trusted(n=25)
        sigma_k1 = _loo_cluster_sigma(T, _FEATURES, k=1, n_init=1)
        baseline = _baseline_sigma(T)
        assert sigma_k1 == pytest.approx(baseline, rel=0.05)


# ---------------------------------------------------------------------------
# s2 helpers
# ---------------------------------------------------------------------------

from eaves.postprocess.panels.s2 import _chosen_threshold


class TestChosenThreshold:

    def test_returns_first_primary_match(self):
        df = pd.DataFrame({
            "threshold_mcm": [1.0, 5.0, 10.0],
            "frac_reliable": [0.75, 0.82, 0.91],
            "n_above":       [200, 80,   40],
        })
        assert _chosen_threshold(df) == pytest.approx(5.0)

    def test_falls_back_to_secondary_when_no_primary(self):
        df = pd.DataFrame({
            "threshold_mcm": [1.0, 5.0, 10.0],
            "frac_reliable": [0.65, 0.72, 0.79],
            "n_above":       [200, 50,   15],
        })
        assert _chosen_threshold(df) == pytest.approx(5.0)

    def test_returns_default_when_neither_condition_met(self):
        df = pd.DataFrame({
            "threshold_mcm": [1.0, 2.0, 5.0],
            "frac_reliable": [0.50, 0.55, 0.60],
            "n_above":       [10,  8,    5],
        })
        assert _chosen_threshold(df, default_mcm=7.0) == pytest.approx(7.0)

    def test_n_above_gate_prevents_primary_match(self):
        df = pd.DataFrame({
            "threshold_mcm": [5.0, 10.0],
            "frac_reliable": [0.85, 0.90],
            "n_above":       [10,   35],
        })
        assert _chosen_threshold(df) == pytest.approx(10.0)

    def test_empty_df_returns_default(self):
        df = pd.DataFrame(columns=["threshold_mcm", "frac_reliable", "n_above"])
        assert _chosen_threshold(df, default_mcm=3.0) == pytest.approx(3.0)
