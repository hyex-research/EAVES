"""Unit tests for the domain preprocessing helpers.

Covers the segment split (parts sum to the reach, follow the channel, share
their nodes and carry the connectivity), the upstream closure of a river
table and the removal of zero-length reaches. The snap holds the junction
rule, the node where the network ends, the ground distance and the full
search radius, the verdicts on a junction, and leaves unsnapped a dam that
the site table puts on a stream the reaches do not hold. With the dams at
their sites, a dam snaps only within its crest and one cell, stands at its
junction, at a node near its foot or at its foot on a cut reach, and the
river direction reads the whole reach. The site table stops on any row it
cannot vouch for. The snap checks run on small synthetic networks without
touching disk, and the table and preprocessing checks write to a temporary
folder.
"""

from __future__ import annotations

import math

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from pyproj import Geod
from shapely.geometry import LineString, Point
from shapely.geometry import box as shapely_box

import eaves.config as _cfg
from eaves.pipeline.terrain import get_river_direction_from_segment
from eaves.preprocess import (
    CUT_END_MIN_M,
    HYDROGRAPHY_CELL_M,
    SITE_VERDICT_COLUMNS,
    SITE_VERDICTS,
    _dam_reach_m,
    _dams_at_sites,
    _drop_zero_length_reaches,
    _load_site_verdicts,
    _snap_dams_to_nearest_segment,
    _split_long_segments,
    _upstream_closure,
    ensure_inputs,
)


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
    # The parts of a bent reach rebuild its line, corner included
    assert sum(g.length for g in parts.geometry) == pytest.approx(gdf.geometry["2"].length)
    assert any(len(g.coords) > 2 for g in parts.geometry)
    assert parts.geometry.iloc[0].coords[0] == pytest.approx(gdf.geometry["2"].coords[0])
    assert parts.geometry.iloc[-1].coords[-1] == pytest.approx(gdf.geometry["2"].coords[-1])
    for lower, upper in zip(parts.geometry.iloc[:-1], parts.geometry.iloc[1:], strict=True):
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


def _junction() -> gpd.GeoDataFrame:
    """A stem s below a junction at latitude 20.02, where the feeder f from the north and the headwater tributary g from the east end, with the headwater h above f."""
    lines = {
        "s": LineString([(42.00, 20.00), (42.00, 20.02)]),
        "f": LineString([(42.00, 20.02), (42.00, 20.04)]),
        "h": LineString([(42.00, 20.04), (42.00, 20.06)]),
        "g": LineString([(42.00, 20.02), (42.02, 20.02)]),
    }
    return gpd.GeoDataFrame(
        {"uparea": [180.0, 60.0, 40.0, 100.0], "up1": ["f", "h", "0", "0"], "up2": ["g", "0", "0", "0"], "up3": "0", "up4": "0"},
        geometry=list(lines.values()), index=list(lines), crs="EPSG:4326")


def _dams(points: dict, crest_m=None) -> gpd.GeoDataFrame:
    """Catalog rows at the given points, with the crest length of the catalog where one is given."""
    columns = {"dam_id": list(points)}
    if crest_m is not None:
        columns["dam_length_m"] = crest_m
    return gpd.GeoDataFrame(columns, geometry=[Point(xy) for xy in points.values()], crs="EPSG:4326")


def _snap(dams, rivers, **kwargs) -> gpd.GeoDataFrame:
    return _snap_dams_to_nearest_segment(dams, rivers, max_snap_distance_m=1000.0, **kwargs)[0].set_index("dam_id")


# A dam on f 300 m above the junction, its catalog point 30 m east of the line
ON_THE_FEEDER = (42.00029, 20.0227)


def test_dam_whose_crest_does_not_reach_the_junction_stands_above_it():
    snapped = _snap(_dams({"d": ON_THE_FEEDER}, crest_m=[100.0]), _junction())
    assert snapped.at["d", "snapped_segment_id"] == "f"
    assert snapped.at["d", "closest_segment_id"] == "f"
    assert snapped.geometry["d"].coords[0] == (42.00, 20.04)


def test_dam_whose_crest_reaches_the_junction_takes_both_lines():
    snapped = _snap(_dams({"d": ON_THE_FEEDER}, crest_m=[400.0]), _junction())
    assert snapped.at["d", "snapped_segment_id"] == "s"
    assert snapped.at["d", "closest_segment_id"] == "f"
    assert snapped.geometry["d"].coords[0] == (42.00, 20.02)


def test_dam_without_a_crest_length_stays_above_a_junction_with_a_node_above_it():
    snapped = _snap(_dams({"d": ON_THE_FEEDER}), _junction())
    assert snapped.at["d", "snapped_segment_id"] == "f"


def test_dam_on_a_headwater_line_keeps_the_junction_below_it():
    # The dam stands on g 300 m east of the junction, and the upper end of g is the head of a channel with no node above the dam
    snapped = _snap(_dams({"d": (42.0029, 20.0203)}, crest_m=[100.0]), _junction())
    assert snapped.at["d", "snapped_segment_id"] == "s"
    assert snapped.at["d", "closest_segment_id"] == "g"
    assert snapped.geometry["d"].coords[0] == (42.00, 20.02)


def test_dam_takes_the_lower_end_of_its_line_where_no_other_line_joins():
    # Near the lower end of h, the node where h meets f alone, the dam keeps the nearer end whatever its crest
    snapped = _snap(_dams({"d": (42.00029, 20.0427)}, crest_m=[10.0]), _junction())
    assert snapped.at["d", "snapped_segment_id"] == "f"
    assert snapped.geometry["d"].coords[0] == (42.00, 20.04)


def test_dam_where_the_network_ends_stands_at_the_upstream_node_of_the_last_part():
    # Near the outlet of s no part lies below the node, so the dam stands where the feeders of s join
    snapped = _snap(_dams({"d": (42.00029, 20.0027)}, crest_m=[100.0]), _junction())
    assert snapped.at["d", "snapped_segment_id"] == "s"
    assert snapped.geometry["d"].coords[0] == (42.00, 20.02)


def test_dam_at_the_head_of_a_channel_keeps_its_part_for_the_river_direction():
    snapped = _snap(_dams({"d": (42.00029, 20.0597)}, crest_m=[100.0]), _junction())
    assert snapped.at["d", "snapped_segment_id"] == "h"
    assert snapped.at["d", "closest_segment_id"] == "h"
    assert snapped.geometry["d"].coords[0] == (42.00, 20.06)


def test_dam_off_the_network_keeps_its_catalog_point_without_a_part():
    dams = _dams({"off": ON_THE_FEEDER, "open": ON_THE_FEEDER}, crest_m=[100.0, 100.0])
    out, n_unsnapped = _snap_dams_to_nearest_segment(dams, _junction(), max_snap_distance_m=1000.0, off_network={"off"})
    snapped = out.set_index("dam_id")
    assert n_unsnapped == 1
    assert pd.isna(snapped.at["off", "snapped_segment_id"]) and pd.isna(snapped.at["off", "closest_segment_id"])
    assert snapped.geometry["off"].coords[0] == ON_THE_FEEDER
    assert snapped.at["open", "snapped_segment_id"] == "f"


def test_verdict_above_junction_keeps_the_upper_end_of_the_part_whatever_the_crest():
    snapped = _snap(_dams({"d": ON_THE_FEEDER}, crest_m=[400.0]), _junction(), junction_verdicts={"d": "above_junction"})
    assert snapped.at["d", "snapped_segment_id"] == "f"
    assert snapped.geometry["d"].coords[0] == (42.00, 20.04)


def test_verdict_at_junction_takes_the_junction_whatever_the_crest():
    snapped = _snap(_dams({"d": ON_THE_FEEDER}, crest_m=[100.0]), _junction(), junction_verdicts=pd.Series({"d": "at_junction"}))
    assert snapped.at["d", "snapped_segment_id"] == "s"
    assert snapped.at["d", "closest_segment_id"] == "f"
    assert snapped.geometry["d"].coords[0] == (42.00, 20.02)


@pytest.mark.parametrize("crest_m", [100.0, 400.0])
def test_snap_without_a_verdict_on_the_junction_follows_the_crest(crest_m):
    # A verdict that is not on a junction, or no verdict at all, leaves the crest length to decide
    plain = _snap(_dams({"d": ON_THE_FEEDER}, crest_m=[crest_m]), _junction())
    for verdict in ("on_network", "open"):
        judged = _snap(_dams({"d": ON_THE_FEEDER}, crest_m=[crest_m]), _junction(), junction_verdicts={"d": verdict})
        pd.testing.assert_frame_equal(judged, plain)
    assert plain.at["d", "snapped_segment_id"] == ("f" if crest_m < 300.0 else "s")


@pytest.mark.parametrize("verdict", ["above_junction", "at_junction"])
def test_verdict_on_a_junction_the_network_does_not_hold_changes_nothing(verdict):
    # Near the lower end of h, where h meets f alone, and on s below the node where f and g meet, the nearer end is no junction at the lower end
    for point in ((42.00029, 20.0427), (42.00029, 20.019)):
        dams = _dams({"d": point}, crest_m=[10.0])
        pd.testing.assert_frame_equal(_snap(dams, _junction(), junction_verdicts={"d": verdict}), _snap(dams, _junction()))


def test_verdict_above_junction_on_a_part_without_a_node_above_keeps_the_junction():
    # The dam stands on the headwater part g, so it has no node above it
    snapped = _snap(_dams({"d": (42.0029, 20.0203)}, crest_m=[100.0]), _junction(), junction_verdicts={"d": "above_junction"})
    assert snapped.at["d", "snapped_segment_id"] == "s"
    assert snapped.geometry["d"].coords[0] == (42.00, 20.02)


def test_search_window_holds_the_full_radius_north_and_south():
    # A line 997 m north of the dam on the ground lies within the radius of 1 km
    north_m = 997.0
    line = LineString([(41.99, 20.0 + north_m / 110_574.0 * 1.0001), (42.01, 20.0 + north_m / 110_574.0 * 1.0001)])
    rivers = gpd.GeoDataFrame({"uparea": [50.0], "up1": ["0"], "up2": "0", "up3": "0", "up4": "0"}, geometry=[line], index=["n"], crs="EPSG:4326")
    snapped = _snap(_dams({"d": (42.0, 20.0)}, crest_m=[100.0]), rivers)
    assert snapped.at["d", "closest_segment_id"] == "n"
    assert snapped.at["d", "snap_distance_m"] == pytest.approx(north_m, abs=5.0)


@pytest.mark.parametrize("lat_node", [0.0, 28.0, 60.0])
def test_snap_distance_is_a_ground_distance_at_every_latitude(lat_node):
    # A channel flowing south, two reaches drawn from their downstream to their upstream end, meeting at a node at the given latitude, and a dam 950 m east of that node on the ground
    lon = 36.6
    rivers = gpd.GeoDataFrame(
        {"uparea": [10.0, 20.0], "up1": ["0", "a"], "up2": "0", "up3": "0", "up4": "0"},
        geometry=[LineString([(lon, lat_node), (lon, lat_node + 0.1)]), LineString([(lon, lat_node - 0.1), (lon, lat_node)])],
        index=["a", "b"], crs="EPSG:4326")
    east_m = 950.0
    dam_lon = lon + east_m / (111_320.0 * math.cos(math.radians(lat_node)))
    snapped = _snap(_dams({"d": (dam_lon, lat_node)}), rivers)
    assert snapped.at["d", "snapped_segment_id"] == "b"
    assert abs(snapped.at["d", "snap_distance_m"] - east_m) < 5.0
    assert snapped.geometry["d"].coords[0] == (lon, lat_node)


def _write_site_table(tmp_path, rows, columns=SITE_VERDICT_COLUMNS):
    path = tmp_path / "verdicts.csv"
    pd.DataFrame(rows, columns=columns).to_csv(path, index=False)
    return path


REGISTRY_IDS = ["id_1", "id_2", "id_3"]


def test_site_table_loads_by_dam_id(tmp_path):
    path = _write_site_table(tmp_path, [["id_1", "One", "off_network", "The image shows the pool on a side stream."], ["id_3", "Three", "open", "No image settles it."]])
    verdicts = _load_site_verdicts(path, REGISTRY_IDS)
    assert verdicts.index.tolist() == ["id_1", "id_3"]
    assert verdicts["verdict"].tolist() == ["off_network", "open"]
    assert verdicts.at["id_1", "evidence"] == "The image shows the pool on a side stream."


def test_site_table_takes_the_five_verdicts(tmp_path):
    rows = [[f"id_{i}", f"Dam {i}", verdict, "Seen."] for i, verdict in enumerate(SITE_VERDICTS, start=1)]
    verdicts = _load_site_verdicts(_write_site_table(tmp_path, rows), [row[0] for row in rows])
    assert verdicts["verdict"].tolist() == ["off_network", "on_network", "above_junction", "at_junction", "open"]


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ([["id_1", "One", "open", "Seen."], ["id_2", "Two", "open", " "]], "line 3 \\(id_2\\): the row gives no evidence"),
        ([["id_1", "One", "open", "Seen."], ["id_1", "One", "on_network", "Seen again."]], "line 3 \\(id_1\\): the dam is named twice"),
        ([["id_2", "Two", "maybe", "Seen."]], "line 2 \\(id_2\\): the verdict 'maybe' is not one of"),
        ([["id_1", "One", "open", "Seen."], ["id_9", "Nine", "open", "Seen."]], "line 3 \\(id_9\\): the registry does not hold this dam"),
    ],
    ids=["no_evidence", "named_twice", "unknown_verdict", "not_in_the_registry"],
)
def test_site_table_stops_on_a_row_it_cannot_vouch_for(tmp_path, rows, message):
    with pytest.raises(ValueError, match=message):
        _load_site_verdicts(_write_site_table(tmp_path, rows), REGISTRY_IDS)


def test_site_table_stops_on_columns_out_of_order(tmp_path):
    path = _write_site_table(tmp_path, [["One", "id_1", "open", "Seen."]], columns=["name", "dam_id", "verdict", "evidence"])
    with pytest.raises(ValueError, match="the columns must be"):
        _load_site_verdicts(path, REGISTRY_IDS)


GEOD = Geod(ellps="WGS84")


# ---- Dams at their sites ----
# Longest part of the networks of the site tests, so that a reach of about 2.2 km has three parts
SITE_SEG_LEN_M = 1000.0


def _junction_reaches() -> gpd.GeoDataFrame:
    """The reaches of the junction network before the split, indexed by COMID as text, with their geodesic lengths and unit catchments."""
    reaches = _junction()
    reaches["unitarea"] = [20.0, 20.0, 40.0, 100.0]
    reaches["lengthm"] = [GEOD.geometry_length(g) for g in reaches.geometry]
    reaches["lengthkm"] = reaches["lengthm"] / 1000.0
    return reaches


def _at_sites(points: dict, crest_m, verdicts=None):
    """The dams at their sites on the junction network, with the cut network, the sites by dam id and the count of dams beyond their reach."""
    reaches = _junction_reaches()
    split = _split_long_segments(reaches, max_seg_len_m=SITE_SEG_LEN_M)
    dams = _dams(points, crest_m=crest_m)
    snapped, _ = _snap_dams_to_nearest_segment(dams, split, max_snap_distance_m=1000.0, junction_verdicts=verdicts, details=True)
    placed, network, sites, n_beyond = _dams_at_sites(snapped, dams.geometry, reaches, split, SITE_SEG_LEN_M, 1000.0, junction_verdicts=verdicts)
    sites.index = dams["dam_id"].to_numpy()[sites.index]
    return placed.set_index("dam_id"), network, sites, n_beyond


def _ground_m(a, b) -> float:
    return GEOD.inv(a[0], a[1], b[0], b[1])[2]


def _upper_end(network, segment):
    return network.geometry[segment].coords[-1]


def _east(lon, lat, east_m):
    """The point east_m meters east of (lon, lat) on the ground."""
    x, y, _ = GEOD.fwd(lon, lat, 90.0, east_m)
    return (x, y)


def test_river_direction_of_a_reach_named_by_its_comid_reads_its_parts_joined():
    # A bent reach cut shortly below its corner, and a dam at the cut, where the chord of the part below runs on one side of the dam only
    reach = _network().loc[["2"]]
    split = _split_long_segments(reach, max_seg_len_m=2000.0, cuts={"2": [0.4]}).reset_index()
    whole = reach.reset_index(names="index")
    lon, lat = split.geometry[0].coords[-1]
    joined = get_river_direction_from_segment(split, "2", lon, lat)
    assert joined == pytest.approx(get_river_direction_from_segment(whole, "2", lon, lat))
    assert not np.allclose(joined, get_river_direction_from_segment(split, "2_part1", lon, lat))
    assert get_river_direction_from_segment(split, "9", lon, lat) is None


def test_reach_of_a_dam_is_its_crest_and_one_cell_within_the_snap_distance():
    dams = _dams({"a": (42.0, 20.0), "b": (42.0, 20.0), "c": (42.0, 20.0), "d": (42.0, 20.0)}, crest_m=[100.0, np.nan, 0.0, 2000.0])
    assert _dam_reach_m(dams, 1000.0).tolist() == [100.0 + HYDROGRAPHY_CELL_M, 1000.0, 1000.0, 1000.0]
    assert _dam_reach_m(dams.drop(columns="dam_length_m"), 800.0).tolist() == [800.0] * 4


def test_dam_whose_reach_passes_within_its_crest_and_one_cell_stands_and_one_just_beyond_stays_unsnapped():
    # Two dams beside the middle of f, 10 m inside and 10 m beyond a reach of 190 m
    points = {"inside": _east(42.0, 20.03, 180.0), "beyond": _east(42.0, 20.03, 200.0)}
    placed, _, sites, n_beyond = _at_sites(points, crest_m=[100.0, 100.0])
    assert n_beyond == 1
    assert placed.at["inside", "snapped_segment_id"].startswith("f_part")
    assert pd.isna(placed.at["beyond", "snapped_segment_id"]) and pd.isna(placed.at["beyond", "closest_segment_id"])
    assert placed.geometry["beyond"].coords[0] == pytest.approx(points["beyond"])
    assert placed.at["beyond", "snap_distance_m"] == pytest.approx(200.0, abs=0.2)
    assert sites.index.tolist() == ["inside"]


def test_dam_stands_at_a_node_at_its_foot():
    placed, network, sites, _ = _at_sites({"d": (42.00029, 20.03)}, crest_m=[100.0])
    segment = placed.at["d", "snapped_segment_id"]
    assert sites.at["d", "site"] == "foot"
    assert _ground_m(_upper_end(network, segment), (42.0, 20.03)) < 0.01
    assert placed.geometry["d"].coords[0] == _upper_end(network, segment)
    assert placed.at["d", "closest_segment_id"] == "f"
    above = network.at[segment, "up1"]
    assert above.startswith("f_part") and network.geometry[above].coords[0] == _upper_end(network, segment)
    parts = _parts(network, "f")
    reach = _junction_reaches().loc["f"]
    assert parts["lengthm"].sum() == pytest.approx(reach["lengthm"])
    assert parts["unitarea"].sum() == pytest.approx(reach["unitarea"])
    assert parts["lengthm"].max() <= SITE_SEG_LEN_M


def test_foot_within_the_tolerance_of_a_node_takes_it_without_a_cut_and_one_just_beyond_cuts():
    split = _split_long_segments(_junction_reaches(), max_seg_len_m=SITE_SEG_LEN_M)
    node = split.geometry["f_part1"].coords[-1]
    for north_m, site in ((80.0, "node"), (100.0, "foot")):
        x, y, _ = GEOD.fwd(node[0], node[1], 0.0, north_m)
        placed, network, sites, _ = _at_sites({"d": _east(x, y, 30.0)}, crest_m=[100.0])
        assert sites.at["d", "site"] == site
        if site == "node":
            assert placed.at["d", "snapped_segment_id"] == "f_part1"
            assert placed.geometry["d"].coords[0] == node
            pd.testing.assert_frame_equal(network, split)
        else:
            assert _parts(network, "f")["lengthm"].iloc[0] == pytest.approx(split.at["f_part1", "lengthm"] + north_m, abs=1.0)
            assert _ground_m(placed.geometry["d"].coords[0], (x, y)) < 0.01


def test_foot_near_a_junction_it_does_not_take_is_cut_above_the_junction():
    # The dam stands on f 50 m above the junction with a crest of 10 m, so the junction is no node of the dam
    x, y, _ = GEOD.fwd(42.0, 20.02, 0.0, 50.0)
    placed, network, sites, _ = _at_sites({"d": _east(x, y, 30.0)}, crest_m=[10.0])
    assert sites.at["d", "site"] == "foot"
    assert placed.at["d", "snapped_segment_id"] == "f_part1"
    assert _ground_m(placed.geometry["d"].coords[0], (x, y)) < 0.01


def test_crest_that_reaches_the_junction_takes_it_without_a_cut():
    split = _split_long_segments(_junction_reaches(), max_seg_len_m=SITE_SEG_LEN_M)
    placed, network, sites, _ = _at_sites({"d": ON_THE_FEEDER}, crest_m=[400.0])
    assert sites.at["d", "site"] == "junction"
    assert placed.at["d", "snapped_segment_id"] == "s_part3"
    assert placed.at["d", "closest_segment_id"] == "f"
    assert placed.geometry["d"].coords[0] == _upper_end(split, "s_part3")
    pd.testing.assert_frame_equal(network, split)


def test_verdict_at_junction_takes_the_junction_and_above_junction_takes_the_foot():
    placed, _, sites, _ = _at_sites({"d": ON_THE_FEEDER}, crest_m=[100.0], verdicts={"d": "at_junction"})
    assert (sites.at["d", "site"], placed.at["d", "snapped_segment_id"]) == ("junction", "s_part3")
    placed, network, sites, _ = _at_sites({"d": ON_THE_FEEDER}, crest_m=[400.0], verdicts={"d": "above_junction"})
    assert sites.at["d", "site"] == "foot"
    assert placed.at["d", "snapped_segment_id"] == "f_part1"
    assert _ground_m(placed.geometry["d"].coords[0], (42.0, 20.0227)) < 0.01


def test_verdict_at_junction_at_the_upper_end_takes_the_junction_of_the_parts_above():
    # The dam stands on s 110 m below the node where f and g meet, beyond the tolerance of that node
    split = _split_long_segments(_junction_reaches(), max_seg_len_m=SITE_SEG_LEN_M)
    placed, _, sites, _ = _at_sites({"d": (42.00029, 20.019)}, crest_m=[10.0], verdicts={"d": "at_junction"})
    assert (sites.at["d", "site"], sites.at["d", "fraction"]) == ("junction", 1.0)
    assert placed.at["d", "snapped_segment_id"] == "s_part3"
    assert placed.geometry["d"].coords[0] == _upper_end(split, "s_part3")
    placed, _, sites, _ = _at_sites({"d": (42.00029, 20.019)}, crest_m=[10.0])
    assert sites.at["d", "site"] == "foot"


def test_dam_on_a_headwater_part_whose_crest_misses_the_junction_stands_at_its_foot():
    # The dam stands on g 300 m east of the junction, where the snap keeps the junction since g starts at the head of a channel
    placed, network, sites, _ = _at_sites({"d": (42.0029, 20.0203)}, crest_m=[100.0])
    assert sites.at["d", "site"] == "foot"
    assert placed.at["d", "snapped_segment_id"] == "g_part1"
    assert _ground_m(placed.geometry["d"].coords[0], (42.0029, 20.02)) < 0.01


def test_foot_near_the_head_of_a_channel_is_cut_and_keeps_the_dam():
    placed, network, sites, _ = _at_sites({"d": (42.00029, 20.0597)}, crest_m=[100.0])
    assert sites.at["d", "site"] == "foot"
    segment = placed.at["d", "snapped_segment_id"]
    top = _parts(network, "h").index[-1]
    assert segment != top and network.at[segment, "up1"] == top and network.at[top, "up1"] == "0"
    assert _ground_m(placed.geometry["d"].coords[0], (42.0, 20.0597)) < 0.01


def test_dam_whose_foot_is_the_head_of_its_channel_stays_unsnapped():
    # The catalog point lies 30 m north of the head of the channel of h, so the nearest point of h is its upper end
    placed, network, sites, n_beyond = _at_sites({"d": (42.00029, 20.0603)}, crest_m=[100.0])
    assert n_beyond == 0 and "d" not in sites.index
    assert pd.isna(placed.at["d", "snapped_segment_id"]) and pd.isna(placed.at["d", "closest_segment_id"])
    assert placed.geometry["d"].coords[0] == pytest.approx((42.00029, 20.0603))
    assert _parts(network, "h").index.tolist() == _parts(_split_long_segments(_junction_reaches(), max_seg_len_m=SITE_SEG_LEN_M), "h").index.tolist()


def test_foot_at_the_end_of_the_network_is_held_one_meter_inside_its_reach():
    # The catalog point lies 33 m south of the lower end of s, where the network ends, so the foot is that end and no node
    placed, network, sites, _ = _at_sites({"d": (42.00, 19.9997)}, crest_m=[100.0])
    assert sites.at["d", "site"] == "foot"
    assert placed.at["d", "snapped_segment_id"] == "s_part1"
    assert network.at["s_part1", "lengthm"] == pytest.approx(CUT_END_MIN_M)
    assert _ground_m(placed.geometry["d"].coords[0], (42.00, 20.00)) == pytest.approx(CUT_END_MIN_M, abs=0.05)


def test_node_goes_to_the_dam_with_the_nearer_foot():
    node = _split_long_segments(_junction_reaches(), max_seg_len_m=SITE_SEG_LEN_M).geometry["f_part1"].coords[-1]
    feet = {"near": GEOD.fwd(node[0], node[1], 0.0, 30.0)[:2], "far": GEOD.fwd(node[0], node[1], 180.0, 60.0)[:2]}
    placed, _, sites, _ = _at_sites({d: _east(*xy, 30.0) for d, xy in feet.items()}, crest_m=[100.0, 100.0])
    assert sites.loc[["near", "far"], "site"].tolist() == ["node", "foot"]
    assert placed.geometry["near"].coords[0] == node
    assert _ground_m(placed.geometry["far"].coords[0], feet["far"]) < 0.01


def test_two_dams_on_one_reach_cut_it_in_three_pieces_with_their_own_inlets():
    placed, network, sites, _ = _at_sites({"low": (42.00029, 20.0227), "high": (42.00029, 20.035)}, crest_m=[50.0, 50.0])
    assert sites["site"].tolist() == ["foot", "foot"]
    low, high = placed.at["low", "snapped_segment_id"], placed.at["high", "snapped_segment_id"]
    assert low != high
    assert _ground_m(placed.geometry["low"].coords[0], (42.0, 20.0227)) < 0.01
    assert _ground_m(placed.geometry["high"].coords[0], (42.0, 20.035)) < 0.01
    assert network.at[low, "up1"] != high or network.geometry[high].coords[-1] != network.geometry[low].coords[-1]
    assert network.geometry[network.at[low, "up1"]].coords[0] == network.geometry[low].coords[-1]


def test_split_without_cuts_is_the_split_of_today():
    today = _split_long_segments(_network(), max_seg_len_m=2000.0)
    for cuts in (None, {}, {"9": [0.5]}):
        pd.testing.assert_frame_equal(_split_long_segments(_network(), max_seg_len_m=2000.0, cuts=cuts), today)


def test_cut_reach_is_cut_at_its_sites_first_and_each_piece_split_into_equal_parts_named_along_the_reach():
    gdf = _network()
    split = _split_long_segments(gdf, max_seg_len_m=2000.0, cuts={"3": [0.2], "1": [0.5]})
    parts = _parts(split, "3")
    assert parts.index.tolist() == ["3_part1", "3_part2", "3_part3", "3_part4"]
    assert parts["lengthm"].to_numpy() == pytest.approx([1400.0, 5600.0 / 3, 5600.0 / 3, 5600.0 / 3])
    assert parts["unitarea"].to_numpy() == pytest.approx(gdf.at["3", "unitarea"] * parts["lengthm"].to_numpy() / 7000.0)
    assert parts["up1"].tolist() == ["3_part2", "3_part3", "3_part4", "0"]
    assert split.at["2_part3", "up1"] == "3_part1"
    # A reach short enough to stay whole takes its parts from the cut, and the reach above still links to it by its first part
    assert _parts(split, "1").index.tolist() == ["1_part1", "1_part2"]
    assert split.at["1_part1", "up1"] == "1_part2" and split.at["1_part2", "up1"] == "2_part1"
    for reach in ("1", "3"):
        geoms = _parts(split, reach).geometry
        assert geoms.iloc[0].coords[0] == pytest.approx(gdf.geometry[reach].coords[0])
        assert geoms.iloc[-1].coords[-1] == pytest.approx(gdf.geometry[reach].coords[-1])
        for lower, upper in zip(geoms.iloc[:-1], geoms.iloc[1:], strict=True):
            assert lower.coords[-1] == upper.coords[0]


def _write_inputs(tmp_path, monkeypatch, dam_at_site):
    """Write the junction network, its unit catchments, a country, a catalog and a site table as the files the preprocessing reads, and point the settings at them."""
    reaches = _junction()
    comid = {"s": 1, "f": 2, "h": 3, "g": 4}
    rivers = gpd.GeoDataFrame({
        "COMID": [comid[r] for r in reaches.index],
        "lengthkm": [GEOD.geometry_length(g) / 1000.0 for g in reaches.geometry],
        "uparea": reaches["uparea"].to_numpy(),
        **{ux: [comid.get(v, 0) for v in reaches[ux]] for ux in ("up1", "up2", "up3", "up4")},
        "NextDownID": [0, 1, 2, 1],
    }, geometry=reaches.geometry.to_numpy(), crs="EPSG:4326")
    basins = gpd.GeoDataFrame({"COMID": rivers["COMID"], "unitarea": [20.0, 20.0, 40.0, 100.0]}, geometry=[g.buffer(0.001) for g in reaches.geometry], crs="EPSG:4326")
    country = gpd.GeoDataFrame({"NAME": ["Land"]}, geometry=[shapely_box(41.9, 19.9, 42.1, 20.1)], crs="EPSG:4326")
    # A dam with the verdict at_junction on f, a dam at its foot on h, a dam off the network and a dam 300 m beside f with a crest of 50 m
    catalog = pd.DataFrame({
        "dam_id": ["junction", "foot", "off", "beside"],
        "longitude": [42.00029, 42.00029, 42.00029, _east(42.0, 20.03, 300.0)[0]],
        "latitude": [20.0227, 20.05, 20.0227, 20.03],
        "dam_length_m": [100.0, 100.0, 100.0, 50.0],
    })
    paths = {name: str(tmp_path / f"{name}.geojson") for name in ("rivers", "basins", "country")}
    rivers.to_file(paths["rivers"], driver="GeoJSON")
    basins.to_file(paths["basins"], driver="GeoJSON")
    country.to_file(paths["country"], driver="GeoJSON")
    catalog.to_csv(tmp_path / "dams.csv", index=False)
    table = _write_site_table(tmp_path, [["junction", "Junction", "at_junction", "Seen."], ["off", "Off", "off_network", "Seen."]])
    settings = {"COUNTRY_SHP": paths["country"], "TARGET_COUNTRY": "Land", "COUNTRY_NAME_COL": "NAME", "MERIT_RIVERS_SHP": paths["rivers"],
                "MERIT_BASINS_SHP": paths["basins"], "DAMS_CSV": str(tmp_path / "dams.csv"), "DOMAIN_DIR": str(tmp_path / f"domain_{dam_at_site}"),
                "DAM_SITE_VERDICTS": str(table), "DAM_AT_SITE": dam_at_site,
                "MAX_SEG_LEN_M": SITE_SEG_LEN_M, "MAX_SNAP_DISTANCE_M": 1000.0, "DAM_BBOX_BUFFER_DEG": 0.3}
    for name, value in settings.items():
        monkeypatch.setattr(_cfg, name, value, raising=False)


@pytest.mark.parametrize("dam_at_site", [False, True])
def test_preprocessing_places_the_dams_at_their_sites_with_the_key_and_snaps_as_before_without_it(tmp_path, monkeypatch, dam_at_site):
    _write_inputs(tmp_path, monkeypatch, dam_at_site)
    rivers_path, dams_path = ensure_inputs(rebuild=True)
    rivers = gpd.read_file(rivers_path).set_index("index")
    dams = gpd.read_file(dams_path).set_index("dam_id")
    assert dams.columns.tolist() == ["longitude", "latitude", "dam_length_m", "snapped_segment_id", "closest_segment_id", "snap_distance_m", "geometry"]
    assert pd.isna(dams.at["off", "snapped_segment_id"])
    assert dams.at["junction", "snapped_segment_id"] == "1_part3"
    if dam_at_site:
        assert pd.isna(dams.at["beside", "snapped_segment_id"])
        assert _ground_m(dams.geometry["foot"].coords[0], (42.0, 20.05)) < 0.01
    else:
        assert rivers.index.tolist() == _split_long_segments(_junction_reaches().rename(index={"s": "1", "f": "2", "h": "3", "g": "4"}), max_seg_len_m=SITE_SEG_LEN_M).index.tolist()
        assert dams.at["beside", "snapped_segment_id"].startswith("2_part")
        assert dams.geometry["foot"].coords[0] in [g.coords[-1] for g in rivers.geometry]
        assert _ground_m(dams.geometry["foot"].coords[0], (42.0, 20.05)) > 100.0
    # Every snapped dam stands at the upper end of its segment, a part of the network written beside it
    snapped = dams[dams["snapped_segment_id"].notna()]
    assert snapped["snapped_segment_id"].isin(rivers.index).all()
    assert snapped["closest_segment_id"].isin(rivers.index if not dam_at_site else rivers.index.str.split("_part").str[0]).all()
    assert all(rivers.geometry[s].coords[-1] == pytest.approx(g.coords[0], abs=1e-12) for s, g in zip(snapped["snapped_segment_id"], snapped.geometry, strict=True))
