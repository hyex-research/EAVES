"""Preprocessing: MERIT-Basins reaches -> country clip -> reach subdivision -> dam snap.

Produces the two geojsons the main EAVES loop consumes from
:mod:`eaves.config.DOMAIN_DIR`:

* ``rivers_split.geojson``: MERIT-Basins reaches that intersect the country
  and every reach upstream of them, with reaches longer than
  ``MAX_SEG_LEN_M`` subdivided along the channel into equal parts and
  ``up1..up4`` adjacency preserved.
* ``dams_snapped.geojson``: dam catalog snapped to a node of the nearest
  reach part within ``MAX_SNAP_DISTANCE_M``, with the
  ``snapped_segment_id``, ``closest_segment_id`` and ``snap_distance_m``
  columns attached. A dam stays above a junction that its crest does not
  reach, unless the site table of the region (``DAM_SITE_VERDICTS``) judges
  that junction, and a dam that the table puts on a stream the reaches do
  not hold stays unsnapped. Where the settings set ``DAM_AT_SITE``, a dam
  snaps only within its crest length and one cell of its reach, and then
  stands at its site on that reach, at which the network of
  ``rivers_split.geojson`` is cut. The EAV
  pipeline reads the two segment IDs back. The catalog arrives cleaned, and
  region-specific curation is left to the caller, with
  ``region/<country>/input/<country>_dams/clean_catalog.py`` as a
  reference implementation.
"""

from __future__ import annotations

import math
import os
from collections import defaultdict

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point
from shapely.geometry import box as shapely_box
from shapely.ops import substring, unary_union

import eaves.config as _cfg

RIVERS_SPLIT_GEOJSON = "rivers_split.geojson"
DAMS_SNAPPED_GEOJSON = "dams_snapped.geojson"
# Verdicts of a site table: the image puts the dam on a stream the reaches do not hold, on the stream of its reach, above the junction below it, at the junction of its reaches, or leaves it open
SITE_VERDICTS = ("off_network", "on_network", "above_junction", "at_junction", "open")
# Verdicts of a site table that decide the junction at a dam in place of its crest length
JUNCTION_VERDICTS = ("above_junction", "at_junction")
# Columns of a site table, in their order
SITE_VERDICT_COLUMNS = ["dam_id", "name", "verdict", "evidence"]
# One cell of the 3 arc-second grid on which MERIT-Basins draws its reaches, the distance by which a reach can pass beside its channel
HYDROGRAPHY_CELL_M = 90.0
# Distance along the reach within which a foot takes a node of the network without a cut, one cell of the grid of the reaches
FOOT_NODE_TOLERANCE_M = 90.0
# Least length in meters of a piece of a cut reach
CUT_END_MIN_M = 1.0
# Where a dam at its site stands: at the junction it takes, at a node of the network near its foot, or at its foot on a cut reach
SITE_KINDS = ("junction", "node", "foot")


# ---- Upstream closure ----
def _upstream_closure(comids, gdf_rivers: gpd.GeoDataFrame) -> set[str]:
    """Return ``comids`` together with every reach of ``gdf_rivers`` that drains into them.

    The closure is walked level by level over the up1..up4 columns, so it stays
    fast on a full MERIT table. A link to a reach absent from the table raises
    ``ValueError``, since the table would then cut a catchment.
    """
    index = gdf_rivers.index.astype(str)
    position = pd.Series(np.arange(len(index)), index=index)
    known = set(index)
    ups = gdf_rivers[["up1", "up2", "up3", "up4"]].astype(str).to_numpy()
    keep = {str(c) for c in comids}
    frontier = keep
    while frontier:
        missing = frontier - known
        if missing:
            raise ValueError(
                f"{len(missing)} reaches are linked but absent from the river table: "
                f"{sorted(missing)[:10]}"
            )
        linked = set(ups[position.loc[list(frontier)].to_numpy()].ravel()) - {"0"}
        frontier = linked - keep
        keep |= frontier
    return keep


# ---- Zero-length reaches ----
def _drop_zero_length_reaches(gdf_rivers: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Return ``gdf_rivers`` without its reaches of zero length.

    The hydrography stores a closed depression whose catchment just reaches the
    channel threshold as a reach of zero length that links to itself. Such a
    reach is a single cell and not a channel, and nothing drains into it.
    """
    return gdf_rivers[gdf_rivers["lengthkm"] > 0].copy()


# ---- Site verdicts ----
def _load_site_verdicts(path: str, registry_ids) -> pd.DataFrame:
    """Return the site verdicts of a region, indexed by ``dam_id``.

    A site table holds one row per dam that a person has looked at on an
    image, with the columns ``SITE_VERDICT_COLUMNS`` in their order. The
    verdict is one of ``SITE_VERDICTS``, and the evidence says in plain words
    what the image shows. ``registry_ids`` are the dam ids of the catalog.

    The function raises ``ValueError`` naming the line of the file on a row
    without evidence, a dam named twice, a verdict outside ``SITE_VERDICTS``
    or a dam the catalog does not hold. It raises one too on columns other
    than ``SITE_VERDICT_COLUMNS``.
    """
    table = pd.read_csv(path, dtype=str, keep_default_na=False)
    if table.columns.tolist() != SITE_VERDICT_COLUMNS:
        raise ValueError(f"{path}: the columns must be {SITE_VERDICT_COLUMNS}, not {table.columns.tolist()}")
    table = table.apply(lambda column: column.str.strip())
    registry = set(pd.Index(registry_ids).astype(str))
    seen = set()
    for i, row in table.iterrows():
        # The header is line 1 of the file and the first row line 2
        where = f"{path}, line {i + 2} ({row['dam_id'] or 'no dam_id'})"
        if row["dam_id"] in seen:
            raise ValueError(f"{where}: the dam is named twice")
        if row["dam_id"] not in registry:
            raise ValueError(f"{where}: the registry does not hold this dam")
        if row["verdict"] not in SITE_VERDICTS:
            raise ValueError(f"{where}: the verdict {row['verdict']!r} is not one of {list(SITE_VERDICTS)}")
        if row["evidence"] == "":
            raise ValueError(f"{where}: the row gives no evidence")
        seen.add(row["dam_id"])
    return table.set_index("dam_id")


# ---- Segment splitting ----
def _reach_parts(lengthm: float, fractions, max_seg_len_m: float) -> list[float]:
    """Return the ends of the parts of a reach cut at ``fractions``, as fractions of the reach from its lower end.

    The reach is cut at each fraction first, and each piece is split into the
    fewest equal parts no longer than ``max_seg_len_m``.
    """
    edges = [0.0, *sorted(fractions), 1.0]
    ends = []
    for lower, upper in zip(edges[:-1], edges[1:]):
        n = max(int(np.ceil((upper - lower) * lengthm / max_seg_len_m)), 1)
        ends.extend(lower + (upper - lower) * j / n for j in range(n))
    return [*ends, 1.0]


def _split_long_segments(gdf_rivers: gpd.GeoDataFrame, max_seg_len_m: float, cuts=None) -> gpd.GeoDataFrame:
    """Split segments longer than ``max_seg_len_m`` and rewire up1..up4.

    ``cuts`` maps a COMID as text to the fractions of the reach, from its
    lower end, at which dams stand. Such a reach is cut there first, and each
    piece is split into equal parts no longer than ``max_seg_len_m``, by
    ``_reach_parts``. Every part carries the share of the reach length and
    unit catchment that its fraction of the reach gives. A reach without cuts
    is split as without ``cuts``.
    """
    gdf_proj = gdf_rivers.to_crs(epsg=3857).copy()
    new_segments = []
    cuts = cuts or {}

    for idx, row in gdf_proj.iterrows():
        geom = row.geometry
        length = row["lengthm"]
        if str(idx) in cuts:
            ends = _reach_parts(length, cuts[str(idx)], max_seg_len_m)
            for i, (lower, upper) in enumerate(zip(ends[:-1], ends[1:])):
                part = row.copy()
                part.geometry = substring(geom, lower, upper, normalized=True)
                part.name = f"{idx}_part{i+1}"
                part["lengthm"] = length * (upper - lower)
                part["lengthkm"] = part["lengthm"] / 1000.0
                part["unitarea"] = row["unitarea"] * (upper - lower)
                links = (f"{idx}_part{i+2}", "0", "0", "0") if i < len(ends) - 2 else tuple(row[ux] for ux in ("up1", "up2", "up3", "up4"))
                part["up1"], part["up2"], part["up3"], part["up4"] = links
                new_segments.append(part)
            continue
        if length <= max_seg_len_m:
            row.name = str(idx)
            new_segments.append(row)
            continue
        num_parts = int(np.ceil(length / max_seg_len_m))
        split_distances = np.linspace(0, 1, num_parts + 1)
        # Each part is the piece of the channel between two cut points and carries an equal share of the reach length and area, and the parts of a reach sum to the reach
        split_lines = [
            substring(geom, split_distances[i], split_distances[i + 1], normalized=True)
            for i in range(num_parts)
        ]
        for i, part_geom in enumerate(split_lines):
            part = row.copy()
            part.geometry = part_geom
            part.name = f"{idx}_part{i+1}"
            part["lengthm"] = length / num_parts
            part["lengthkm"] = part["lengthm"] / 1000.0
            part["unitarea"] = row["unitarea"] / num_parts
            if i < len(split_lines) - 1:
                part["up1"] = f"{idx}_part{i+2}"
                part["up2"] = "0"
                part["up3"] = "0"
                part["up4"] = "0"
            else:
                part["up1"] = row["up1"]
                part["up2"] = row["up2"]
                part["up3"] = row["up3"]
                part["up4"] = row["up4"]
            new_segments.append(part)

    gdf_new = gpd.GeoDataFrame(new_segments, crs=gdf_proj.crs).to_crs(gdf_rivers.crs)

    # Rewires cross-segment references to the first part of each split segment
    split_map: dict[str, list[str]] = {}
    for idx in gdf_new.index:
        if "_part" in str(idx):
            base_id = str(idx).split("_part")[0]
            split_map.setdefault(base_id, []).append(str(idx))
    for base_id in split_map:
        split_map[base_id].sort(key=lambda x: int(x.split("_part")[1]))

    for idx, row in gdf_new.iterrows():
        for ux in ("up1", "up2", "up3", "up4"):
            if ux in gdf_new.columns and pd.notnull(row[ux]):
                up_seg = str(row[ux])
                if up_seg in split_map:
                    gdf_new.at[idx, ux] = split_map[up_seg][0]

    return gdf_new


# ---- Dam snapping ----
def _snap_search_bounds_wgs84(point: Point, max_snap_distance_m: float):
    """Bounding box in EPSG:4326 for the spatial-index prefilter, padded by ``max_snap_distance_m``.

    The pad converts the distance to degrees at the latitude of the point,
    with the shortest meridian degree and a margin, and the box holds the
    full ground radius.
    """
    lat = float(point.y)
    lat_rad = math.radians(lat)
    pad_ns = 1.02 * max_snap_distance_m / 110_574.0
    pad_ew = 1.02 * max_snap_distance_m / (111_320.0 * max(math.cos(lat_rad), 0.05))
    minx, miny, maxx, maxy = point.bounds
    return (minx - pad_ew, miny - pad_ns, maxx + pad_ew, maxy + pad_ns)


def _local_equidistant_crs(point: Point) -> str:
    """Azimuthal equidistant projection centered on the point, in which distances from it are ground distances in meters."""
    return f"+proj=aeqd +lat_0={point.y} +lon_0={point.x} +datum=WGS84 +units=m +no_defs"


def _snap_dams_to_nearest_segment(
    gdf_dams: gpd.GeoDataFrame,
    gdf_rivers_split: gpd.GeoDataFrame,
    max_snap_distance_m: float,
    off_network=frozenset(),
    junction_verdicts=None,
    details=False,
) -> tuple[gpd.GeoDataFrame, int]:
    """Snap each dam to a node of the nearest reach part within ``max_snap_distance_m``.

    Distances are measured on the ground, in the azimuthal equidistant
    projection centered on each dam. All input dams are retained. A dam
    within snap distance takes the nearer end of the part nearest the dam,
    recorded as ``closest_segment_id``, which gives the river direction at
    the wall. ``snap_distance_m`` holds the distance to that part wherever a
    part lies within the search window.

    A dam passes a junction only where its crest reaches it. When the nearer
    end of its part is the lower end and another part ends there too, the dam
    takes that junction only within ``dam_length_m``, the crest length of the
    catalog. Otherwise the dam takes the upper end of its part. A part whose
    upper end is the head of a channel has no node above the dam, and a dam
    on it keeps the junction.

    A verdict of an image on the junction decides in place of the crest
    length. ``junction_verdicts`` maps a dam id to its verdict of the site
    table, and only the verdicts of ``JUNCTION_VERDICTS`` act. With
    ``above_junction`` the dam takes the upper end of its part whatever its
    crest, unless the part has no node above the dam. With ``at_junction``
    the dam takes the junction whatever its crest. A verdict whose junction
    the nearer end of the part does not hold changes nothing. Without
    ``junction_verdicts`` the crest length decides every junction.

    The dam stands at the upstream node of the part with the largest
    ``uparea`` at its node, recorded as ``snapped_segment_id``. Where the
    network ends, at the coast, at a sink or at the outlet of a catchment,
    no part lies below the node, and the dam stands at the upstream node of
    the last part.

    Dams outside snap distance and the dams of ``off_network``, the dam ids
    that the site table puts on a stream the reaches do not hold, keep their
    catalog geometry and receive ``snapped_segment_id=None`` and
    ``closest_segment_id=None``. Placement starts at the catalog coordinate
    for every dam and retries from the snapped node where one exists, so
    these dams have a single starting point and run without river direction
    or the stage-4 river-direction retry.

    With ``details`` the output also holds what the site of a dam needs:
    ``line_distance_m``, the distance to the nearest part before rounding,
    ``junction_m``, the distance to a junction at the lower end of that part
    where the snap weighed one, and ``upper_junction``, whether the dam took
    the upper end of its part where two parts above meet.

    Returns (dams_gdf, n_unsnapped).
    """
    river_sindex = gdf_rivers_split.sindex
    crs = gdf_rivers_split.crs if gdf_rivers_split.crs is not None else "EPSG:4326"

    node_to_segments: dict[str, list] = defaultdict(list)
    for seg_id, row in gdf_rivers_split.iterrows():
        start_node = Point(row.geometry.coords[0])
        end_node = Point(row.geometry.coords[-1])
        node_to_segments[start_node.wkt].append((seg_id, True))
        node_to_segments[end_node.wkt].append((seg_id, False))

    snapped_ids, snapped_pts, closest_ids, snap_dists = [], [], [], []
    junction_ms, upper_junctions = [], []
    verdict_of = {} if junction_verdicts is None else {str(d): v for d, v in dict(junction_verdicts).items() if v in JUNCTION_VERDICTS}

    for dam in gdf_dams.itertuples():
        dam_point = dam.geometry
        bounds = _snap_search_bounds_wgs84(dam_point, max_snap_distance_m)
        cand_idx = list(river_sindex.intersection(bounds))
        cand = gdf_rivers_split.iloc[cand_idx]

        junction_ms.append(np.nan); upper_junctions.append(False)
        if cand.empty or str(getattr(dam, "dam_id", "")) in off_network:
            snapped_ids.append(None); snapped_pts.append(None)
            closest_ids.append(None); snap_dists.append(float("nan"))
            continue

        local_crs = _local_equidistant_crs(dam_point)
        dam_m = gpd.GeoSeries([dam_point], crs=crs).to_crs(local_crs).iloc[0]
        cand_m = cand.to_crs(local_crs)
        seg_distances = [(i, dam_m.distance(g)) for i, g in cand_m.geometry.items()]
        closest_seg_id, min_d = min(seg_distances, key=lambda x: x[1])

        if min_d > max_snap_distance_m:
            snapped_ids.append(None); snapped_pts.append(None)
            closest_ids.append(None); snap_dists.append(float(min_d))
            continue

        closest_seg = gdf_rivers_split.loc[closest_seg_id]
        start_node = Point(closest_seg.geometry.coords[0])
        end_node = Point(closest_seg.geometry.coords[-1])
        nodes_m = gpd.GeoSeries([start_node, end_node], crs=crs).to_crs(local_crs)
        closest_point = start_node if dam_m.distance(nodes_m.iloc[0]) < dam_m.distance(nodes_m.iloc[1]) else end_node
        # A dam stands above a junction at the lower end of its part unless its crest reaches that junction or no node lies above it, and a verdict on the junction decides in place of the crest
        joining = [s for s, at_lower_end in node_to_segments[start_node.wkt] if at_lower_end and s != closest_seg_id]
        lines_above = sum(at_lower_end for _, at_lower_end in node_to_segments[end_node.wkt])
        upper_junctions[-1] = closest_point is end_node and lines_above >= 2
        if closest_point is start_node and joining:
            crest_m = pd.to_numeric(getattr(dam, "dam_length_m", np.nan), errors="coerce")
            crest_m = float(crest_m) if pd.notnull(crest_m) else 0.0
            feeds_upper_end = lines_above > 0
            junction_ms[-1] = dam_m.distance(nodes_m.iloc[0])
            passes = junction_ms[-1] <= crest_m or not feeds_upper_end
            verdict = verdict_of.get(str(getattr(dam, "dam_id", "")), "")
            if verdict == "at_junction":
                passes = True
            elif verdict == "above_junction":
                passes = not feeds_upper_end
            if not passes:
                closest_point = end_node

        connected = node_to_segments.get(closest_point.wkt, [])
        conn_ids = [sid for sid, _ in connected]
        upareas = gdf_rivers_split.loc[conn_ids, "uparea"]
        downstream_id = upareas.idxmax()

        snapped_ids.append(downstream_id)
        # The dam stands at the upstream node of its part, which is the nearest node except where the network ends
        snapped_pts.append(Point(gdf_rivers_split.geometry.loc[downstream_id].coords[-1]))
        closest_ids.append(closest_seg_id)
        snap_dists.append(float(min_d))

    out = gdf_dams.copy()
    out["snapped_segment_id"] = snapped_ids
    out["closest_segment_id"] = closest_ids
    out["snap_distance_m"] = [round(d, 1) if np.isfinite(d) else None for d in snap_dists]
    # Uses the snapped node where available and keeps the original point otherwise
    out["geometry"] = [
        sp if sp is not None else g
        for sp, g in zip(snapped_pts, out.geometry)
    ]

    if details:
        out["line_distance_m"] = snap_dists
        out["junction_m"] = junction_ms
        out["upper_junction"] = upper_junctions

    n_unsnapped = int(out["snapped_segment_id"].isna().sum())
    return out.reset_index(drop=True), n_unsnapped


# ---- Dams at their sites ----
def _dam_reach_m(gdf_dams: gpd.GeoDataFrame, max_snap_distance_m: float) -> pd.Series:
    """Return the reach of each dam in meters, its catalog crest length plus ``HYDROGRAPHY_CELL_M``, at most ``max_snap_distance_m``.

    A dam without a positive crest length reaches ``max_snap_distance_m``.
    """
    crest_m = pd.to_numeric(gdf_dams["dam_length_m"], errors="coerce") if "dam_length_m" in gdf_dams.columns else pd.Series(np.nan, index=gdf_dams.index)
    return (crest_m + HYDROGRAPHY_CELL_M).where(crest_m > 0, max_snap_distance_m).clip(upper=max_snap_distance_m)


def _foot_fraction(point: Point, line) -> float:
    """Return the foot of ``point`` on ``line``, both in EPSG:4326, as a fraction of the line in EPSG:3857 from its lower end.

    The foot is the point of the line nearest the point on the ground, in the
    azimuthal equidistant projection centered on the point. The fraction is
    measured in EPSG:3857, the projection in which the split cuts the reaches.
    """
    local_crs = _local_equidistant_crs(point)
    line_m = gpd.GeoSeries([line], crs="EPSG:4326").to_crs(local_crs).iloc[0]
    foot_m = line_m.interpolate(line_m.project(Point(0.0, 0.0)))
    foot, line_3857 = gpd.GeoSeries([foot_m], crs=local_crs).to_crs(epsg=3857).iloc[0], gpd.GeoSeries([line], crs="EPSG:4326").to_crs(epsg=3857).iloc[0]
    return float(line_3857.project(foot, normalized=True))


def _reach_part_names(reach: str, gdf_network: gpd.GeoDataFrame) -> list[str]:
    """Return the names of the parts of a reach in a network, from its lower end."""
    if reach in gdf_network.index:
        return [reach]
    n = int((pd.Index(gdf_network.index.astype(str)).str.split("_part").str[0] == reach).sum())
    return [f"{reach}_part{k}" for k in range(1, n + 1)]


def _dam_sites(
    gdf_snapped: gpd.GeoDataFrame,
    gdf_points: gpd.GeoSeries,
    gdf_reaches: gpd.GeoDataFrame,
    gdf_rivers_split: gpd.GeoDataFrame,
    junction_verdicts=None,
) -> pd.DataFrame:
    """Return the site of every snapped dam on its reach, with the columns ``site``, ``reach`` and ``fraction``.

    ``gdf_snapped`` is the snap with ``details``, ``gdf_points`` the catalog
    points of the same rows, ``gdf_reaches`` the reaches before the split,
    indexed by COMID as text, and ``gdf_rivers_split`` the network of the
    snap. The reach of a dam is that of its part. The fraction of a site is
    measured from the lower end of the reach. The site is the first of these:

    - ``junction``: the snap weighed a junction at the lower end of the part
      and the dam takes it, by the verdict ``at_junction``, or by its crest
      where the verdict is not ``above_junction``. A dam whose verdict
      ``at_junction`` took the upper end of its part where two parts above
      meet stands at that junction.
    - ``node``: the foot, the point of the reach nearest the catalog point,
      lies within ``FOOT_NODE_TOLERANCE_M`` along the reach of a node of the
      network: a node between two parts, the upper end of a reach with links,
      or a lower end where one part continues and no other part ends. A node
      goes to the dam with the nearer foot, and a junction site holds its node.
    - ``foot``: the reach is cut at the foot, held ``CUT_END_MIN_M`` from
      each end of the reach.

    A dam that the snap put at the head of a channel, on a part without
    links, takes its site where its foot lies more than ``CUT_END_MIN_M``
    below that head. A dam whose foot is the head itself has no reach above
    it, so it has no site and is left out of the returned sites.
    """
    verdict_of = {} if junction_verdicts is None else {str(d): v for d, v in dict(junction_verdicts).items() if v in JUNCTION_VERDICTS}
    node_to_segments: dict[str, list] = defaultdict(list)
    for seg_id, geom in gdf_rivers_split.geometry.items():
        node_to_segments[Point(geom.coords[0]).wkt].append((seg_id, True))
        node_to_segments[Point(geom.coords[-1]).wkt].append((seg_id, False))

    def node_key(reach, f, names):
        # A node inside a reach is named by its fraction, and an end of a reach by its point, which the reaches that meet there share
        if 0.0 < f < 1.0:
            return (reach, f)
        geom = gdf_rivers_split.geometry[names[0] if f == 0.0 else names[-1]]
        return Point(geom.coords[0] if f == 0.0 else geom.coords[-1]).wkt

    def foot_site(i, reach):
        lengthm = float(gdf_reaches.at[reach, "lengthm"])
        end_share = min(CUT_END_MIN_M / lengthm, 0.5)
        return ("foot", reach, float(np.clip(_foot_fraction(gdf_points[i], gdf_reaches.geometry[reach]), end_share, 1.0 - end_share)))

    sites, claims, keys = {}, {}, {}
    for i, dam in gdf_snapped[gdf_snapped["snapped_segment_id"].notna()].iterrows():
        reach = str(dam["closest_segment_id"]).split("_part")[0]
        names = _reach_part_names(reach, gdf_rivers_split)
        verdict = verdict_of.get(str(dam.get("dam_id", "")), "")
        crest_m = pd.to_numeric(dam.get("dam_length_m", np.nan), errors="coerce")
        crest_m = float(crest_m) if pd.notnull(crest_m) else 0.0
        if pd.notna(dam["junction_m"]) and (verdict == "at_junction" or (verdict != "above_junction" and dam["junction_m"] <= crest_m)):
            sites[i] = ("junction", reach, 0.0)
            claims[node_key(reach, 0.0, names)] = (-1.0, i)
            continue
        if verdict == "at_junction" and dam["upper_junction"]:
            sites[i] = ("junction", reach, 1.0)
            claims[node_key(reach, 1.0, names)] = (-1.0, i)
            continue
        lengthm = float(gdf_reaches.at[reach, "lengthm"])
        fraction = _foot_fraction(gdf_points[i], gdf_reaches.geometry[reach])
        # A dam at the head of a channel whose foot is that head has no piece of the reach above it
        at_head = all(str(gdf_rivers_split.at[dam["snapped_segment_id"], ux]) in ("0", "nan", "None", "") for ux in ("up1", "up2", "up3", "up4"))
        if at_head and (1.0 - fraction) * lengthm <= CUT_END_MIN_M:
            continue
        nodes = [k / len(names) for k in range(1, len(names))]
        if any(str(gdf_reaches.at[reach, ux]) not in ("0", "nan", "None", "") for ux in ("up1", "up2", "up3", "up4")):
            nodes.append(1.0)
        at_lower = node_to_segments[Point(gdf_rivers_split.geometry[names[0]].coords[0]).wkt]
        if sum(not lower for _, lower in at_lower) == 1 and sum(lower for _, lower in at_lower) == 1:
            nodes.append(0.0)
        along, f = min(((abs(fraction - f) * lengthm, f) for f in nodes), default=(np.inf, None))
        if along <= FOOT_NODE_TOLERANCE_M:
            sites[i], keys[i] = ("node", reach, f), node_key(reach, f, names)
            if along < claims.get(keys[i], (np.inf, None))[0]:
                claims[keys[i]] = (along, i)
            continue
        sites[i] = foot_site(i, reach)

    # A dam that loses its node to a nearer foot or to a junction stands at its own foot
    for i, key in keys.items():
        if claims[key][1] != i:
            sites[i] = foot_site(i, sites[i][1])
    return pd.DataFrame.from_dict(sites, orient="index", columns=["site", "reach", "fraction"])


def _site_cuts(sites: pd.DataFrame, gdf_reaches: gpd.GeoDataFrame) -> dict[str, list[float]]:
    """Return the fractions at which each reach is cut, the sites inside the reach, two sites closer than ``CUT_END_MIN_M`` making one cut."""
    cuts = {}
    inner = sites[(sites["fraction"] > 0.0) & (sites["fraction"] < 1.0)]
    for reach, fractions in inner.groupby("reach")["fraction"]:
        lengthm = float(gdf_reaches.at[reach, "lengthm"])
        kept = []
        for f in sorted(set(fractions)):
            if not kept or (f - kept[-1]) * lengthm >= CUT_END_MIN_M:
                kept.append(f)
        cuts[reach] = kept
    return cuts


def _place_dams_at_sites(gdf_snapped: gpd.GeoDataFrame, sites: pd.DataFrame, gdf_network: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Return ``gdf_snapped`` with every dam of ``sites`` on the cut network ``gdf_network``.

    A dam stands at the upper end of the part below its site, recorded as
    ``snapped_segment_id``. A site inside a reach takes the part of the reach
    whose upper end lies nearest its fraction, which is the part that ends at
    its cut. A site at the upper end of a reach takes the top part of that
    reach. A site at the lower end of a reach takes, among the parts that
    meet there, the part with the largest ``uparea``, as the snap does.
    ``closest_segment_id``, which gives the river direction at the wall,
    becomes the COMID of the dam's reach, whose parts the direction reads
    joined, since a part of the cut network ends at the wall.
    """
    node_to_segments: dict[str, list] = defaultdict(list)
    for seg_id, geom in gdf_network.geometry.items():
        node_to_segments[Point(geom.coords[0]).wkt].append(seg_id)
        node_to_segments[Point(geom.coords[-1]).wkt].append(seg_id)
    segments = {}
    for i, (_, reach, f) in sites.iterrows():
        names = _reach_part_names(reach, gdf_network)
        if f <= 0.0:
            meeting = node_to_segments[Point(gdf_network.geometry[names[0]].coords[0]).wkt]
            segments[i] = gdf_network.loc[meeting, "uparea"].idxmax()
        elif f >= 1.0:
            segments[i] = names[-1]
        else:
            # The fractions of the upper ends of the parts follow from their lengths, which the split gives as shares of the reach
            shares = gdf_network.loc[names, "lengthm"].to_numpy() / gdf_network.loc[names, "lengthm"].sum()
            segments[i] = names[int(np.argmin(np.abs(np.cumsum(shares)[:-1] - f)))]
    out = gdf_snapped.copy()
    rows = list(segments)
    out.loc[rows, "snapped_segment_id"] = [segments[i] for i in rows]
    out.loc[rows, "closest_segment_id"] = sites.loc[rows, "reach"].to_numpy()
    out["geometry"] = [Point(gdf_network.geometry[segments[i]].coords[-1]) if i in segments else g for i, g in zip(out.index, out.geometry)]
    return out


def _dams_at_sites(
    gdf_snapped: gpd.GeoDataFrame,
    gdf_points: gpd.GeoSeries,
    gdf_reaches: gpd.GeoDataFrame,
    gdf_rivers_split: gpd.GeoDataFrame,
    max_seg_len_m: float,
    max_snap_distance_m: float,
    junction_verdicts=None,
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, pd.DataFrame, int]:
    """Return the dams at their sites, the network cut at the sites, the sites and the count of dams beyond their reach.

    ``gdf_snapped`` is the snap with ``details`` on ``gdf_rivers_split``. A dam
    whose nearest part lies beyond its reach, ``_dam_reach_m``, stays
    unsnapped, without river direction or snapped node, since no reach of the
    network passes its wall. A dam at the head of a channel whose foot is that
    head has no site and stays unsnapped too. Every other snapped dam stands
    at its site, ``_dam_sites``, on the network that ``_split_long_segments``
    cuts at the sites. The output holds the columns of the snap without its
    details.
    """
    out = gdf_snapped.copy()
    beyond = out["snapped_segment_id"].notna() & (out["line_distance_m"] > _dam_reach_m(out, max_snap_distance_m))
    out.loc[beyond, ["snapped_segment_id", "closest_segment_id"]] = None
    out["geometry"] = [p if b else g for b, p, g in zip(beyond, gdf_points, out.geometry)]
    sites = _dam_sites(out, gdf_points, gdf_reaches, gdf_rivers_split, junction_verdicts=junction_verdicts)
    no_site = out["snapped_segment_id"].notna() & ~out.index.isin(sites.index)
    out.loc[no_site, ["snapped_segment_id", "closest_segment_id"]] = None
    out["geometry"] = [p if n else g for n, p, g in zip(no_site, gdf_points, out.geometry)]
    network = _split_long_segments(gdf_reaches, max_seg_len_m=max_seg_len_m, cuts=_site_cuts(sites, gdf_reaches))
    placed = _place_dams_at_sites(out, sites, network)
    return placed.drop(columns=["line_distance_m", "junction_m", "upper_junction"]), network, sites, int(beyond.sum())


# ---- Orchestrator ----
def ensure_inputs(rebuild: bool = False) -> tuple[str, str]:
    """Build (or load from cache) the preprocessed rivers + snapped dams.

    Returns (rivers_split_path, dams_snapped_path). On repeat runs with
    ``rebuild=False``, simply returns the cached paths.
    """
    os.makedirs(_cfg.DOMAIN_DIR, exist_ok=True)
    rivers_path = os.path.join(_cfg.DOMAIN_DIR, RIVERS_SPLIT_GEOJSON)
    dams_path = os.path.join(_cfg.DOMAIN_DIR, DAMS_SNAPPED_GEOJSON)

    if not rebuild and os.path.isfile(rivers_path) and os.path.isfile(dams_path):
        print(f"[preprocess] Using cached inputs in {_cfg.DOMAIN_DIR}/")
        return rivers_path, dams_path

    print("[preprocess] Building domain inputs...")

    # ---- Country mask ----
    print(f"  Loading country shapefile -> filtering to {_cfg.TARGET_COUNTRY}...")
    gdf_country = gpd.read_file(_cfg.COUNTRY_SHP)
    gdf_country = gdf_country[gdf_country[_cfg.COUNTRY_NAME_COL] == _cfg.TARGET_COUNTRY]
    if gdf_country.empty:
        raise ValueError(
            f"No feature matched {_cfg.COUNTRY_NAME_COL}={_cfg.TARGET_COUNTRY!r} "
            f"in {_cfg.COUNTRY_SHP}"
        )
    gdf_country = gdf_country.to_crs(epsg=4326)
    country_geom = gdf_country.geometry.union_all()

    # ---- MERIT-Basins reach clip ----
    print("  Loading MERIT-Basins reaches (this can take a minute)...")
    gdf_rivers = gpd.read_file(_cfg.MERIT_RIVERS_SHP).set_crs(epsg=4326)
    gdf_rivers["COMID"] = gdf_rivers["COMID"].astype(str)
    gdf_rivers = gdf_rivers.set_index("COMID")
    gdf_rivers[["up1", "up2", "up3", "up4"]] = (
        gdf_rivers[["up1", "up2", "up3", "up4"]].fillna(0).astype(int).astype(str)
    )
    gdf_rivers = gdf_rivers.drop(columns=["NextDownID"], errors="ignore")
    n_reaches = len(gdf_rivers)
    gdf_rivers = _drop_zero_length_reaches(gdf_rivers)
    print(f"    Dropped {n_reaches - len(gdf_rivers)} zero-length reaches.")

    print("  Loading MERIT-Basins unit catchments...")
    gdf_basins = gpd.read_file(_cfg.MERIT_BASINS_SHP).set_crs(epsg=4326)
    gdf_basins["COMID"] = gdf_basins["COMID"].astype(str)
    gdf_basins = gdf_basins.set_index("COMID")
    gdf_rivers["unitarea"] = gdf_basins["unitarea"].reindex(gdf_rivers.index)

    print("  Clipping rivers to country...")
    inside = gdf_rivers.index[gdf_rivers.geometry.intersects(country_geom)]
    # A reach that touches the country keeps every reach that drains into it, the channel of a dam next to the border included
    keep = _upstream_closure(inside, gdf_rivers)
    print(f"    {len(inside)} reaches touch the country, {len(keep) - len(inside)} more drain into them from outside.")
    gdf_rivers_sub = gdf_rivers[gdf_rivers.index.isin(keep)].copy()
    gdf_rivers_sub["lengthm"] = gdf_rivers_sub["lengthkm"] * 1000.0

    # ---- Dam catalog ----
    print(f"  Loading dam catalog from {_cfg.DAMS_CSV}...")
    df_dams = pd.read_csv(_cfg.DAMS_CSV)
    print(f"    {len(df_dams)} dams (catalog assumed pre-cleaned).")
    off_network = set()
    junction_verdicts = None
    verdicts_path = _cfg.DAM_SITE_VERDICTS
    if verdicts_path:
        verdicts = _load_site_verdicts(verdicts_path, df_dams["dam_id"])
        off_network = set(verdicts.index[verdicts["verdict"] == "off_network"])
        junction_verdicts = verdicts["verdict"]
        n_junction = int(verdicts["verdict"].isin(JUNCTION_VERDICTS).sum())
        print(f"    {len(verdicts)} site verdicts, {len(off_network)} dams on a stream the reaches do not hold stay unsnapped, "
              f"{n_junction} verdicts decide the junction at their dam.")

    buf = _cfg.DAM_BBOX_BUFFER_DEG
    dam_mask = unary_union([
        shapely_box(lon - buf, lat - buf, lon + buf, lat + buf)
        for lon, lat in zip(df_dams["longitude"], df_dams["latitude"])
    ])
    print(f"  Clipping rivers to {buf:.2f}° bbox around {len(df_dams)} dams...")
    n_before_box = len(gdf_rivers_sub)
    gdf_rivers_sub = gdf_rivers_sub[gdf_rivers_sub.geometry.intersects(dam_mask)].copy()
    print(f"    {n_before_box} -> {len(gdf_rivers_sub)} segments after dam-bbox clip.")

    print(f"  Splitting segments longer than {_cfg.MAX_SEG_LEN_M:.0f} m...")
    gdf_split = _split_long_segments(gdf_rivers_sub, max_seg_len_m=_cfg.MAX_SEG_LEN_M)
    print(f"    {len(gdf_rivers_sub)} -> {len(gdf_split)} segments after split.")

    # ---- Snap ----
    gdf_dams = gpd.GeoDataFrame(
        df_dams,
        geometry=gpd.points_from_xy(df_dams["longitude"], df_dams["latitude"]),
        crs="EPSG:4326",
    )
    print(f"  Snapping {len(gdf_dams)} dams to nearest segment "
          f"(max {_cfg.MAX_SNAP_DISTANCE_M:.0f} m)...")
    gdf_snapped, n_unsnapped = _snap_dams_to_nearest_segment(
        gdf_dams, gdf_split, max_snap_distance_m=_cfg.MAX_SNAP_DISTANCE_M, off_network=off_network,
        junction_verdicts=junction_verdicts, details=_cfg.DAM_AT_SITE,
    )
    if _cfg.DAM_AT_SITE:
        # A dam stands only where a reach passes within its crest and one cell, and then at its site on that reach, which the network is cut at
        n_first = int(gdf_snapped["snapped_segment_id"].notna().sum())
        gdf_snapped, gdf_split, sites, n_beyond = _dams_at_sites(
            gdf_snapped, gdf_dams.geometry, gdf_rivers_sub, gdf_split, _cfg.MAX_SEG_LEN_M, _cfg.MAX_SNAP_DISTANCE_M,
            junction_verdicts=junction_verdicts,
        )
        n_unsnapped = int(gdf_snapped["snapped_segment_id"].isna().sum())
        counts = sites["site"].value_counts().reindex(SITE_KINDS, fill_value=0)
        print(f"    {n_beyond} dams whose nearest reach lies beyond their crest and one cell stay unsnapped, "
              f"and {n_first - n_beyond - len(sites)} whose foot is the head of their channel. "
              f"The others stand at a junction ({counts['junction']}), at a node near their foot ({counts['node']}) "
              f"or at their foot on a cut reach ({counts['foot']}), {len(gdf_split)} segments.")
    n_snapped = len(gdf_snapped) - n_unsnapped
    reasons = f"farther than {_cfg.MAX_SNAP_DISTANCE_M:.0f} m from the nearest MERIT-Basins reach or on a stream it does not hold"
    if _cfg.DAM_AT_SITE:
        reasons += ", beyond their crest and one cell from their reach or with their foot at the head of their channel"
    print(f"    {n_snapped} snapped, {n_unsnapped} kept on catalog coords ({reasons}, stage-4 retry skipped).")

    # GeoJSON drops custom indices. The reset keeps the segment ID in the "index" column read downstream
    gdf_split_out = gdf_split.reset_index()
    gdf_split_out.to_file(rivers_path, driver="GeoJSON")
    gdf_snapped.to_file(dams_path, driver="GeoJSON")

    print(f"[preprocess] Wrote:\n  {rivers_path}\n  {dams_path}")
    return rivers_path, dams_path
