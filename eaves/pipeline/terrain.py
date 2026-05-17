"""DEM loading, clipping, reprojection, flow direction, and topographic features."""

from __future__ import annotations

import os

import numpy as np
import rasterio
from rasterio.merge import merge as rio_merge
from rasterio.warp import calculate_default_transform, reproject, Resampling
from rasterio.transform import rowcol

import eaves.config as _cfg
from ..utils import srtm_tile_name


# ---------------------------------------------------------------------------
# SRTM tile loading & mosaic
# ---------------------------------------------------------------------------

def load_srtm_tiles(lat, lon, buffer_deg=0.15):
    lat_min = np.floor(lat - buffer_deg)
    lat_max = np.floor(lat + buffer_deg)
    lon_min = np.floor(lon - buffer_deg)
    lon_max = np.floor(lon + buffer_deg)

    datasets = []
    for la in np.arange(lat_min, lat_max + 1):
        for lo in np.arange(lon_min, lon_max + 1):
            name = srtm_tile_name(la, lo)
            path = os.path.join(_cfg.SRTM_DIR, name)
            if not os.path.isfile(path):
                continue
            if name not in _cfg._srtm_cache:
                _cfg._srtm_cache[name] = rasterio.open(path)
            datasets.append(_cfg._srtm_cache[name])

    if not datasets:
        raise FileNotFoundError(
            f"No SRTM tiles found for lat={lat:.2f}, lon={lon:.2f}"
        )

    if len(datasets) == 1:
        src = datasets[0]
        data = src.read(1).astype(np.float32)
        data[data == src.nodata] = np.nan
        return data, src.transform, src.crs
    mosaic, out_transform = rio_merge(datasets)
    data = mosaic[0].astype(np.float32)
    data[data <= -32000] = np.nan
    return data, out_transform, datasets[0].crs


# ---------------------------------------------------------------------------
# DEM clipping & reprojection
# ---------------------------------------------------------------------------

def clip_and_reproject_dem(dem_data, dem_transform, dem_crs,
                           center_lat, center_lon, radius_deg, target_epsg):
    left = center_lon - radius_deg
    right = center_lon + radius_deg
    bottom = center_lat - radius_deg
    top = center_lat + radius_deg

    row_top, col_left = rowcol(dem_transform, left, top)
    row_bot, col_right = rowcol(dem_transform, right, bottom)
    row_min = max(0, min(row_top, row_bot))
    row_max = min(dem_data.shape[0], max(row_top, row_bot) + 1)
    col_min = max(0, min(col_left, col_right))
    col_max = min(dem_data.shape[1], max(col_left, col_right) + 1)

    clip = dem_data[row_min:row_max, col_min:col_max].copy()
    clip_transform = rasterio.transform.from_origin(
        dem_transform.c + col_min * dem_transform.a,
        dem_transform.f + row_min * dem_transform.e,
        abs(dem_transform.a),
        abs(dem_transform.e),
    )

    src_crs = dem_crs
    dst_crs = f"EPSG:{target_epsg}"
    dst_transform, dst_width, dst_height = calculate_default_transform(
        src_crs, dst_crs, clip.shape[1], clip.shape[0],
        left=clip_transform.c,
        bottom=clip_transform.f + clip.shape[0] * clip_transform.e,
        right=clip_transform.c + clip.shape[1] * clip_transform.a,
        top=clip_transform.f,
    )

    dst_data = np.full((dst_height, dst_width), np.nan, dtype=np.float32)
    reproject(
        source=clip,
        destination=dst_data,
        src_transform=clip_transform,
        src_crs=src_crs,
        src_nodata=np.nan,
        dst_transform=dst_transform,
        dst_crs=dst_crs,
        dst_nodata=np.nan,
        resampling=Resampling.bilinear,
    )

    pixel_area = abs(dst_transform.a * dst_transform.e)
    return dst_data, dst_transform, pixel_area, dst_crs


# ---------------------------------------------------------------------------
# Flow direction from river segment geometry
# ---------------------------------------------------------------------------

def get_flow_direction_from_segment(gdf_rivers, segment_id, dam_lon, dam_lat,
                                    smooth_m=500.0):
    mask = gdf_rivers["index"] == segment_id
    if mask.sum() == 0:
        return None
    seg = gdf_rivers.loc[mask].iloc[0]
    line = seg.geometry
    coords = list(line.coords)
    if len(coords) < 2:
        return None

    lat_rad = np.radians(dam_lat)
    m_per_deg_lon = 111320.0 * np.cos(lat_rad)
    m_per_deg_lat = 110540.0

    cum_dist = [0.0]
    for i in range(1, len(coords)):
        dx = (coords[i][0] - coords[i - 1][0]) * m_per_deg_lon
        dy = (coords[i][1] - coords[i - 1][1]) * m_per_deg_lat
        cum_dist.append(cum_dist[-1] + np.hypot(dx, dy))
    total_len = cum_dist[-1]
    cum_dist = np.array(cum_dist)

    dists_to_dam = [np.hypot((c[0] - dam_lon) * m_per_deg_lon,
                             (c[1] - dam_lat) * m_per_deg_lat)
                    for c in coords]
    nearest_idx = int(np.argmin(dists_to_dam))
    dam_s = cum_dist[nearest_idx]

    def _interp(s):
        s = np.clip(s, 0, total_len)
        idx = int(np.searchsorted(cum_dist, s, side="right")) - 1
        idx = np.clip(idx, 0, len(coords) - 2)
        seg_len = cum_dist[idx + 1] - cum_dist[idx]
        frac = (s - cum_dist[idx]) / seg_len if seg_len > 0 else 0.0
        p0 = np.array(coords[idx])
        p1 = np.array(coords[idx + 1])
        return p0 + frac * (p1 - p0)

    s_up = max(dam_s - smooth_m, 0)
    s_dn = min(dam_s + smooth_m, total_len)
    p_up = _interp(s_up)
    p_dn = _interp(s_dn)

    chord = p_dn - p_up
    norm = np.linalg.norm(chord)
    if norm < 1e-12:
        return None
    return chord / norm


def _flood_river_overlay_from_segment(
    gdf_rivers, segment_id, dem_tf, dem_shape, utm_epsg,
    arrow_step_px=40.0,
    arrow_len_px=14.0,
):
    """Project the snapped river LineString into DEM pixel space for QC plots."""
    from pyproj import CRS, Transformer

    sid = str(segment_id).strip()
    if not sid or sid.lower() == "nan" or gdf_rivers is None:
        return None
    mask = gdf_rivers["index"].astype(str) == sid
    if mask.sum() == 0:
        return None
    geom = gdf_rivers.loc[mask].iloc[0].geometry
    if geom is None or geom.is_empty:
        return None
    if geom.geom_type == "MultiLineString":
        geom = max(geom.geoms, key=lambda g: g.length)
    if geom.geom_type != "LineString":
        return None

    crs_gdf = gdf_rivers.crs
    crs_src = CRS.from_user_input(crs_gdf) if crs_gdf is not None else CRS.from_epsg(4326)
    crs_dst = CRS.from_epsg(int(utm_epsg))
    tr = Transformer.from_crs(crs_src, crs_dst, always_xy=True)

    h, w = int(dem_shape[0]), int(dem_shape[1])
    cc, rr = [], []
    for xy in geom.coords:
        lon, lat = float(xy[0]), float(xy[1])
        try:
            xe, yn = tr.transform(lon, lat)
            r, c = rowcol(dem_tf, xe, yn)
        except Exception:
            continue
        if not (np.isfinite(r) and np.isfinite(c)):
            continue
        cc.append(float(c))
        rr.append(float(r))
    if len(cc) < 2:
        return None
    cc = np.asarray(cc, dtype=float)
    rr = np.asarray(rr, dtype=float)

    acx, acy, uc, vr = [], [], [], []
    cum_s = 0.0
    next_mark = float(arrow_step_px)
    for i in range(len(cc) - 1):
        dc = cc[i + 1] - cc[i]
        dr = rr[i + 1] - rr[i]
        seg_len = float(np.hypot(dc, dr))
        if seg_len < 1e-9:
            continue
        ue = dc / seg_len
        ve = dr / seg_len
        while cum_s + seg_len >= next_mark - 1e-9:
            dist_into = next_mark - cum_s
            tt = float(np.clip(dist_into / seg_len, 0.0, 1.0))
            acx.append(cc[i] + tt * dc)
            acy.append(rr[i] + tt * dr)
            uc.append(ue * arrow_len_px)
            vr.append(ve * arrow_len_px)
            next_mark += arrow_step_px
        cum_s += seg_len

    if not acx and len(cc) >= 2:
        dc = cc[-1] - cc[0]
        dr = rr[-1] - rr[0]
        L = float(np.hypot(dc, dr))
        if L > 1e-9:
            acx.append(0.5 * (cc[0] + cc[-1]))
            acy.append(0.5 * (rr[0] + rr[-1]))
            uc.append((dc / L) * arrow_len_px)
            vr.append((dr / L) * arrow_len_px)

    return {
        "line_cc": cc,
        "line_rr": rr,
        "arrow_cc": np.asarray(acx, dtype=float),
        "arrow_rr": np.asarray(acy, dtype=float),
        "arrow_uc": np.asarray(uc, dtype=float),
        "arrow_vr": np.asarray(vr, dtype=float),
    }


# ---------------------------------------------------------------------------
# DEM-gradient downstream direction
# ---------------------------------------------------------------------------

def get_downstream_direction_from_dem(dem, dam_row, dam_col, search_radius=5):
    nrows, ncols = dem.shape
    r0 = max(search_radius, dam_row - search_radius)
    r1 = min(nrows - 1 - search_radius, dam_row + search_radius)
    c0 = max(search_radius, dam_col - search_radius)
    c1 = min(ncols - 1 - search_radius, dam_col + search_radius)

    patch = dem[r0:r1 + 1, c0:c1 + 1]
    if patch.size < 9:
        return np.array([1.0, 0.0])

    grad_row, grad_col = np.gradient(patch)
    center_r = dam_row - r0
    center_c = dam_col - c0

    gr = np.nanmean(grad_row[max(0, center_r - 1):center_r + 2,
                              max(0, center_c - 1):center_c + 2])
    gc = np.nanmean(grad_col[max(0, center_r - 1):center_r + 2,
                              max(0, center_c - 1):center_c + 2])

    downstream = np.array([-gr, -gc])
    norm = np.linalg.norm(downstream)
    if norm < 1e-6:
        return np.array([1.0, 0.0])
    return downstream / norm


# ---------------------------------------------------------------------------
# Topographic feature extraction (for regionalization)
# ---------------------------------------------------------------------------

def compute_valley_width(dem_utm, dam_r, dam_c, spillway_height, dam_elev, pixel_size):
    """Minimum cross-section gap width at spillway level (metres).

    Casts rays at 2-degree intervals from the dam pixel and looks for terrain
    that rises above ``z_spillway`` on both sides. The minimum two-sided gap
    over all angles is the reported valley width.

    When no angle produces a two-sided wall pair within the search radius the
    function returns ``2 * max_search * pixel_size`` -- the full diameter of
    the search window. This is the conservative lower bound for floodplain or
    wide-pan reservoirs where spillway-level terrain is genuinely farther
    away than the search radius and is the right physical answer for those
    sites (rather than the not-a-number sentinel that the old behaviour
    produced and that propagated downstream as a missing feature).
    """
    z_spillway = dam_elev + spillway_height
    nrows, ncols = dem_utm.shape
    max_search = 200

    min_gap_m = float("inf")

    for angle_deg in range(0, 180, 2):
        angle_rad = np.radians(angle_deg)
        wr = np.cos(angle_rad)
        wc = np.sin(angle_rad)

        d_pos, d_neg = None, None
        for d in range(1, max_search + 1):
            r = int(round(dam_r + wr * d))
            c = int(round(dam_c + wc * d))
            if r < 0 or r >= nrows or c < 0 or c >= ncols:
                break
            if not np.isnan(dem_utm[r, c]) and dem_utm[r, c] >= z_spillway:
                d_pos = d
                break

        for d in range(1, max_search + 1):
            r = int(round(dam_r - wr * d))
            c = int(round(dam_c - wc * d))
            if r < 0 or r >= nrows or c < 0 or c >= ncols:
                break
            if not np.isnan(dem_utm[r, c]) and dem_utm[r, c] >= z_spillway:
                d_neg = d
                break

        if d_pos is not None and d_neg is not None:
            gap_m = (d_pos + d_neg) * pixel_size
            min_gap_m = min(min_gap_m, gap_m)

    if min_gap_m == float("inf"):
        return float(2 * max_search * pixel_size)
    return min_gap_m


def compute_channel_slope(dem_utm, dam_r, dam_c, pixel_size, reach_m=1000.0):
    """Thalweg slope over a fixed reach."""
    nrows, ncols = dem_utm.shape
    ds = get_downstream_direction_from_dem(dem_utm, dam_r, dam_c)
    reach_px = int(reach_m / pixel_size)

    up_r = int(np.clip(round(dam_r - ds[0] * reach_px), 0, nrows - 1))
    up_c = int(np.clip(round(dam_c - ds[1] * reach_px), 0, ncols - 1))
    dn_r = int(np.clip(round(dam_r + ds[0] * reach_px), 0, nrows - 1))
    dn_c = int(np.clip(round(dam_c + ds[1] * reach_px), 0, ncols - 1))

    z_up = dem_utm[up_r, up_c]
    z_dn = dem_utm[dn_r, dn_c]

    if np.isnan(z_up) or np.isnan(z_dn):
        patch = dem_utm[max(0, dam_r - 2):dam_r + 3, max(0, dam_c - 2):dam_c + 3]
        if patch.size < 4:
            return np.nan
        gy, gx = np.gradient(patch)
        return float(np.nanmean(np.sqrt(gx**2 + gy**2)))

    dist_m = np.hypot((up_r - dn_r) * pixel_size, (up_c - dn_c) * pixel_size)
    if dist_m < 1.0:
        return np.nan
    return abs(float(z_up) - float(z_dn)) / dist_m


def compute_mean_catchment_slope(dem_utm, dam_r, dam_c, pixel_size, radius_m=2000.0):
    """Mean terrain slope in a circular patch around the dam pixel."""
    radius_px = int(radius_m / pixel_size)
    nrows, ncols = dem_utm.shape

    r0 = max(0, dam_r - radius_px)
    r1 = min(nrows, dam_r + radius_px + 1)
    c0 = max(0, dam_c - radius_px)
    c1 = min(ncols, dam_c + radius_px + 1)

    patch = dem_utm[r0:r1, c0:c1].copy()
    if patch.size < 9:
        return np.nan

    gy, gx = np.gradient(patch, pixel_size)
    slope = np.sqrt(gx**2 + gy**2)

    rows_local = np.arange(patch.shape[0]) - (dam_r - r0)
    cols_local = np.arange(patch.shape[1]) - (dam_c - c0)
    rr, cc = np.meshgrid(rows_local, cols_local, indexing="ij")
    dist_px = np.sqrt(rr**2 + cc**2)
    circle_mask = dist_px <= radius_px

    return float(np.nanmean(slope[circle_mask]))


def _extract_topo_features(dem_utm, dam_r, dam_c, dam_elev, spillway_height, pixel_size):
    """Package topographic features for regionalization."""
    valley_width_m = compute_valley_width(
        dem_utm, dam_r, dam_c, spillway_height, dam_elev, pixel_size,
    )
    valley_ratio = (
        valley_width_m / spillway_height
        if spillway_height > 0 and np.isfinite(valley_width_m)
        else np.nan
    )
    channel_slope = compute_channel_slope(dem_utm, dam_r, dam_c, pixel_size)
    mean_slope = compute_mean_catchment_slope(dem_utm, dam_r, dam_c, pixel_size)
    return {
        "valley_width_m": valley_width_m,
        "valley_ratio": valley_ratio,
        "channel_slope": channel_slope,
        "mean_catchment_slope": mean_slope,
    }
