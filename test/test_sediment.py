"""Unit tests for the sediment-budget helpers in
:mod:`eaves.postprocess.report`.

Covers the delivered-yield budget (no additional SDR by default, constant
override available), the trap-saturation cap, and the categorical silt-risk
banding.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from eaves.postprocess.report import (
    _silt_risk_label,
    augment_summary_with_sediment_risk,
)


def _synthetic_summary(tmp_path, capacity_mcm=10.0, yield_t_ha_yr=5.0,
                       area_km2=100.0, construction_year=2000):
    df = pd.DataFrame({
        "dam_id": ["id_test"],
        "sed_yield_t_ha_yr": [yield_t_ha_yr],
        "upstream_area_km2": [area_km2],
        "capacity_mcm": [capacity_mcm],
        "construction_year": [construction_year],
    })
    path = tmp_path / "eaves_summary.csv"
    df.to_csv(path, index=False)
    return df, path


class TestDeliveredYieldBudget:

    def test_no_sdr_applied_by_default(self, tmp_path):
        # The yield input is delivered yield (Boyce SDR applied at source,
        # Dash et al. 2025 Eq. 3), so the default budget must not discount
        # delivery a second time.
        df, path = _synthetic_summary(tmp_path)
        augment_summary_with_sediment_risk(
            df, path, ref_year=2020, sediment_sdr=None,
            sediment_bulk_density=1.3)
        out = pd.read_csv(path)
        # V_sed = Y * A_ha * years / rho / 1e6 [MCM], years = 20
        # The CSV stores the fraction rounded to 6 decimals.
        expected = 5.0 * (100.0 * 100.0) * 20 / 1.3 / 1e6 / 10.0
        assert out["predicted_silt_fraction"].iloc[0] == pytest.approx(
            min(expected, 1.0), abs=1e-6)

    def test_constant_sdr_override(self, tmp_path):
        df, path = _synthetic_summary(tmp_path, capacity_mcm=100.0)
        augment_summary_with_sediment_risk(
            df, path, ref_year=2020, sediment_sdr=0.5,
            sediment_bulk_density=1.3)
        out = pd.read_csv(path)
        expected = 5.0 * (100.0 * 100.0) * 20 * 0.5 / 1.3 / 1e6 / 100.0
        assert out["predicted_silt_fraction"].iloc[0] == pytest.approx(
            expected, abs=1e-6)

    def test_trap_saturation_caps_at_one(self, tmp_path):
        df, path = _synthetic_summary(tmp_path, capacity_mcm=0.01)
        augment_summary_with_sediment_risk(
            df, path, ref_year=2020, sediment_sdr=None,
            sediment_bulk_density=1.3)
        out = pd.read_csv(path)
        assert out["predicted_silt_fraction"].iloc[0] == pytest.approx(1.0)
        assert out["sediment_risk"].iloc[0] == "fully_silted"


class TestSiltRiskLabel:

    @pytest.mark.parametrize("frac,expected", [
        (0.05, "low"),
        (0.20, "moderate"),
        (0.40, "high"),
        (0.75, "severe"),
        (1.0, "fully_silted"),
        (1.5, "fully_silted"),
    ])
    def test_bands(self, frac, expected):
        assert _silt_risk_label(frac) == expected

    def test_nan_is_unknown(self):
        assert _silt_risk_label(float("nan")) == "unknown"

    def test_monotone_band_order(self):
        order = ["low", "moderate", "high", "severe", "fully_silted"]
        labels = [_silt_risk_label(f) for f in (0.05, 0.2, 0.4, 0.75, 1.0)]
        assert labels == order
