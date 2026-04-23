"""Preprocessing: MERIT rivers -> country clip -> segment split -> dam snap.

Produces the two geojsons the main EAVES loop consumes from
:mod:`eaves.config.DOMAIN_DIR`:

* ``rivers_split.geojson``  -- country-clipped MERIT rivers with long segments
  split to ``MAX_SEG_LEN_M`` and ``up1..up4`` adjacency preserved.
* ``dams_snapped.geojson``  -- dam catalogue snapped to the nearest river node
  within ``MAX_SNAP_DISTANCE_M``; columns ``snapped_segment_id``,
  ``snap_distance``, ``up1..up4`` are attached. The catalogue is assumed to
  already be cleaned upstream (region-specific curation is left to the
  caller; see ``region/<country>/input/<country>_dams/clean_catalogue.py``
  for a reference implementation).
"""

from __future__ import annotations

import math
import os
from collections import defaultdict

import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point, LineString, box as shapely_box
from shapely.ops import unary_union

import eaves.config as _cfg


RIVERS_SPLIT_GEOJSON = "rivers_split.geojson"
DAMS_SNAPPED_GEOJSON = "dams_snapped.geojson"


# ---------------------------------------------------------------------------
# Segment splitting
# ---------------------------------------------------------------------------
def _split_long_segments(gdf_rivers: gpd.GeoDataFrame, max_seg_len_m: float) -> gpd.GeoDataFrame:
    """Split segments longer than ``max_seg_len_m`` and rewire up1..up4."""
    gdf_proj = gdf_rivers.to_crs(epsg=3857).copy()
    new_segments = []

    for idx, row in gdf_proj.iterrows():
        geom = row.geometry
        length = row["lengthm"]
        if length <= max_seg_len_m:
            row.name = str(idx)
            new_segments.append(row)
            continue
        num_parts = int(np.ceil(length / max_seg_len_m))
        split_distances = np.linspace(0, 1, num_parts + 1)
        split_lines = [
            LineString([
                geom.interpolate(split_distances[i], normalized=True),
                geom.interpolate(split_distances[i + 1], normalized=True),
            ])
            for i in range(num_parts)
        ]
        for i, part_geom in enumerate(split_lines):
            part = row.copy()
            part.geometry = part_geom
            part.name = f"{idx}_part{i+1}"
            part["lengthm"] = part_geom.length
            part["lengthkm"] = part_geom.length / 1000.0
            part["unitarea"] = row["unitarea"] * (part["lengthm"] / length)
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

    # Rewire cross-segment references so downstream parts point to the first
    # part of whatever split-up segment used to be their upstream neighbour.
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


# ---------------------------------------------------------------------------
# Dam snapping
# ---------------------------------------------------------------------------
def _snap_search_bounds_wgs84(point: Point, max_snap_distance_m: float):
    """Metric-padded bounding box around a WGS84 point for spatial-index prefilter."""
    lat = float(point.y)
    lat_rad = math.radians(lat)
    pad_ns = max_snap_distance_m / 111_320.0
    pad_ew = max_snap_distance_m / (111_320.0 * max(math.cos(lat_rad), 0.05))
    minx, miny, maxx, maxy = point.bounds
    return (minx - pad_ew, miny - pad_ns, maxx + pad_ew, maxy + pad_ns)


def _snap_dams_to_nearest_segment(
    gdf_dams: gpd.GeoDataFrame,
    gdf_rivers_split: gpd.GeoDataFrame,
    max_snap_distance_m: float,
) -> tuple[gpd.GeoDataFrame, int]:
    """Snap dams to the nearest river node within ``max_snap_distance_m``.

    All input dams are retained. Dams within snap distance get their geometry
    moved to the closest segment endpoint and ``snapped_segment_id`` / ``up1..up4``
    populated from the downstream segment (largest ``uparea`` at that node).
    Dams outside snap distance keep their catalogue geometry and receive
    ``snapped_segment_id=None`` -- EAVES workers fall back to catalogue
    coordinates and skip the stage-4 river retry for these.

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

    snapped_ids, snapped_pts, snap_d = [], [], []
    up1, up2, up3, up4 = [], [], [], []

    for dam in gdf_dams.itertuples():
        dam_point = dam.geometry
        bounds = _snap_search_bounds_wgs84(dam_point, max_snap_distance_m)
        cand_idx = list(river_sindex.intersection(bounds))
        cand = gdf_rivers_split.iloc[cand_idx]

        if cand.empty:
            snapped_ids.append(None); snapped_pts.append(None); snap_d.append(np.inf)
            up1.append(None); up2.append(None); up3.append(None); up4.append(None)
            continue

        dam_m = gpd.GeoSeries([dam_point], crs=crs).to_crs(3857).iloc[0]
        cand_m = cand.to_crs(3857)
        seg_distances = [(i, dam_m.distance(g)) for i, g in cand_m.geometry.items()]
        closest_seg_id, min_d = min(seg_distances, key=lambda x: x[1])

        if min_d > max_snap_distance_m:
            snapped_ids.append(None); snapped_pts.append(None); snap_d.append(min_d)
            up1.append(None); up2.append(None); up3.append(None); up4.append(None)
            continue

        closest_seg = gdf_rivers_split.loc[closest_seg_id]
        start_node = Point(closest_seg.geometry.coords[0])
        end_node = Point(closest_seg.geometry.coords[-1])
        nodes_m = gpd.GeoSeries([start_node, end_node], crs=crs).to_crs(3857)
        closest_point = start_node if dam_m.distance(nodes_m.iloc[0]) < dam_m.distance(nodes_m.iloc[1]) else end_node

        connected = node_to_segments.get(closest_point.wkt, [])
        conn_ids = [sid for sid, _ in connected]
        upareas = gdf_rivers_split.loc[conn_ids, "uparea"]
        downstream_id = upareas.idxmax()
        downstream_row = gdf_rivers_split.loc[downstream_id]

        snapped_ids.append(downstream_id)
        snapped_pts.append(closest_point)
        snap_d.append(min_d)
        up1.append(str(downstream_row.get("up1")) if pd.notnull(downstream_row.get("up1")) else None)
        up2.append(str(downstream_row.get("up2")) if pd.notnull(downstream_row.get("up2")) else None)
        up3.append(str(downstream_row.get("up3")) if pd.notnull(downstream_row.get("up3")) else None)
        up4.append(str(downstream_row.get("up4")) if pd.notnull(downstream_row.get("up4")) else None)

    out = gdf_dams.copy()
    out["snapped_segment_id"] = snapped_ids
    out["snap_distance"] = snap_d
    out["up1"] = up1
    out["up2"] = up2
    out["up3"] = up3
    out["up4"] = up4
    # Replace catalogue geometry with the snapped node where available; leave
    # the original point intact otherwise so downstream code can still run.
    out["geometry"] = [
        sp if sp is not None else g
        for sp, g in zip(snapped_pts, out.geometry)
    ]

    n_unsnapped = int(out["snapped_segment_id"].isna().sum())
    return out.reset_index(drop=True), n_unsnapped


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------
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

    # --- Country mask ---
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

    # --- MERIT rivers clip ---
    print("  Loading MERIT rivers (this can take a minute)...")
    gdf_rivers = gpd.read_file(_cfg.MERIT_RIVERS_SHP).set_crs(epsg=4326)
    gdf_rivers["COMID"] = gdf_rivers["COMID"].astype(str)
    gdf_rivers = gdf_rivers.set_index("COMID")
    gdf_rivers[["up1", "up2", "up3", "up4"]] = (
        gdf_rivers[["up1", "up2", "up3", "up4"]].fillna(0).astype(int).astype(str)
    )
    gdf_rivers = gdf_rivers.drop(columns=["NextDownID"], errors="ignore")

    print("  Loading MERIT basins...")
    gdf_basins = gpd.read_file(_cfg.MERIT_BASINS_SHP).set_crs(epsg=4326)
    gdf_basins["COMID"] = gdf_basins["COMID"].astype(str)
    gdf_basins = gdf_basins.set_index("COMID")
    gdf_rivers["unitarea"] = gdf_basins["unitarea"].reindex(gdf_rivers.index)

    print("  Clipping rivers to country...")
    gdf_rivers_sub = gdf_rivers[gdf_rivers.geometry.intersects(country_geom)].copy()
    gdf_rivers_sub["lengthm"] = gdf_rivers_sub["lengthkm"] * 1000.0

    # --- Dam catalogue ---
    print(f"  Loading dam catalogue from {_cfg.DAMS_CSV}...")
    df_dams = pd.read_csv(_cfg.DAMS_CSV)
    print(f"    {len(df_dams)} dams (catalogue assumed pre-cleaned).")

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

    # --- Snap ---
    gdf_dams = gpd.GeoDataFrame(
        df_dams,
        geometry=gpd.points_from_xy(df_dams["longitude"], df_dams["latitude"]),
        crs="EPSG:4326",
    )
    print(f"  Snapping {len(gdf_dams)} dams to nearest segment "
          f"(max {_cfg.MAX_SNAP_DISTANCE_M:.0f} m)...")
    gdf_snapped, n_unsnapped = _snap_dams_to_nearest_segment(
        gdf_dams, gdf_split, max_snap_distance_m=_cfg.MAX_SNAP_DISTANCE_M,
    )
    n_snapped = len(gdf_snapped) - n_unsnapped
    print(f"    {n_snapped} snapped; {n_unsnapped} kept on catalogue coords "
          f"(further than {_cfg.MAX_SNAP_DISTANCE_M:.0f} m from MERIT — stage-4 retry skipped).")

    # --- Persist ---
    # GeoJSON doesn't store custom indices; reset to a plain RangeIndex and
    # keep the split-segment ID in a column named "index" (terrain.py and
    # curves.py look up segments via gdf_rivers["index"]).
    gdf_split_out = gdf_split.reset_index()
    gdf_split_out.to_file(rivers_path, driver="GeoJSON")
    gdf_snapped.to_file(dams_path, driver="GeoJSON")

    print(f"[preprocess] Wrote:\n  {rivers_path}\n  {dams_path}")
    return rivers_path, dams_path
