"""Unit tests for the s1 supplementary-panel helper functions.

All checks run on small synthetic data (no disk I/O, no config loading).
The LOO KMeans loop dominates the runtime.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from eaves.postprocess.panels.s1 import (
    CLUSTER_FEATURES,
    _baseline_sigma,
    _design_matrix,
    _loo_cluster_sigma,
    _silhouette_curve,
)

# ---- Shared synthetic data ----

def _synthetic_trusted(n: int = 40, seed: int = 0) -> pd.DataFrame:
    """Training dams with the s1 feature columns, the capacity and training flag that the released exponent rule reads, and a 'b' column."""
    rng = np.random.default_rng(seed)
    return pd.DataFrame({
        "valley_ratio":         np.exp(rng.normal(3.5, 0.6, n)),
        "channel_slope":        np.exp(rng.normal(-5.0, 0.6, n)),
        "mean_catchment_slope": np.exp(rng.normal(-2.0, 0.5, n)),
        "dam_height_m":         np.exp(rng.normal(2.5, 0.4, n)),
        "spillway_height_m":    np.exp(rng.normal(2.2, 0.4, n)),
        "dam_length_m":         np.exp(rng.normal(5.5, 0.5, n)),
        "capacity_mcm":         np.exp(rng.normal(0.5, 1.2, n)),
        "b":                    rng.normal(1.5, 0.25, n),
        "training":             True,
    })


# A minimum training capacity below every capacity, so every remaining training dam sets the exponent
_ALL = 0.0


# ---- s1 helpers ----

class TestDesignMatrix:

    def test_output_shape(self):
        T = _synthetic_trusted(n=20)
        X = _design_matrix(T, CLUSTER_FEATURES)
        assert X.shape == (20, len(CLUSTER_FEATURES))

    def test_columns_are_standardized(self):
        T = _synthetic_trusted(n=100)
        X = _design_matrix(T, CLUSTER_FEATURES)
        assert np.abs(X.mean(axis=0)).max() == pytest.approx(0.0, abs=1e-10)
        assert np.abs(X.std(axis=0) - 1.0).max() == pytest.approx(0.0, abs=1e-10)

    def test_constant_column_not_nan(self):
        T = _synthetic_trusted(n=10)
        T["dam_length_m"] = 100.0
        X = _design_matrix(T, CLUSTER_FEATURES)
        assert not np.isnan(X).any()


class TestSilhouetteCurve:

    def test_returns_correct_length(self):
        T = _synthetic_trusted(n=50)
        X = _design_matrix(T, CLUSTER_FEATURES)
        ks = [2, 3, 4]
        scores = _silhouette_curve(X, ks)
        assert len(scores) == 3

    def test_scores_in_valid_range(self):
        T = _synthetic_trusted(n=50)
        X = _design_matrix(T, CLUSTER_FEATURES)
        scores = _silhouette_curve(X, [2, 3])
        assert all(-1.0 <= s <= 1.0 for s in scores)

    def test_reproducible_with_same_seed(self):
        T = _synthetic_trusted(n=50)
        X = _design_matrix(T, CLUSTER_FEATURES)
        s1 = _silhouette_curve(X, [2, 3], seed=7)
        s2 = _silhouette_curve(X, [2, 3], seed=7)
        assert s1 == s2

    def test_returns_floats(self):
        T = _synthetic_trusted(n=30)
        X = _design_matrix(T, CLUSTER_FEATURES)
        scores = _silhouette_curve(X, [2])
        assert all(isinstance(s, float) for s in scores)


class TestBaselineSigma:

    def test_constant_b_returns_zero(self):
        T = _synthetic_trusted(n=20)
        T["b"] = 1.5
        sigma = _baseline_sigma(T, _ALL)
        assert sigma == pytest.approx(0.0, abs=1e-6)

    def test_returns_positive_for_spread_b(self):
        T = _synthetic_trusted(n=40)
        sigma = _baseline_sigma(T, _ALL)
        assert sigma > 0.0

    def test_returns_finite_float(self):
        T = _synthetic_trusted(n=20)
        sigma = _baseline_sigma(T, _ALL)
        assert np.isfinite(sigma)

    def test_baseline_applies_the_released_exponent_rule(self):
        T = _synthetic_trusted(n=30)
        T.loc[:9, "capacity_mcm"] = 0.5
        T.loc[10:, "capacity_mcm"] = 5.0
        T.loc[:9, "b"] = T.loc[:9, "b"] + 0.5
        b = T["b"].values
        preds = np.array([T.drop(index=i).query("capacity_mcm >= 1.0")["b"].median() for i in range(len(T))])
        d = preds - b
        expected = (np.quantile(d, 0.84) - np.quantile(d, 0.16)) / 2.0
        assert _baseline_sigma(T, 1.0) == pytest.approx(expected)
        assert _baseline_sigma(T, 1.0) != pytest.approx(_baseline_sigma(T, _ALL))

    def test_larger_spread_gives_larger_sigma(self):
        rng = np.random.default_rng(99)
        T_narrow = _synthetic_trusted(n=40)
        T_wide = T_narrow.copy()
        T_narrow["b"] = rng.normal(1.5, 0.1, len(T_narrow))
        T_wide["b"]   = rng.normal(1.5, 1.0, len(T_wide))
        assert _baseline_sigma(T_wide, _ALL) > _baseline_sigma(T_narrow, _ALL)


class TestLooClusterSigma:

    def test_returns_positive_finite_sigma_and_bounded_r2(self):
        T = _synthetic_trusted(n=30)
        sigma, r2 = _loo_cluster_sigma(T, CLUSTER_FEATURES, k=2, threshold_mcm=_ALL, n_init=1)
        assert np.isfinite(sigma) and sigma >= 0.0
        assert np.isfinite(r2) and r2 <= 1.0

    def test_perfectly_separable_groups_give_small_sigma(self):
        n = 30
        T = _synthetic_trusted(n=n)
        T["valley_ratio"] = np.concatenate([
            np.full(n // 2, 5.0),
            np.full(n - n // 2, 100.0),
        ])
        T["b"] = np.concatenate([
            np.full(n // 2, 1.1),
            np.full(n - n // 2, 2.1),
        ])
        sigma, _ = _loo_cluster_sigma(T, CLUSTER_FEATURES, k=2, threshold_mcm=_ALL, n_init=3)
        baseline = _baseline_sigma(T, _ALL)
        assert sigma < baseline

    def test_sigma_with_k1_equals_baseline(self):
        T = _synthetic_trusted(n=25)
        sigma_k1, _ = _loo_cluster_sigma(T, CLUSTER_FEATURES, k=1, threshold_mcm=_ALL, n_init=1)
        baseline = _baseline_sigma(T, _ALL)
        assert sigma_k1 == pytest.approx(baseline, rel=0.05)

