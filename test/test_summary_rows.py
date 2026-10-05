"""Unit tests for the summary rows of dams without a flood fill.

Covers the row that a failed dam gains in the summary, the integer columns of
the written table, the selection of the dams with a fill that every reader of
the summary applies, and the column order of the external attributes on a
second pass.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from eaves.cli import _append_dams_without_fill, _finalize_summary
from eaves.postprocess.external_data import add_sedimentation_columns
from eaves.utils import dams_with_fill


def _fill_rows():
    return pd.DataFrame({
        "dam_id": ["id_b", "id_a"],
        "dam_name": ["B", "A"],
        "construction_year": [2005.0, np.nan],
        "dam_height_m": [12.0, 9.5],
        "spillway_height_m": [10.0, 7.0],
        "dam_length_m": [150.0, 80.0],
        "capacity_mcm": [1.5, 0.25],
        "n_pixels": [120, 40],
        "capped": [True, False],
        "valley_width_m": [300.25, 150.5],
        "valley_ratio": [30.02, 21.5],
        "channel_slope": [0.012, 0.0045],
        "mean_catchment_slope": [0.08, 0.11],
        "upstream_area_km2": [42.5, 7.25],
        "lat": [20.123456, 21.5],
        "lon": [41.0, 42.25],
        "quality": ["A", "D"],
        "uncertainty_score": [0, 2],
    })


def _failure(dam_id="id_c"):
    return {
        "dam_id": dam_id, "dam_name": "C", "reason": "placement_failed", "detail": "no valid flood fill",
        "capacity_mcm": 0.11, "dam_height_m": 8.0, "spillway_height_m": 6.0, "dam_length_m": 50.0,
        "upstream_area_km2": 20.41, "construction_year": 1982.0, "latitude": 25.195278, "longitude": 45.277333,
        "valley_width_m": 764.54, "valley_ratio": 127.42, "channel_slope": 0.01328, "mean_catchment_slope": 0.05302,
    }


class TestRowOfAFailedDam:

    def test_failed_dam_gains_a_row_with_its_attributes(self):
        out = _append_dams_without_fill(_fill_rows(), [_failure()])
        assert list(out.columns) == list(_fill_rows().columns)
        assert list(out["dam_id"]) == ["id_b", "id_a", "id_c"]
        row = out.iloc[2]
        assert (row["capacity_mcm"], row["upstream_area_km2"], row["valley_width_m"]) == (0.11, 20.41, 764.54)
        assert (row["lat"], row["lon"]) == (25.195278, 45.277333)
        assert pd.isna(row["n_pixels"]) and pd.isna(row["quality"]) and pd.isna(row["capped"])

    def test_dam_with_a_fill_keeps_its_one_row(self):
        # A dam with a fill and a failed fit sits in both lists
        out = _append_dams_without_fill(_fill_rows(), [_failure("id_a"), _failure("id_c"), _failure("id_c")])
        assert list(out["dam_id"]) == ["id_b", "id_a", "id_c"]

    def test_written_table_keeps_integers_and_blanks(self, tmp_path):
        path = tmp_path / "eaves_summary.csv"
        _finalize_summary(_append_dams_without_fill(_fill_rows(), [_failure()])).to_csv(path, index=False)
        text = pd.read_csv(path, dtype=str, keep_default_na=False)
        assert list(text["dam_id"]) == ["id_a", "id_b", "id_c"]
        assert list(text["n_pixels"]) == ["40", "120", ""]
        assert list(text["uncertainty_score"]) == ["2", "0", ""]
        assert list(text["capped"]) == ["False", "True", ""]
        assert list(text["construction_year"]) == ["", "2005", "1982"]


class TestDamsWithFill:

    def test_summary_reads_back_as_a_table_of_fills(self, tmp_path):
        all_path, fill_path = tmp_path / "all.csv", tmp_path / "fills.csv"
        _finalize_summary(_append_dams_without_fill(_fill_rows(), [_failure()])).to_csv(all_path, index=False)
        _finalize_summary(_fill_rows()).to_csv(fill_path, index=False)
        # The lines of the dams with a fill are the same text, and the selection restores the column types of a table of fills alone
        assert [line for line in all_path.read_text().splitlines() if not line.startswith("id_c")] == fill_path.read_text().splitlines()
        pd.testing.assert_frame_equal(dams_with_fill(pd.read_csv(all_path)), pd.read_csv(fill_path))

    def test_table_without_a_pixel_count_passes_unchanged(self):
        df = pd.DataFrame({"dam_id": ["id_x", "id_y"]})
        assert dams_with_fill(df) is df


class TestExternalColumns:

    def test_second_pass_keeps_the_column_order(self, tmp_path):
        (tmp_path / "sedimentation_yield.csv").write_text("dam_id,sed_yield_t_ha_yr\nid_a,2.5\nid_b,0.75\n")
        (tmp_path / "owe_annual_mean.csv").write_text("dam_id,owe_mm_year\nid_a,2400.5\n")
        first = add_sedimentation_columns(_fill_rows(), str(tmp_path))
        assert list(first.columns) == list(_fill_rows().columns) + ["sed_yield_t_ha_yr", "owe_mm_year"]
        # The report step appends its columns after these two, and a later pass leaves every column in place
        first["sediment_risk"] = "low"
        second = add_sedimentation_columns(first, str(tmp_path))
        assert list(second.columns) == list(first.columns)
        pd.testing.assert_frame_equal(second, first)
