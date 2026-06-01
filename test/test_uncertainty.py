"""Unit tests for :mod:`eaves.postprocess.uncertainty`.

Covers the b_sigma estimator, the anchor back-solve, and the V band algebra
that backs the S3 supplementary panel. All synthetic, no disk I/O.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from eaves.postprocess.uncertainty import (
    _FILL_LEVELS,
    _a_cap_m2,
    _v_sigma_dex,
    compute_b_sigma,
    compute_uncertainty_table,
)


def _trusted_summary(n: int = 40, seed: int = 0) -> pd.DataFrame:
    """Summary frame that passes the trusted-set gate, with spread-out b."""
    rng = np.random.default_rng(seed)
    return pd.DataFrame({
        "quality":   ["A"] * n,
        "r_squared": [0.995] * n,
        "vol_ratio": [1.0] * n,
        "n_pixels":  [200] * n,
        "b":         rng.normal(1.5, 0.25, n),
    })


class TestComputeBSigma:

    def test_returns_population_half_width(self):
        df = _trusted_summary(n=200)
        b = df["b"]
        expected = float((b.quantile(0.84) - b.quantile(0.16)) / 2.0)
        assert compute_b_sigma(df) == pytest.approx(expected)

    def test_fallback_when_too_few_trusted(self):
        df = _trusted_summary(n=5)
        assert compute_b_sigma(df) == pytest.approx(0.25)

    def test_untrusted_rows_excluded(self):
        df = _trusted_summary(n=40)
        bad = df.copy()
        bad["r_squared"] = 0.5          # all fail the r^2 gate
        combined = pd.concat([df, bad], ignore_index=True)
        # Only the 40 good rows should drive the estimate.
        assert compute_b_sigma(combined) == pytest.approx(compute_b_sigma(df))

    def test_returns_positive_finite(self):
        v = compute_b_sigma(_trusted_summary(n=50))
        assert np.isfinite(v) and v > 0


class TestAnchorBackSolve:

    def test_a_cap_inverts_power_law(self):
        c, b, cap_mcm = 0.01, 1.5, 10.0
        a_cap = _a_cap_m2(c, b, cap_mcm)
        # By construction V_cap = c * A_cap^b must reproduce the capacity.
        assert c * a_cap**b == pytest.approx(cap_mcm * 1e6, rel=1e-9)

    def test_a_cap_positive(self):
        assert _a_cap_m2(0.005, 1.8, 0.4) > 0


class TestVSigmaDex:

    def test_zero_at_full_pool(self):
        assert _v_sigma_dex(0.26, 1.0) == pytest.approx(0.0)

    def test_equals_b_sigma_at_tenth_pool(self):
        # |log10(0.1)| = 1, so sigma == b_sigma at a tenth of full-pool area.
        assert _v_sigma_dex(0.26, 0.10) == pytest.approx(0.26)

    def test_widens_as_area_drops(self):
        s_half = _v_sigma_dex(0.26, 0.5)
        s_tenth = _v_sigma_dex(0.26, 0.1)
        assert 0 < s_half < s_tenth


class TestUncertaintyTable:

    def _params(self) -> pd.DataFrame:
        return pd.DataFrame({
            "dam_id":       ["id_a", "id_b"],
            "source":       ["srtm_derived", "regi_multi"],
            "c":            [0.01, 0.05],
            "b":            [1.5, 1.3],
            "capacity_mcm": [10.0, 0.5],
        })

    def test_has_expected_columns(self):
        out = compute_uncertainty_table(self._params(), b_sigma=0.26)
        for label in _FILL_LEVELS:
            assert f"V_pred_{label}_mcm" in out.columns
            assert f"V_sigma_dex_{label}" in out.columns
            assert f"V_pct_up_{label}" in out.columns
        assert len(out) == 2

    def test_sigma_increases_toward_low_pool(self):
        out = compute_uncertainty_table(self._params(), b_sigma=0.26)
        row = out.iloc[0]
        assert (row["V_sigma_dex_half_pool"]
                < row["V_sigma_dex_quarter_pool"]
                < row["V_sigma_dex_tenth_pool"])

    def test_a_cap_matches_back_solve(self):
        p = self._params()
        out = compute_uncertainty_table(p, b_sigma=0.26).set_index("dam_id")
        for _, r in p.iterrows():
            expected_km2 = _a_cap_m2(r["c"], r["b"], r["capacity_mcm"]) / 1e6
            assert out.at[r["dam_id"], "A_cap_km2"] == pytest.approx(expected_km2)

    def test_pct_bounds_are_positive(self):
        out = compute_uncertainty_table(self._params(), b_sigma=0.26)
        for label in _FILL_LEVELS:
            assert (out[f"V_pct_up_{label}"] >= 0).all()
