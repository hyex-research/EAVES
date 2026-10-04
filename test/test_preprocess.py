"""Unit tests for the domain preprocessing helpers.

Covers the segment split (parts sum to the reach, follow the channel, share
their nodes and carry the connectivity), the upstream closure of a river
table and the removal of zero-length reaches. All checks run on small
synthetic networks without touching disk.
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString

from eaves.preprocess import _drop_zero_length_reaches, _split_long_segments, _upstream_closure


def _network() -> gpd.GeoDataFrame:
    """Three reaches in a chain, 3 drains into 2 and 2 into 1, with a bent reach 2."""
    rows = {
        "1": {"lengthm": 1500.0, "unitarea": 12.0, "up1": "2",
              "geometry": LineString([(45.00, 20.00), (45.01, 20.00)])},
        "2": {"lengthm": 5000.0, "unitarea": 30.0, "up1": "3",
              "geometry": LineString([(45.01, 20.00), (45.03, 20.00), (45.03, 20.02)])},
        "3": {"lengthm": 7000.0, "unitarea": 28.0, "up1": "0",
              "geometry": LineString([(45.03, 20.02), (45.09, 20.02)])},
    }
    gdf = gpd.GeoDataFrame.from_dict(rows, orient="index", crs="EPSG:4326")
    gdf["lengthkm"] = gdf["lengthm"] / 1000.0
    for ux in ("up2", "up3", "up4"):
        gdf[ux] = "0"
    return gdf


def _parts(split: gpd.GeoDataFrame, reach: str) -> gpd.GeoDataFrame:
    return split[split.index.str.split("_part").str[0] == reach]


def test_split_parts_sum_to_the_reach():
    gdf = _network()
    split = _split_long_segments(gdf, max_seg_len_m=2000.0)
    assert len(_parts(split, "1")) == 1
    assert len(_parts(split, "2")) == 3
    assert len(_parts(split, "3")) == 4
    for reach in gdf.index:
        parts = _parts(split, reach)
        assert parts["lengthm"].sum() == pytest.approx(gdf.at[reach, "lengthm"])
        assert parts["unitarea"].sum() == pytest.approx(gdf.at[reach, "unitarea"])
        assert np.allclose(parts["lengthkm"], parts["lengthm"] / 1000.0)


def test_split_parts_follow_the_channel():
    gdf = _network()
    split = _split_long_segments(gdf, max_seg_len_m=2000.0)
    parts = _parts(split, "2")
    # The parts of a bent reach rebuild its line, a chord between cut points would cut the corner
    assert sum(g.length for g in parts.geometry) == pytest.approx(gdf.geometry["2"].length)
    assert any(len(g.coords) > 2 for g in parts.geometry)
    assert parts.geometry.iloc[0].coords[0] == pytest.approx(gdf.geometry["2"].coords[0])
    assert parts.geometry.iloc[-1].coords[-1] == pytest.approx(gdf.geometry["2"].coords[-1])
    for lower, upper in zip(parts.geometry.iloc[:-1], parts.geometry.iloc[1:]):
        assert lower.coords[-1] == pytest.approx(upper.coords[0])


def test_split_carries_the_connectivity():
    split = _split_long_segments(_network(), max_seg_len_m=2000.0)
    assert split.at["1", "up1"] == "2_part1"
    assert split.at["2_part1", "up1"] == "2_part2"
    assert split.at["2_part2", "up1"] == "2_part3"
    assert split.at["2_part3", "up1"] == "3_part1"
    assert split.at["3_part4", "up1"] == "0"


def test_upstream_closure_collects_every_reach_that_drains_in():
    gdf = _network()
    assert _upstream_closure(["3"], gdf) == {"3"}
    assert _upstream_closure(["2"], gdf) == {"2", "3"}
    assert _upstream_closure(["1"], gdf) == {"1", "2", "3"}


def test_upstream_closure_stops_on_a_reach_absent_from_the_table():
    gdf = _network().drop(index="3")
    with pytest.raises(ValueError, match="absent from the river table"):
        _upstream_closure(["1"], gdf)


def test_zero_length_reaches_leave_the_table():
    gdf = _network()
    # A closed depression is stored as a reach of zero length that links to itself
    sink = gdf.loc[["3"]].rename(index={"3": "4"}).assign(lengthm=0.0, lengthkm=0.0, up1="4")
    kept = _drop_zero_length_reaches(pd.concat([gdf, sink]))
    assert kept.index.tolist() == gdf.index.tolist()
