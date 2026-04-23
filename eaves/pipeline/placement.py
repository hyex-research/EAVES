"""Dam wall placement, flood fill, upstream walk, and all 6 placement stages."""

from __future__ import annotations

import time

import numpy as np
from scipy.ndimage import label

from ..config import (
    WALL_BUFFER_PX,
    FLAT_STD_THRESH,
    FLAT_MIN_PIXELS,
    UPSTREAM_WALK_STEP_M,
    EXTENSION_STEP_M,
    EXT_SEARCH_MAX_SAMPLES,
    MAX_CREST_FLOW_DOT,
    TERRAIN_WALL_TOP_K,
    ALIGN_WEIGHT,
)
from .terrain import get_downstream_direction_from_dem
from ..utils import (
    _upstream_sample_distances_m,
    _approx_cone_volume_m3,
    _bresenham,
)


# ---------------------------------------------------------------------------
# Cross-channel barrier snapping
# ---------------------------------------------------------------------------

def _snap_cross_channel_barrier_px(
    dem, r0, c0, pixel_size_m, half_width_m=120.0, step_m=15.0,
):
    """Slide along cross-channel axis to embankment ridge pixel."""
    r0i = int(np.clip(int(r0), 0, dem.shape[0] - 1))
    c0i = int(np.clip(int(c0), 0, dem.shape[1] - 1))
    ds = get_downstream_direction_from_dem(dem, r0i, c0i)
    perp = np.array([-float(ds[1]), float(ds[0])], dtype=float)
    pn = float(np.hypot(perp[0], perp[1]))
    if pn < 1e-9:
        return r0i, c0i
    perp = perp / pn
    h, w = dem.shape
    step_px = max(1.0, float(step_m) / float(pixel_size_m))
    hw = max(3, int(round(float(half_width_m) / float(pixel_size_m))))
    su = max(3, int(round(22.0 / float(pixel_size_m))))
    best_r, best_c = r0i, c0i
    best_sc = -1e18
    s = float(-hw)
    while s <= float(hw) + 1e-6:
        rr = int(np.clip(int(round(r0i + perp[0] * s)), 0, h - 1))
        cc = int(np.clip(int(round(c0i + perp[1] * s)), 0, w - 1))
        zc = dem[rr, cc]
        if np.isnan(zc):
            s += step_px
            continue
        ur = int(np.clip(int(round(rr - ds[0] * su)), 0, h - 1))
        uc = int(np.clip(int(round(cc - ds[1] * su)), 0, w - 1))
        dr = int(np.clip(int(round(rr + ds[0] * su)), 0, h - 1))
        dc = int(np.clip(int(round(cc + ds[1] * su)), 0, w - 1))
        zu, zd = dem[ur, uc], dem[dr, dc]
        if np.isnan(zu) or np.isnan(zd):
            s += step_px
            continue
        sc = float(zc) - 0.5 * (float(zu) + float(zd))
        if sc > best_sc:
            best_sc = sc
            best_r, best_c = rr, cc
        s += step_px
    if best_sc < 1.5:
        return r0i, c0i
    return best_r, best_c


# ---------------------------------------------------------------------------
# Wall orientation scoring & iteration
# ---------------------------------------------------------------------------

def _wall_pair_from_crest(wr, wc, ds_dem):
    """Crest unit vector -> (crest_xy, upstream_xy) in pixel row/col space."""
    best_wall = np.array([float(wr), float(wc)], dtype=float)
    perp1 = np.array([-best_wall[1], best_wall[0]])
    perp2 = -perp1
    if np.dot(perp1, ds_dem) > np.dot(perp2, ds_dem):
        downstream_vec = perp1
    else:
        downstream_vec = perp2
    upstream_vec = -downstream_vec
    return best_wall, upstream_vec


def _crest_gap_m_at_angle(dem, dam_r, dam_c, wr, wc, z_spillway, pixel_size, max_search):
    """Valley half-widths in px if both sides hit z_spillway banks."""
    nrows, ncols = dem.shape
    d_pos = None
    for d in range(1, max_search + 1):
        r = int(round(dam_r + wr * d))
        c = int(round(dam_c + wc * d))
        if r < 0 or r >= nrows or c < 0 or c >= ncols:
            break
        elev = dem[r, c]
        if not np.isnan(elev) and elev >= z_spillway:
            d_pos = d
            break
    d_neg = None
    for d in range(1, max_search + 1):
        r = int(round(dam_r - wr * d))
        c = int(round(dam_c - wc * d))
        if r < 0 or r >= nrows or c < 0 or c >= ncols:
            break
        elev = dem[r, c]
        if not np.isnan(elev) and elev >= z_spillway:
            d_neg = d
            break
    if d_pos is None or d_neg is None:
        return None
    gap_px = d_pos + d_neg
    return gap_px * pixel_size


def find_wall_from_terrain(dem, dam_r, dam_c, dam_length_m, z_spillway,
                           pixel_size, flow_dir_px=None, top_k=None):
    """Best (wall, upstream) from terrain scoring, or (None, None)."""
    placed = list(iter_wall_placements_from_terrain(
        dem, dam_r, dam_c, dam_length_m, z_spillway, pixel_size,
        flow_dir_px=flow_dir_px, top_k=top_k if top_k is not None else 1,
    ))
    if not placed:
        return None, None
    return placed[0][0], placed[0][1]


def iter_wall_placements_from_terrain(
    dem, dam_r, dam_c, dam_length_m, z_spillway, pixel_size, *,
    flow_dir_px=None, top_k=TERRAIN_WALL_TOP_K,
    prepend_angles_deg=None, prepend_bypass_flow_align=False,
):
    """Yield up to ``top_k`` (crest, upstream) pairs, best first."""
    nrows, ncols = dem.shape
    dam_length_px = dam_length_m / pixel_size
    lim = max(nrows, ncols) - 1
    max_search = int(min(lim, max(int(dam_length_px * 2.5) + 35, 45)))
    max_search_prepend = int(min(lim, max(int(dam_length_px * 3.2) + 55, 55)))

    ds_dem = get_downstream_direction_from_dem(dem, dam_r, dam_c)
    flow_u = None
    if flow_dir_px is not None:
        nrm = np.linalg.norm(flow_dir_px)
        if nrm > 1e-9:
            flow_u = flow_dir_px / nrm

    seen = set()
    n_out = 0

    if prepend_angles_deg:
        for angle_deg in prepend_angles_deg:
            angle_deg = int(angle_deg) % 180
            angle_rad = np.radians(angle_deg)
            wr = float(np.cos(angle_rad))
            wc = float(np.sin(angle_rad))
            gap_m = _crest_gap_m_at_angle(
                dem, dam_r, dam_c, wr, wc, z_spillway, pixel_size, max_search_prepend,
            )
            if gap_m is None:
                continue
            if prepend_bypass_flow_align:
                diag_m = float(np.hypot(nrows, ncols) * pixel_size)
                if gap_m > min(diag_m * 0.92, dam_length_m * 10.0):
                    continue
            elif gap_m > dam_length_m * 2.0:
                continue
            wall, upstream = _wall_pair_from_crest(wr, wc, ds_dem)
            if not prepend_bypass_flow_align:
                if abs(float(np.dot(wall, ds_dem))) > MAX_CREST_FLOW_DOT:
                    continue
                if flow_u is not None and abs(float(np.dot(wall, flow_u))) > MAX_CREST_FLOW_DOT:
                    continue
            key = (round(wr, 4), round(wc, 4))
            if key in seen:
                continue
            seen.add(key)
            yield wall, upstream
            n_out += 1
            if n_out >= top_k:
                return

    candidates = []
    raw_by_gap = []

    for angle_deg in range(0, 180, 1):
        angle_rad = np.radians(angle_deg)
        wr = np.cos(angle_rad)
        wc = np.sin(angle_rad)

        d_pos = None
        for d in range(1, max_search + 1):
            r = int(round(dam_r + wr * d))
            c = int(round(dam_c + wc * d))
            if r < 0 or r >= nrows or c < 0 or c >= ncols:
                break
            elev = dem[r, c]
            if not np.isnan(elev) and elev >= z_spillway:
                d_pos = d
                break

        d_neg = None
        for d in range(1, max_search + 1):
            r = int(round(dam_r - wr * d))
            c = int(round(dam_c - wc * d))
            if r < 0 or r >= nrows or c < 0 or c >= ncols:
                break
            elev = dem[r, c]
            if not np.isnan(elev) and elev >= z_spillway:
                d_neg = d
                break

        if d_pos is None or d_neg is None:
            continue

        gap_px = d_pos + d_neg
        gap_m = gap_px * pixel_size
        raw_by_gap.append((gap_m, angle_deg, wr, wc))

        if gap_m > dam_length_m * 2.0:
            continue

        width_err_m = abs(gap_m - dam_length_m)
        crest = np.array([wr, wc], dtype=float)
        a_flow = abs(float(np.dot(crest, flow_u))) if flow_u is not None else 0.0
        a_dem = abs(float(np.dot(crest, ds_dem)))
        if flow_u is not None:
            align = max(a_flow, a_dem)
        else:
            align = a_dem

        combined = width_err_m + align * dam_length_m * ALIGN_WEIGHT
        candidates.append((combined, width_err_m, align, wr, wc))

    raw_by_gap.sort(key=lambda t: t[0])
    perp_seen = set()
    for _, raw_angle, _, _ in raw_by_gap[:6]:
        perp_deg = (raw_angle + 90) % 180
        if perp_deg in perp_seen:
            continue
        perp_seen.add(perp_deg)
        pr = np.radians(perp_deg)
        pwr, pwc = float(np.cos(pr)), float(np.sin(pr))
        already = any(
            abs(pwr - c[3]) < 0.02 and abs(pwc - c[4]) < 0.02 for c in candidates
        )
        if already:
            continue
        pgap = _crest_gap_m_at_angle(
            dem, dam_r, dam_c, pwr, pwc, z_spillway, pixel_size, max_search_prepend,
        )
        if pgap is None or pgap > dam_length_m * 5.0:
            continue
        perr = abs(pgap - dam_length_m)
        pc = np.array([pwr, pwc], dtype=float)
        pa_flow = abs(float(np.dot(pc, flow_u))) if flow_u is not None else 0.0
        pa_dem = abs(float(np.dot(pc, ds_dem)))
        pa = max(pa_flow, pa_dem) if flow_u is not None else pa_dem
        pcombined = perr + pa * dam_length_m * ALIGN_WEIGHT
        candidates.append((pcombined, perr, pa, pwr, pwc))

    if not candidates:
        return

    candidates.sort(key=lambda t: t[0])
    for _, _, _, wr, wc in candidates:
        key = (round(wr, 4), round(wc, 4))
        if key in seen:
            continue
        seen.add(key)
        wall, upstream = _wall_pair_from_crest(wr, wc, ds_dem)
        if abs(float(np.dot(wall, ds_dem))) > MAX_CREST_FLOW_DOT:
            continue
        if flow_u is not None and abs(float(np.dot(wall, flow_u))) > MAX_CREST_FLOW_DOT:
            continue
        yield wall, upstream
        n_out += 1
        if n_out >= top_k:
            break

    # River-perpendicular bonus candidate (bypasses DEM-alignment filter)
    if flow_u is not None:
        rp_wr, rp_wc = float(-flow_u[1]), float(flow_u[0])
        if rp_wr < 0:
            rp_wr, rp_wc = -rp_wr, -rp_wc
        rp_key = (round(rp_wr, 4), round(rp_wc, 4))
        if rp_key not in seen:
            rp_gap = _crest_gap_m_at_angle(
                dem, dam_r, dam_c, rp_wr, rp_wc, z_spillway, pixel_size,
                max_search_prepend,
            )
            if rp_gap is not None and rp_gap <= dam_length_m * 5.0:
                seen.add(rp_key)
                rp_wall, rp_up = _wall_pair_from_crest(rp_wr, rp_wc, ds_dem)
                yield rp_wall, rp_up


# ---------------------------------------------------------------------------
# Wall rasterisation & flood fill
# ---------------------------------------------------------------------------

def place_wall(dem, dam_row, dam_col, perp_vec_px,
               wall_elev, spillway_elev, thickness=2):
    nrows, ncols = dem.shape
    perp = perp_vec_px / np.linalg.norm(perp_vec_px) if np.linalg.norm(perp_vec_px) > 0 else np.array([0, 1])

    endpoints = []
    for sign in [1, -1]:
        reached_high = False
        extra = 0
        end_r, end_c = dam_row, dam_col
        for dist in range(1, max(nrows, ncols)):
            r = int(round(dam_row + sign * dist * perp[0]))
            c = int(round(dam_col + sign * dist * perp[1]))
            if r < 0 or r >= nrows or c < 0 or c >= ncols:
                break
            end_r, end_c = r, c
            if not np.isnan(dem[r, c]) and dem[r, c] > spillway_elev:
                reached_high = True
            if reached_high:
                extra += 1
                if extra >= WALL_BUFFER_PX:
                    break
        endpoints.append((end_r, end_c))

    centre_pixels = list(_bresenham(endpoints[0][0], endpoints[0][1],
                                     endpoints[1][0], endpoints[1][1]))

    wall_set = set()
    for r, c in centre_pixels:
        for dr in range(-thickness, thickness + 1):
            for dc in range(-thickness, thickness + 1):
                rr, cc = r + dr, c + dc
                if 0 <= rr < nrows and 0 <= cc < ncols:
                    wall_set.add((rr, cc))

    for r, c in wall_set:
        dem[r, c] = wall_elev


def flood_fill_8(dem, seed_row, seed_col, max_elev):
    nrows, ncols = dem.shape
    mask = np.zeros((nrows, ncols), dtype=bool)
    if seed_row < 0 or seed_row >= nrows or seed_col < 0 or seed_col >= ncols:
        return mask

    seed_val = dem[seed_row, seed_col]
    if np.isnan(seed_val) or seed_val > max_elev:
        return mask

    stack = [(seed_row, seed_col)]
    mask[seed_row, seed_col] = True

    neighbors = [(-1, -1), (-1, 0), (-1, 1),
                 (0, -1),          (0, 1),
                 (1, -1),  (1, 0), (1, 1)]

    while stack:
        r, c = stack.pop()
        for dr, dc in neighbors:
            nr, nc = r + dr, c + dc
            if 0 <= nr < nrows and 0 <= nc < ncols and not mask[nr, nc]:
                val = dem[nr, nc]
                if not np.isnan(val) and val <= max_elev:
                    mask[nr, nc] = True
                    stack.append((nr, nc))

    return mask


def detect_flat_water(dem_footprint, min_pixels=FLAT_MIN_PIXELS,
                      std_thresh=FLAT_STD_THRESH):
    valid = ~np.isnan(dem_footprint)
    if valid.sum() < min_pixels:
        return False, np.nan

    rounded = np.round(dem_footprint * 2) / 2
    unique_elevs, counts = np.unique(rounded[valid], return_counts=True)

    dominant_idx = np.argmax(counts)
    dominant_elev = unique_elevs[dominant_idx]

    flat_mask = valid & (np.abs(dem_footprint - dominant_elev) <= 0.5)
    labeled, n_features = label(flat_mask)
    if n_features == 0:
        return False, np.nan

    sizes = np.bincount(labeled.ravel())
    sizes[0] = 0
    largest = sizes.argmax()
    largest_size = sizes[largest]

    if largest_size < min_pixels:
        return False, np.nan

    cluster_vals = dem_footprint[labeled == largest]
    if np.nanstd(cluster_vals) > std_thresh:
        return False, np.nan

    return True, float(np.nanmean(cluster_vals))


# ---------------------------------------------------------------------------
# Fill seed finder & validation helpers
# ---------------------------------------------------------------------------

def _find_seed_upstream(dem_walled, dam_r, dam_c, upstream_vec, seed_dist, z_spillway):
    seed_r = int(round(dam_r + upstream_vec[0] * seed_dist))
    seed_c = int(round(dam_c + upstream_vec[1] * seed_dist))
    seed_r = int(np.clip(seed_r, 0, dem_walled.shape[0] - 1))
    seed_c = int(np.clip(seed_c, 0, dem_walled.shape[1] - 1))

    if not np.isnan(dem_walled[seed_r, seed_c]) and dem_walled[seed_r, seed_c] <= z_spillway:
        return seed_r, seed_c, True

    for extra in range(1, 30):
        base_r = int(round(dam_r + upstream_vec[0] * (seed_dist + extra)))
        base_c = int(round(dam_c + upstream_vec[1] * (seed_dist + extra)))
        for dr2 in range(-3, 4):
            for dc2 in range(-3, 4):
                rr = int(np.clip(base_r + dr2, 0, dem_walled.shape[0] - 1))
                cc = int(np.clip(base_c + dc2, 0, dem_walled.shape[1] - 1))
                if not np.isnan(dem_walled[rr, cc]) and dem_walled[rr, cc] <= z_spillway:
                    return rr, cc, True
    return 0, 0, False


def _accept_terrain_fill(fp, dem_utm, dam_elev, dam_height, spillway_height,
                         capacity_m3, pixel_area, n_px):
    """Stricter volume gate for terrain-primary path."""
    fp_zmin = float(np.nanmin(dem_utm[fp]))
    fp_zmax = float(np.nanmax(dem_utm[fp]))
    z_min_tolerance = max(15.0, dam_height * 0.75)
    max_vol_approx = n_px * pixel_area * spillway_height / 3.0
    vol_ok = max_vol_approx >= 0.10 * capacity_m3
    z_range = fp_zmax - fp_zmin
    z_range_ok = z_range < spillway_height * 5
    if fp_zmin < dam_elev - z_min_tolerance:
        return False
    if not vol_ok or not z_range_ok:
        return False
    return True


def _accept_fallback_fill(fp, dem_utm, dam_elev, dam_height, spillway_height):
    fp_zmin = float(np.nanmin(dem_utm[fp]))
    fp_zmax = float(np.nanmax(dem_utm[fp]))
    z_min_tolerance = max(15.0, dam_height * 0.75)
    z_range = fp_zmax - fp_zmin
    z_range_ok = z_range < spillway_height * 5
    if fp_zmin < dam_elev - z_min_tolerance:
        return False
    if not z_range_ok:
        return False
    return True


def _flood_downstream_biased(fp, dam_r, dam_c, downstream_px, *,
                             buffer_px=5.0, frac_thresh=0.36):
    """True if too much flooded area sits downstream of the dam."""
    if fp is None or fp.sum() == 0:
        return False
    dv = np.asarray(downstream_px, dtype=float)
    nrm = float(np.linalg.norm(dv))
    if nrm < 1e-9:
        return False
    dv /= nrm
    rr, cc = np.where(fp)
    proj = (rr - float(dam_r)) * dv[0] + (cc - float(dam_c)) * dv[1]
    frac_down = float(np.sum(proj > buffer_px)) / max(1, proj.size)
    return frac_down > frac_thresh


def _pool_downstream_skewed(fp, dam_r, dam_c, downstream_px, *, min_pixels=30):
    """True if pool is biased to the downstream side."""
    if fp is None or int(fp.sum()) < min_pixels:
        return False
    if _flood_downstream_biased(fp, dam_r, dam_c, downstream_px,
                                buffer_px=4.0, frac_thresh=0.28):
        return True
    dv = np.asarray(downstream_px, dtype=float)
    nrm = float(np.linalg.norm(dv))
    if nrm < 1e-9:
        return False
    dv /= nrm
    rr, cc = np.where(fp)
    proj = (rr - float(dam_r)) * dv[0] + (cc - float(dam_c)) * dv[1]
    return float(np.median(proj)) > 1.75


def _downstream_leak_ok(fp, dam_r, dam_c, downstream_vec_px, *,
                        buffer_px=6.0, max_frac=0.005):
    """Reject footprints that spill downstream of the wall."""
    if fp is None or fp.sum() == 0:
        return False
    dv = np.asarray(downstream_vec_px, dtype=float)
    nrm = float(np.linalg.norm(dv))
    if nrm < 1e-9:
        return True
    dv /= nrm

    rr, cc = np.where(fp)
    proj = (rr - float(dam_r)) * dv[0] + (cc - float(dam_c)) * dv[1]
    n_down = int(np.sum(proj > buffer_px))
    frac = n_down / max(1, int(fp.sum()))
    return frac <= max_frac


def _snap_dam_elev(dem_utm, dam_r, dam_c):
    dam_elev = dem_utm[dam_r, dam_c]
    if not np.isnan(dam_elev):
        return dam_r, dam_c, dam_elev
    for dr in range(-3, 4):
        for dc in range(-3, 4):
            rr, cc = dam_r + dr, dam_c + dc
            if 0 <= rr < dem_utm.shape[0] and 0 <= cc < dem_utm.shape[1]:
                if not np.isnan(dem_utm[rr, cc]):
                    return rr, cc, float(dem_utm[rr, cc])
    return dam_r, dam_c, np.nan


# ---------------------------------------------------------------------------
# Upstream valley walk
# ---------------------------------------------------------------------------

def _iter_upstream_positions_walked(dem_utm, dam_r0, dam_c0, upstream_offsets,
                                    pixel_size, walk_step_m=None, downstream_walk=False):
    """Walk along valley, yielding (offset_m, row, col) at each target distance."""
    if walk_step_m is None:
        walk_step_m = UPSTREAM_WALK_STEP_M
    h, w = dem_utm.shape
    targets = sorted({float(x) for x in upstream_offsets})
    r, c = float(dam_r0), float(dam_c0)
    traveled = 0.0
    for target in targets:
        while traveled + 1e-9 < target:
            step = min(walk_step_m, target - traveled)
            ri = int(np.clip(round(r), 0, h - 1))
            ci = int(np.clip(round(c), 0, w - 1))
            ds = get_downstream_direction_from_dem(dem_utm, ri, ci)
            along = ds if downstream_walk else (-ds)
            r += along[0] * (step / pixel_size)
            c += along[1] * (step / pixel_size)
            if not (-0.5 <= r < h - 0.5 and -0.5 <= c < w - 0.5):
                return
            traveled += step
        ri = int(np.clip(round(r), 0, h - 1))
        ci = int(np.clip(round(c), 0, w - 1))
        yield target, ri, ci


# ---------------------------------------------------------------------------
# Single-try terrain placement
# ---------------------------------------------------------------------------

def _try_terrain_placement_once(
    dem_utm, dam_r, dam_c, dam_elev,
    eff_length, dam_height, spillway_height, capacity_m3, pixel_area,
    flow_dir_px, wall_thickness, seed_dist,
    prepend_angles_deg=None, prepend_bypass_flow_align=False,
    deadline=None,
):
    """One terrain wall + flood-fill + acceptance check.
    Returns (fp, n_px, area_km2, dam_r, dam_c, dam_elev, wall_vec, eff_length) or None.
    """
    if eff_length <= 0:
        return None
    pixel_size = np.sqrt(pixel_area)
    z_spillway = dam_elev + spillway_height
    z_wall = dam_elev + dam_height
    h, w = dem_utm.shape

    GOOD_ENOUGH = 0.26
    UPSTREAM_MAX_ERR = 1.5
    best_up = None
    best_up_err = float("inf")
    best_dn = None
    best_dn_err = float("inf")

    for wall_vec, upstream_vec in iter_wall_placements_from_terrain(
        dem_utm, dam_r, dam_c, eff_length, z_spillway,
        pixel_size, flow_dir_px=flow_dir_px, top_k=TERRAIN_WALL_TOP_K,
        prepend_angles_deg=prepend_angles_deg,
        prepend_bypass_flow_align=prepend_bypass_flow_align,
    ):
        dem_walled = dem_utm.copy()
        place_wall(
            dem_walled, dam_r, dam_c, wall_vec,
            z_wall, z_spillway, thickness=wall_thickness,
        )

        for side_idx, side_vec in enumerate(
            (upstream_vec, -np.asarray(upstream_vec, dtype=float))
        ):
            is_upstream = (side_idx == 0)
            sr, sc, ok = _find_seed_upstream(
                dem_walled, dam_r, dam_c, side_vec, seed_dist, z_spillway,
            )
            if not ok:
                continue

            fp = flood_fill_8(dem_walled, sr, sc, z_spillway)
            n_px = int(fp.sum())
            if n_px < 10 or n_px > 0.26 * h * w:
                continue

            opp_vec = -np.asarray(side_vec, dtype=float)
            if not _downstream_leak_ok(
                fp, dam_r, dam_c, opp_vec,
                buffer_px=float(wall_thickness + 6),
                max_frac=0.002,
            ):
                continue

            if not _accept_terrain_fill(
                fp, dem_utm, dam_elev, dam_height, spillway_height,
                capacity_m3, pixel_area, n_px,
            ):
                continue

            approx_vol = _approx_cone_volume_m3(n_px, pixel_area, spillway_height)
            vol_err = abs(np.log(max(approx_vol, 1.0) / max(capacity_m3, 1.0)))
            area_km2 = n_px * pixel_area / 1e6
            wv_tuple = (float(wall_vec[0]), float(wall_vec[1]))
            candidate = (fp, n_px, area_km2, dam_r, dam_c, dam_elev, wv_tuple, float(eff_length))

            if is_upstream:
                if vol_err < best_up_err:
                    best_up_err = vol_err
                    best_up = candidate
            else:
                if vol_err < best_dn_err:
                    best_dn_err = vol_err
                    best_dn = candidate

        if best_up_err < GOOD_ENOUGH:
            return best_up
        if deadline is not None and time.time() > deadline:
            break

    if best_up is not None and best_up_err <= UPSTREAM_MAX_ERR:
        return best_up
    if best_up is not None and best_dn is not None:
        return best_up if best_up_err <= best_dn_err else best_dn
    return best_up or best_dn


# ---------------------------------------------------------------------------
# Extended upstream search
# ---------------------------------------------------------------------------

def search_terrain_wall_extended_upstream(
    dem_utm, dam_r0, dam_c0, dam_length_base_m,
    dam_height, spillway_height, capacity_m3, pixel_area, flow_dir_px,
    wall_thickness, seed_dist,
    skip_duplicate_nominal=False,
    max_shift_px=None,
    prepend_angles_deg=None, prepend_bypass_flow_align=False,
    deadline=None,
):
    """Try crest lengths at walked upstream positions.
    Returns (footprint, n_pixels, area_km2, dam_r, dam_c, dam_elev, upstream_m).
    """
    pixel_size = np.sqrt(pixel_area)
    upstream_offsets = _upstream_sample_distances_m(pixel_size, max_shift_px=max_shift_px)

    n_desired = max(1, int(np.ceil(dam_length_base_m / EXTENSION_STEP_M)) + 1)
    if n_desired > EXT_SEARCH_MAX_SAMPLES:
        extensions = np.linspace(0.0, dam_length_base_m, EXT_SEARCH_MAX_SAMPLES)
    else:
        extensions = np.linspace(0.0, dam_length_base_m, n_desired)

    walked = list(
        _iter_upstream_positions_walked(
            dem_utm, dam_r0, dam_c0, upstream_offsets, pixel_size,
        )
    )

    # Phase 0: local grid search
    h, w = dem_utm.shape
    _LOCAL_RADIUS = 2
    local_seen = set()
    for dr in range(-_LOCAL_RADIUS, _LOCAL_RADIUS + 1):
        for dc in range(-_LOCAL_RADIUS, _LOCAL_RADIUS + 1):
            if dr == 0 and dc == 0:
                continue
            lr, lc = dam_r0 + dr, dam_c0 + dc
            if not (0 <= lr < h and 0 <= lc < w):
                continue
            if (lr, lc) in local_seen:
                continue
            local_seen.add((lr, lc))
            if deadline is not None and time.time() > deadline:
                break
            lr, lc, lelev = _snap_dam_elev(dem_utm, lr, lc)
            if not np.isfinite(lelev):
                continue
            res = _try_terrain_placement_once(
                dem_utm, lr, lc, lelev,
                dam_length_base_m, dam_height, spillway_height, capacity_m3,
                pixel_area, flow_dir_px, wall_thickness, seed_dist,
                prepend_angles_deg=prepend_angles_deg,
                prepend_bypass_flow_align=prepend_bypass_flow_align,
                deadline=deadline,
            )
            if res is not None:
                fp, n_px, area_km2, _dr, _dc, _de, wv, el = res
                return fp, n_px, area_km2, _dr, _dc, _de, 0.0, wv, el

    # Phase 1: base crest length
    for upstream_m, dam_r, dam_c in walked:
        if deadline is not None and time.time() > deadline:
            break
        dam_r, dam_c, dam_elev = _snap_dam_elev(dem_utm, dam_r, dam_c)
        if not np.isfinite(dam_elev):
            continue
        if skip_duplicate_nominal and upstream_m < 0.5:
            continue
        res = _try_terrain_placement_once(
            dem_utm, dam_r, dam_c, dam_elev,
            dam_length_base_m, dam_height, spillway_height, capacity_m3, pixel_area,
            flow_dir_px, wall_thickness, seed_dist,
            prepend_angles_deg=prepend_angles_deg,
            prepend_bypass_flow_align=prepend_bypass_flow_align,
            deadline=deadline,
        )
        if res is not None:
            fp, n_px, area_km2, dr, dc, delev, wv, el = res
            return fp, n_px, area_km2, dr, dc, delev, upstream_m, wv, el

    # Phase 2: lengthen crest
    for upstream_m, dam_r, dam_c in walked:
        if deadline is not None and time.time() > deadline:
            break
        dam_r, dam_c, dam_elev = _snap_dam_elev(dem_utm, dam_r, dam_c)
        if not np.isfinite(dam_elev):
            continue
        for ext_m in extensions:
            if ext_m < 1e-6:
                continue
            if deadline is not None and time.time() > deadline:
                break
            eff_length = dam_length_base_m + ext_m
            res = _try_terrain_placement_once(
                dem_utm, dam_r, dam_c, dam_elev,
                eff_length, dam_height, spillway_height, capacity_m3, pixel_area,
                flow_dir_px, wall_thickness, seed_dist,
                prepend_angles_deg=prepend_angles_deg,
                prepend_bypass_flow_align=prepend_bypass_flow_align,
                deadline=deadline,
            )
            if res is None:
                continue
            fp, n_px, area_km2, dr, dc, delev, wv, el = res
            return fp, n_px, area_km2, dr, dc, delev, upstream_m, wv, el

    return None, 0, 0.0, dam_r0, dam_c0, np.nan, np.nan, None, np.nan


# ---------------------------------------------------------------------------
# Fallback multi-direction fill
# ---------------------------------------------------------------------------

def fallback_multidirection_fill(
    dem_utm, dam_r, dam_c, dam_elev, z_spillway, z_wall,
    spillway_height, dam_height, capacity_m3, pixel_area,
    wall_thickness, seed_dist, area_cap_km2,
    flow_dir_px=None,
):
    downstream_candidates = []
    if flow_dir_px is not None:
        v = np.asarray(flow_dir_px, dtype=float)
        nn = np.linalg.norm(v)
        if nn > 1e-9:
            downstream_candidates.append(v / nn)
    downstream_candidates.append(get_downstream_direction_from_dem(dem_utm, dam_r, dam_c))
    for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1),
                   (-1, -1), (-1, 1), (1, -1), (1, 1)]:
        v = np.array([dr, dc], dtype=float)
        downstream_candidates.append(v / np.linalg.norm(v))

    valid_fills = []
    for cand_idx, downstream_px in enumerate(downstream_candidates):
        upstream_px = -downstream_px
        perp_px = np.array([-downstream_px[1], downstream_px[0]])

        dem_walled = dem_utm.copy()
        place_wall(dem_walled, dam_r, dam_c, perp_px,
                   z_wall, z_spillway, thickness=wall_thickness)

        h, w = dem_utm.shape
        for side_idx, side_vec in enumerate((upstream_px, downstream_px)):
            is_upstream = (side_idx == 0)
            opp = -np.asarray(side_vec, dtype=float)
            seed_r, seed_c, ok = _find_seed_upstream(
                dem_walled, dam_r, dam_c, side_vec, seed_dist, z_spillway,
            )
            if not ok:
                continue

            fp = flood_fill_8(dem_walled, seed_r, seed_c, z_spillway)
            n_px = int(fp.sum())
            if n_px < 4:
                continue
            if not _downstream_leak_ok(
                fp, dam_r, dam_c, opp,
                buffer_px=float(wall_thickness + 6),
                max_frac=0.002,
            ):
                continue
            if not _accept_fallback_fill(fp, dem_utm, dam_elev, dam_height, spillway_height):
                continue

            max_vol_approx = n_px * pixel_area * spillway_height / 3.0
            if max_vol_approx > 2.2 * capacity_m3:
                continue
            if n_px > 0.24 * h * w:
                continue

            fp_area_km2 = n_px * pixel_area / 1e6
            valid_fills.append((n_px, fp_area_km2, fp, cand_idx, is_upstream, perp_px))

    if not valid_fills:
        return None, 0, 0.0, None

    MIN_PIXELS = 10
    within_cap = [(n, a, fp, ci, up, wv) for n, a, fp, ci, up, wv in valid_fills
                  if a <= area_cap_km2 and n >= MIN_PIXELS]
    pool = within_cap if within_cap else valid_fills

    up_fills = [f for f in pool if f[4]]
    dn_fills = [f for f in pool if not f[4]]

    if up_fills:
        up_fills.sort(key=lambda x: x[0], reverse=True)
        best = up_fills[0]
    elif dn_fills:
        dn_fills.sort(key=lambda x: x[0], reverse=True)
        best = dn_fills[0]
    else:
        pool_sorted = sorted(pool, key=lambda x: x[0], reverse=True)
        best = pool_sorted[0]
    n_pixels, footprint_area_km2, footprint, _, _, perp_best = best
    wall_vec_out = (float(perp_best[0]), float(perp_best[1]))
    return footprint, n_pixels, footprint_area_km2, wall_vec_out
