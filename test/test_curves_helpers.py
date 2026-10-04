"""Unit tests for small pure helpers in :mod:`eaves.pipeline.curves` and :mod:`eaves.utils`.

Covers construction-year parsing, which deliberately leaves an unknown year
as ``None`` (never a fabricated sentinel such as 2001), and the precision of
the released tables.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from eaves.pipeline.curves import _parse_construction_year
from eaves.utils import round_released_columns, round_released_value


class TestParseConstructionYear:

    @pytest.mark.parametrize("raw,expected", [
        (2009, 2009),
        (2009.0, 2009),      # pandas hands numeric columns back as float
        ("2009", 2009),
        (1955, 1955),
    ])
    def test_numeric_values_parse_to_int(self, raw, expected):
        assert _parse_construction_year(raw) == expected

    @pytest.mark.parametrize("raw", [
        None,                # genuinely absent
        "",                  # blank cell
        "historical",        # non-numeric catalogue note
        np.nan,              # pandas NaN for a missing numeric cell
        "n/a",
    ])
    def test_missing_or_non_numeric_returns_none(self, raw):
        # Guards against a fabricated sentinel year. The result is None, never 2001
        assert _parse_construction_year(raw) is None

    def test_never_returns_2001_sentinel_for_missing(self):
        for raw in (None, "", np.nan, "historical"):
            assert _parse_construction_year(raw) != 2001


class TestReleasedPrecision:

    def test_capacity_and_exponent_keep_four_decimals(self):
        df = round_released_columns(pd.DataFrame({"capacity_mcm": [0.14080400000000002, 193.644], "b": [1.53381692598004, 2.0]}))
        assert df["capacity_mcm"].tolist() == [0.1408, 193.644]
        assert df["b"].tolist() == [1.5338, 2.0]

    def test_coefficient_keeps_four_significant_digits(self):
        df = round_released_columns(pd.DataFrame({"c": [0.0039059890336142697, 6.971543852124543e-06, 0.977868615812936, np.nan]}))
        assert df["c"].tolist()[:3] == [0.003906, 6.972e-06, 0.9779]
        assert np.isnan(df["c"].iloc[3])

    def test_other_floats_keep_four_significant_digits_and_at_least_two_decimals(self):
        df = round_released_columns(pd.DataFrame({
            "channel_slope": [0.00013384325063176046],
            "valley_width_m": [147.30027877076188],
            "srtm_water_level_m": [2160.0609130859375],
            "area_m2": [861.5534592755366],
            "frac_reliable": [0.8979591836734694],
        }))
        assert df.iloc[0].tolist() == [0.0001338, 147.3, 2160.06, 861.55, 0.898]

    def test_columns_named_after_the_exponent_keep_four_decimals(self):
        df = round_released_columns(pd.DataFrame({"b_reg": [1.4930249], "ref_b": [2.358754], "delta_b": [0.00254]}))
        assert df.iloc[0].tolist() == [1.493, 2.3588, 0.0025]

    def test_catalog_columns_integers_and_text_are_left_alone(self):
        df = pd.DataFrame({
            "lat": [21.82343333], "longitude": [39.24988889], "spillway_height_m": [11.625], "n_pixels": [1234567],
            "dam_id": ["id_000001"], "reason": ["placement_failed"],
        })
        assert round_released_columns(df.copy()).equals(df)

    def test_value_that_is_not_a_float_passes_unchanged(self):
        assert round_released_value("n_dams_summary", 503) == 503
        assert round_released_value("region", "Saudi Arabia") == "Saudi Arabia"
        assert round_released_value("loglog_alpha", -0.5603660846218309) == -0.5604
        assert round_released_value("b_p84", 1.7776640000000001) == 1.7777
