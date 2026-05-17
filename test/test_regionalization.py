"""Unit tests for the multi-feature LR regionalization recipe.

Covers feature-vector construction, model fitting, prediction, and the
single-recipe back-solve. All checks run on small synthetic data without
touching disk, so the module runs in well under a second.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from eaves.postprocess.regionalization import (
    _REGIONAL_FEATURES,
    _log_feature_vector,
    _fit_multi_anchor_lr,
    _predict_multi_anchor_lr,
)


# ---------------------------------------------------------------------------
# Synthetic data generator
# ---------------------------------------------------------------------------

def _synthetic_trusted(n: int = 50, seed: int = 42) -> pd.DataFrame:
    """Build a synthetic trusted-set dataframe with a known A_cap relation.

    Truth: ``log A_cap = -2 + 0.5 log V_cap + 0.3 log valley_ratio + N(0, 0.1)``.
    Other features are correlated with each other only via being log-normal
    draws -- they carry no signal toward the target. A well-behaved
    regression should put coefficients ~0.5 on capacity and ~0.3 on
    valley_ratio.
    """
    rng = np.random.default_rng(seed)
    cap_mcm = np.exp(rng.normal(0.0, 1.5, size=n))
    dam_h = np.exp(rng.normal(2.5, 0.4, size=n))
    sp_h = dam_h * rng.uniform(0.6, 0.9, size=n)
    vr = np.exp(rng.normal(3.5, 0.8, size=n))
    cs = np.exp(rng.normal(-5.0, 0.7, size=n))
    mcs = np.exp(rng.normal(-2.0, 0.5, size=n))
    ua = np.exp(rng.normal(4.0, 1.2, size=n))
    log_a = (
        -2.0
        + 0.5 * np.log(cap_mcm)
        + 0.3 * np.log(vr)
        + rng.normal(0.0, 0.1, size=n)
    )
    return pd.DataFrame({
        "capacity_mcm":          cap_mcm,
        "dam_height_m":          dam_h,
        "spillway_height_m":     sp_h,
        "valley_ratio":          vr,
        "channel_slope":         cs,
        "mean_catchment_slope":  mcs,
        "upstream_area_km2":     ua,
        "footprint_area_km2":    np.exp(log_a),
    })


# ---------------------------------------------------------------------------
# _log_feature_vector
# ---------------------------------------------------------------------------

class TestFeatureVector:

    def test_returns_log_array_when_all_features_present(self):
        row = {f: float(i + 1) for i, f in enumerate(_REGIONAL_FEATURES)}
        v = _log_feature_vector(row)
        assert v is not None
        assert v.shape == (len(_REGIONAL_FEATURES),)
        for i in range(len(_REGIONAL_FEATURES)):
            assert v[i] == pytest.approx(np.log(i + 1))

    def test_returns_none_for_nan(self):
        row = {f: 1.0 for f in _REGIONAL_FEATURES}
        row["valley_ratio"] = np.nan
        assert _log_feature_vector(row) is None

    @pytest.mark.parametrize("bad_value", [0.0, -0.5, -1e6])
    def test_returns_none_for_non_positive(self, bad_value):
        row = {f: 1.0 for f in _REGIONAL_FEATURES}
        row["channel_slope"] = bad_value
        assert _log_feature_vector(row) is None

    def test_returns_none_when_key_missing(self):
        row = {f: 1.0 for f in _REGIONAL_FEATURES}
        del row["capacity_mcm"]
        assert _log_feature_vector(row) is None

    def test_accepts_pandas_series(self):
        row = pd.Series({f: float(i + 1) for i, f in enumerate(_REGIONAL_FEATURES)})
        v = _log_feature_vector(row)
        assert v is not None and v.shape == (len(_REGIONAL_FEATURES),)


# ---------------------------------------------------------------------------
# _fit_multi_anchor_lr
# ---------------------------------------------------------------------------

class TestMultiAnchorFit:

    def test_returns_none_when_too_few_rows(self):
        df = _synthetic_trusted(n=10)
        assert _fit_multi_anchor_lr(df, min_n=20) is None

    def test_returns_coefs_of_correct_shape(self):
        df = _synthetic_trusted(n=50)
        coefs = _fit_multi_anchor_lr(df)
        assert coefs is not None
        assert coefs.shape == (1 + len(_REGIONAL_FEATURES),)

    def test_recovers_known_relation_within_tolerance(self):
        df = _synthetic_trusted(n=300)
        coefs = _fit_multi_anchor_lr(df)
        assert coefs is not None
        idx_cap = _REGIONAL_FEATURES.index("capacity_mcm")
        idx_vr = _REGIONAL_FEATURES.index("valley_ratio")
        assert coefs[1 + idx_cap] == pytest.approx(0.5, abs=0.15)
        assert coefs[1 + idx_vr] == pytest.approx(0.3, abs=0.15)

    def test_skips_rows_with_any_missing_feature(self):
        df = _synthetic_trusted(n=50)
        df.loc[:5, "channel_slope"] = np.nan
        coefs = _fit_multi_anchor_lr(df)
        assert coefs is not None     # fit still works on the remaining rows

    def test_returns_none_when_target_column_missing(self):
        df = _synthetic_trusted(n=50).drop(columns=["footprint_area_km2"])
        assert _fit_multi_anchor_lr(df) is None


# ---------------------------------------------------------------------------
# _predict_multi_anchor_lr
# ---------------------------------------------------------------------------

class TestMultiAnchorPredict:

    def test_returns_none_when_coefs_is_none(self):
        row = {f: 1.0 for f in _REGIONAL_FEATURES}
        assert _predict_multi_anchor_lr(row, None) is None

    def test_returns_none_when_feature_missing(self):
        coefs = _fit_multi_anchor_lr(_synthetic_trusted(n=50))
        row = {f: 1.0 for f in _REGIONAL_FEATURES}
        row["valley_ratio"] = np.nan
        assert _predict_multi_anchor_lr(row, coefs) is None

    def test_returns_positive_finite_float(self):
        df = _synthetic_trusted(n=50)
        coefs = _fit_multi_anchor_lr(df)
        a = _predict_multi_anchor_lr(df.iloc[0].to_dict(), coefs)
        assert a is not None and np.isfinite(a) and a > 0

    def test_in_sample_error_is_small(self):
        df = _synthetic_trusted(n=300)
        coefs = _fit_multi_anchor_lr(df)
        errors = []
        for _, row in df.iterrows():
            a_pred = _predict_multi_anchor_lr(row, coefs)
            if a_pred is not None and a_pred > 0:
                errors.append(np.log(a_pred / row["footprint_area_km2"]))
        errors = np.asarray(errors)
        # Median residual sits on zero (well within 0.05 dex of zero)
        assert abs(float(np.median(errors))) < 0.05
        # 1-sigma residual matches the injected noise (0.1 dex) reasonably
        sigma = float((np.quantile(errors, 0.84) - np.quantile(errors, 0.16)) / 2)
        assert sigma < 0.2


# ---------------------------------------------------------------------------
# Back-solve c = V_cap / A_cap^b is exact at the anchor
# ---------------------------------------------------------------------------

class TestBackSolveAtAnchor:

    def test_back_solve_recovers_capacity_exactly(self):
        df = _synthetic_trusted(n=50)
        coefs = _fit_multi_anchor_lr(df)
        b = 1.5
        for _, row in df.iterrows():
            a_km2 = _predict_multi_anchor_lr(row, coefs)
            if a_km2 is None or a_km2 <= 0:
                continue
            a_m2 = a_km2 * 1e6
            v_cap_m3 = row["capacity_mcm"] * 1e6
            c = v_cap_m3 / (a_m2 ** b)
            # Reconstruct V at the anchor -- by construction = V_cap
            v_check = c * (a_m2 ** b)
            assert v_check == pytest.approx(v_cap_m3, rel=1e-9)


# ---------------------------------------------------------------------------
# Example regionalized dams: train on a synthetic trusted set, then
# regionalize a small handful of representative ungaged dams end-to-end.
# Useful as a worked example -- the test prints nothing but the assertions
# document the expected shape of the output for two named cases.
# ---------------------------------------------------------------------------

class TestExampleRegionalizedDams:
    """Two named example dams that exercise the multi-LR + back-solve path."""

    # A small wadi reservoir (mountainous catchment, narrow valley) and a
    # large plains reservoir (wide valley, gentle slopes). Together they
    # bracket the catalogue's typical regionalization workload.
    EXAMPLE_DAMS = [
        {
            "dam_id": "example_small_wadi",
            "capacity_mcm":         0.50,
            "dam_height_m":        12.0,
            "spillway_height_m":    9.0,
            "valley_ratio":        18.0,
            "channel_slope":        0.012,
            "mean_catchment_slope": 0.140,
            "upstream_area_km2":   25.0,
        },
        {
            "dam_id": "example_large_plain",
            "capacity_mcm":        50.0,
            "dam_height_m":        45.0,
            "spillway_height_m":   38.0,
            "valley_ratio":        90.0,
            "channel_slope":        0.004,
            "mean_catchment_slope": 0.030,
            "upstream_area_km2":  450.0,
        },
    ]

    def test_each_example_dam_gets_finite_positive_parameters(self):
        train = _synthetic_trusted(n=200)
        coefs = _fit_multi_anchor_lr(train)
        b = 1.5

        for dam in self.EXAMPLE_DAMS:
            a_km2 = _predict_multi_anchor_lr(dam, coefs)
            assert a_km2 is not None, f"{dam['dam_id']}: A_cap prediction failed"
            assert a_km2 > 0 and np.isfinite(a_km2), \
                f"{dam['dam_id']}: non-positive or non-finite A_cap = {a_km2}"

            a_m2 = a_km2 * 1e6
            v_cap_m3 = dam["capacity_mcm"] * 1e6
            c = v_cap_m3 / (a_m2 ** b)
            assert c > 0 and np.isfinite(c), \
                f"{dam['dam_id']}: invalid c = {c}"
            # At the predicted anchor, the back-solved curve must reproduce V_cap.
            v_at_anchor = c * (a_m2 ** b)
            assert v_at_anchor == pytest.approx(v_cap_m3, rel=1e-9), \
                f"{dam['dam_id']}: back-solve mismatch"

    def test_larger_capacity_predicts_larger_area(self):
        """Monotonicity smoke check across the two example dams."""
        train = _synthetic_trusted(n=200)
        coefs = _fit_multi_anchor_lr(train)
        a_small = _predict_multi_anchor_lr(self.EXAMPLE_DAMS[0], coefs)
        a_large = _predict_multi_anchor_lr(self.EXAMPLE_DAMS[1], coefs)
        assert a_large > a_small, (
            "Multi-LR predicted a smaller A_cap for the larger dam: "
            f"small={a_small:.4f}, large={a_large:.4f}"
        )

    def test_missing_feature_returns_none_predict(self):
        """The example small-wadi dam with valley_ratio dropped: predict must
        return None rather than silently fabricate a value. The production
        pipeline catches this case and median-imputes the missing feature
        before predicting (see ``run_regionalization``)."""
        train = _synthetic_trusted(n=200)
        coefs = _fit_multi_anchor_lr(train)
        dam = dict(self.EXAMPLE_DAMS[0])
        del dam["valley_ratio"]
        assert _predict_multi_anchor_lr(dam, coefs) is None
