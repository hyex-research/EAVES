"""Level-wise and two-segment residual statistics of the goodness-of-fit check."""
import os
import tempfile

import numpy as np
import pandas as pd
import pytest

from eaves.postprocess.validation import goodness_of_fit_check


def _summary_row(dam_id, c, b, curve_type="full", water_level=np.nan):
    return {
        "dam_id": dam_id, "quality": "A", "r_squared": 0.999, "vol_ratio": 1.0,
        "n_pixels": 200, "b": b, "c": c, "construction_year": 2010,
        "uncertainty_score": 0, "capped": False,
        "curve_type": curve_type, "srtm_water_level_m": water_level,
    }


def _run(cases, typical_extent_frac=np.nan):
    """Write the summary, params and EAV tables of ``cases`` to a temporary folder and run the check."""
    with tempfile.TemporaryDirectory() as d:
        tables = os.path.join(d, "eav_tables")
        os.makedirs(tables)
        rows, params = [], []
        for dam_id, c, b, table, kwargs in cases:
            rows.append(_summary_row(dam_id, c, b, **kwargs))
            params.append({"dam_id": dam_id, "c": c, "b": b, "source": "srtm_derived"})
            table.to_csv(os.path.join(tables, f"{dam_id}_eav.csv"), index=False)
        pd.DataFrame(rows).to_csv(os.path.join(d, "summary.csv"), index=False)
        pd.DataFrame(params).to_csv(os.path.join(d, "params.csv"), index=False)
        out = goodness_of_fit_check(os.path.join(d, "summary.csv"), os.path.join(d, "params.csv"),
                                    tables, os.path.join(d, "validation"),
                                    typical_extent_frac=typical_extent_frac)
    return out.set_index("dam_id")


def _table(areas, volumes):
    z = 100.0 + 0.5 * np.arange(len(areas))
    return pd.DataFrame({"elevation_m": z, "depth_m": z - z[0], "area_m2": areas, "volume_m3": volumes})


class TestGoodnessOfFitCheck:

    def test_exact_power_law_has_zero_residuals(self):
        c, b = 2.5e-3, 1.6
        areas = 1e4 * np.arange(1, 13, dtype=float)
        out = _run([("id_1", c, b, _table(areas, c * areas ** b), {})], typical_extent_frac=0.5)
        row = out.loc["id_1"]
        assert row["n_fit_bins"] == 12
        for col in ("rms_frac_resid", "abs_frac_resid_full_pool", "median_abs_frac_resid_upper_half",
                    "median_abs_frac_resid_below_tenth", "rms_frac_resid_upper_volume",
                    "rms_frac_resid_two_segment", "rms_frac_resid_two_segment_upper_volume",
                    "abs_frac_dev_typical_extent"):
            assert row[col] == pytest.approx(0.0, abs=1e-6), col

    def test_two_segment_fit_beats_one_power_law_on_two_regimes(self):
        areas = 1e4 * np.arange(1, 13, dtype=float)
        volumes = np.where(areas <= 6e4, 1e-2 * areas ** 1.2, 1e-2 * 6e4 ** 1.2 * (areas / 6e4) ** 2.0)
        slope, intercept = np.polyfit(np.log(areas), np.log(volumes), 1)
        out = _run([("id_2", float(np.exp(intercept)), float(slope), _table(areas, volumes), {})])
        row = out.loc["id_2"]
        assert row["rms_frac_resid"] > 0.05
        assert row["rms_frac_resid_two_segment"] == pytest.approx(0.0, abs=1e-6)
        assert row["rms_frac_resid_two_segment_upper_volume"] == pytest.approx(0.0, abs=1e-6)

    def test_short_and_partial_tables(self):
        c, b = 1e-2, 1.5
        areas = 1e4 * np.arange(1, 6, dtype=float)
        short = _table(areas, c * areas ** b)
        partial = _table(1e4 * np.arange(1, 11, dtype=float), c * (1e4 * np.arange(1, 11)) ** b)
        out = _run([("id_3", c, b, short, {}),
                    ("id_4", c, b, partial, {"curve_type": "partial", "water_level": 101.0})])
        assert np.isnan(out.loc["id_3", "rms_frac_resid_two_segment"])
        assert out.loc["id_3", "rms_frac_resid"] == pytest.approx(0.0, abs=1e-6)
        assert out.loc["id_4", "n_fit_bins"] == 8
        assert np.isnan(out.loc["id_4", "abs_frac_dev_typical_extent"])
