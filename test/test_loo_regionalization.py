"""Unit test of the leave-one-out evaluation of the regionalization.

Checks on a synthetic summary that every fold assigns the regional exponent
by the rule of the released run, the median over the remaining training dams
at or above the minimum training capacity with complete features, and not
over every remaining training dam.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from eaves.postprocess.regionalization import (
    FALLBACK_RELIABILITY_THRESHOLD_MCM,
    exponent_training_set,
    minimum_training_capacity,
    regional_median_exponent,
)
from eaves.postprocess.reliability import training_mask, trusted_mask
from eaves.postprocess.validation import loo_regionalization_eval


def _synthetic_summary(seed: int = 3) -> pd.DataFrame:
    """Sixty trusted dams built after the SRTM acquisition: forty at or above 1 MCM, five of them with a missing
    valley ratio, and twenty below 1 MCM whose exponents sit above the rest."""
    rng = np.random.default_rng(seed)
    n_large, n_small = 40, 20
    capacity = np.concatenate([rng.uniform(1.5, 50.0, n_large), rng.uniform(0.2, 0.9, n_small)])
    b = np.concatenate([rng.uniform(1.2, 1.6, n_large), rng.uniform(1.8, 2.0, n_small)])
    valley_ratio = np.exp(rng.normal(3.5, 0.8, n_large + n_small))
    valley_ratio[:5] = np.nan
    footprint = 0.4 * capacity ** 0.6
    df = pd.DataFrame({
        "dam_id":                [f"D{i:03d}" for i in range(n_large + n_small)],
        "capacity_mcm":          capacity,
        "footprint_area_km2":    footprint,
        "c":                     capacity * 1e6 / (footprint * 1e6) ** b,
        "b":                     b,
        "quality":               "A",
        "r_squared":             0.995,
        "vol_ratio":             1.0,
        "n_pixels":              200,
        "construction_year":     2008,
        "dam_height_m":          np.exp(rng.normal(2.5, 0.4, n_large + n_small)),
        "spillway_height_m":     np.exp(rng.normal(2.2, 0.4, n_large + n_small)),
        "valley_ratio":          valley_ratio,
        "channel_slope":         np.exp(rng.normal(-5.0, 0.7, n_large + n_small)),
        "mean_catchment_slope":  np.exp(rng.normal(-2.0, 0.5, n_large + n_small)),
        "upstream_area_km2":     np.exp(rng.normal(4.0, 1.2, n_large + n_small)),
    })
    return df


def test_each_fold_takes_the_exponent_from_the_eligible_remaining_dams(tmp_path):
    df = _synthetic_summary()
    summary_csv = tmp_path / "eaves_summary.csv"
    df.to_csv(summary_csv, index=False)
    water_dir = tmp_path / "water_extent"
    water_dir.mkdir()

    out = loo_regionalization_eval(str(summary_csv), str(water_dir), str(tmp_path / "validation"))

    df["reliable"] = trusted_mask(df)
    df["training"] = training_mask(df)
    threshold, _, fallback = minimum_training_capacity(df)
    assert threshold == pytest.approx(1.0)
    assert not fallback
    trusted = df[df["training"]].reset_index(drop=True)
    assert len(out) == len(trusted) == 60

    for _, rec in out.iterrows():
        remaining = trusted[trusted["dam_id"] != rec["dam_id"]]
        expected = exponent_training_set(remaining, threshold)["b"].median()
        assert len(exponent_training_set(remaining, threshold)) in (34, 35)
        # The returned table carries the released precision of b, four decimals
        assert rec["b_reg"] == pytest.approx(expected, abs=5e-5)
        assert abs(rec["b_reg"] - remaining["b"].median()) > 1e-3

    assert (tmp_path / "validation" / "regionalization_loo.csv").is_file()


def test_the_fold_threshold_falls_back_when_no_candidate_qualifies(tmp_path):
    # Eighteen dams, fewer than the 30 and the 20 the two tiers of the threshold rule require
    df = _synthetic_summary().iloc[:18].reset_index(drop=True)
    summary_csv = tmp_path / "eaves_summary.csv"
    df.to_csv(summary_csv, index=False)
    water_dir = tmp_path / "water_extent"
    water_dir.mkdir()

    out = loo_regionalization_eval(str(summary_csv), str(water_dir), str(tmp_path / "validation"))

    df["reliable"] = trusted_mask(df)
    df["training"] = training_mask(df)
    threshold, _, fallback = minimum_training_capacity(df)
    assert fallback
    assert threshold == pytest.approx(FALLBACK_RELIABILITY_THRESHOLD_MCM)
    trusted = df[df["training"]].reset_index(drop=True)
    assert len(out) == len(trusted) == 18

    for _, rec in out.iterrows():
        remaining = trusted[trusted["dam_id"] != rec["dam_id"]]
        expected = regional_median_exponent(exponent_training_set(remaining, FALLBACK_RELIABILITY_THRESHOLD_MCM))
        assert rec["b_reg"] == pytest.approx(expected, abs=5e-5)
