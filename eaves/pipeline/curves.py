"""Per-dam EAV curve construction (:func:`process_dam`).

Clips the DEM around the dam, runs the staged wall placement, floods the
basin to the spillway elevation, integrates the hypsometry into (z, A, V)
levels with the last level at the spillway or where the volume reaches the
catalog capacity, and fits the power law V = c*A^b. Pre-2000 and
unknown-year dams get a flat-water check and, where it triggers, a partial
curve.
"""

from __future__ import annotations

import time

import numpy as np
import pandas as pd
from pyproj import Transformer
from rasterio.transform import rowcol
from scipy.integrate import cumulative_trapezoid
from scipy.ndimage import binary_dilation, binary_fill_holes, label

from ..config import (
    _PLACEMENT_BUDGET_S,
    BIN_Z,
    LEVEL_MERGE_M,
    UPSTREAM_MAX_SHIFT_PX,
    VOID_THRESHOLD,
    WALL_THICKNESS,
)
from ..utils import (
    buffer_deg_for_dam,
    fit_power_law,
    utm_epsg_from_lon,
)
from .placement import (
    _approx_cone_volume_m3,
    _pool_downstream_skewed,
    _snap_dam_elev,
    _try_terrain_placement_once,
    detect_flat_water,
    fallback_multidirection_fill,
    search_terrain_wall_extended_upstream,
)
from .terrain import (
    _flood_river_overlay_from_segment,
    clip_and_reproject_dem,
    get_downstream_direction_from_dem,
    get_river_direction_from_segment,
)


def _parse_construction_year(cy_raw):
    """Parse a catalog construction year, or ``None`` if missing/non-numeric.

    An unknown year is left as ``None``. The
    flat-water check in :func:`process_dam` runs for unknown-year dams so the
    SRTM surface itself decides whether the reservoir was already impounded
    (partial curve) or captured as a bare valley (full curve).
    """
    try:
        return int(cy_raw)
    except (TypeError, ValueError):
        return None


_EIGHT_CONNECTED = np.ones((3, 3), dtype=bool)


def fill_enclosed_voids(dem):
    """Gives the missing cells that terrain encloses the highest elevation of their rim and returns the DEM with the mask of those cells.

    The flood fill never enters a missing cell, so a gap inside a basin would leave a hole in the footprint
    that no count over the footprint can see. At the highest elevation of its rim, a gap floods only at a level
    that floods every cell around it, so it never opens a path that the terrain around it would close, and the
    accepted footprint counts its cells against the void threshold. The missing margin of the projected window
    touches the array edge and stays missing.
    """
    finite = np.isfinite(dem)
    voids = binary_fill_holes(finite) & ~finite
    if not voids.any():
        return dem, voids
    out = dem.copy()
    gaps, n_gaps = label(voids, structure=_EIGHT_CONNECTED)
    for i in range(1, n_gaps + 1):
        gap = gaps == i
        rim = binary_dilation(gap, structure=_EIGHT_CONNECTED) & finite
        out[gap] = dem[rim].max()
    return out, voids


class DamRow:
    """Lightweight stand-in for a GeoDataFrame row, the dam dict and its geometry in the form :func:`process_dam` reads."""

    def __init__(self, data, geom):
        self._data = data
        self.geometry = geom

    def __getitem__(self, key):
        return self._data[key]

    def get(self, key, default=None):
        return self._data.get(key, default)


def process_dam(dam_row_data, gdf_rivers, srtm_data, srtm_transform, srtm_crs,
                override_lat=None, override_lon=None):
    dam_id = dam_row_data["dam_id"]
    if override_lat is not None and override_lon is not None:
        dam_lat, dam_lon = override_lat, override_lon
    else:
        dam_lat = pd.to_numeric(dam_row_data.get("latitude"), errors="coerce")
        dam_lon = pd.to_numeric(dam_row_data.get("longitude"), errors="coerce")
        if not np.isfinite(dam_lat) or not np.isfinite(dam_lon):
            dam_lat = dam_row_data.geometry.y
            dam_lon = dam_row_data.geometry.x

    dam_height = float(dam_row_data["dam_height_m"])
    spillway_height = float(dam_row_data["spillway_height_m"])
    if spillway_height <= 0:
        spillway_height = dam_height * 0.75
    capacity_m3 = float(dam_row_data["storage_capacity_m3"])
    construction_year = _parse_construction_year(
        dam_row_data.get("construction_year"))

    target_epsg = utm_epsg_from_lon(dam_lon)
    radius = buffer_deg_for_dam(capacity_m3)

    dem_utm, dem_tf, pixel_area, dst_crs = clip_and_reproject_dem(
        srtm_data, srtm_transform, srtm_crs,
        dam_lat, dam_lon, radius, target_epsg,
    )
    dem_utm, void_mask = fill_enclosed_voids(dem_utm)

    tr = Transformer.from_crs("EPSG:4326", f"EPSG:{target_epsg}", always_xy=True)
    dam_x, dam_y = tr.transform(dam_lon, dam_lat)
    dam_r, dam_c = rowcol(dem_tf, dam_x, dam_y)
    dam_r, dam_c = int(dam_r), int(dam_c)

    if dam_r < 0 or dam_r >= dem_utm.shape[0] or dam_c < 0 or dam_c >= dem_utm.shape[1]:
        raise ValueError("Dam pixel outside clipped DEM extent")

    dam_r, dam_c, dam_elev = _snap_dam_elev(dem_utm, dam_r, dam_c)
    if not np.isfinite(dam_elev):
        raise ValueError("Dam location has NaN elevation and no nearby valid pixels")

    dam_r0, dam_c0 = dam_r, dam_c

    capacity_mcm = capacity_m3 / 1e6
    dam_length_m = float(dam_row_data.get("dam_length_m", 0))
    if dam_length_m <= 0:
        dam_length_m = 300.0

    if spillway_height > 0:
        area_cap_m2 = 15.0 * capacity_m3 / spillway_height
    else:
        area_cap_m2 = 15.0 * capacity_m3 / max(dam_height, 1.0)
    area_cap_km2 = area_cap_m2 / 1e6

    pixel_size = np.sqrt(pixel_area)
    wall_thickness = WALL_THICKNESS
    seed_dist = wall_thickness + 4

    river_dir_px = None
    # The river direction is read on the reach part nearest the dam, recorded by the preprocessing with the snap
    seg_id = dam_row_data.get("closest_segment_id")
    if gdf_rivers is not None and seg_id is not None and str(seg_id) != "nan":
        dir_geo = get_river_direction_from_segment(
            gdf_rivers, str(seg_id), dam_lon, dam_lat
        )
        if dir_geo is not None:
            step = 0.001
            p2_lon = dam_lon + dir_geo[0] * step
            p2_lat = dam_lat + dir_geo[1] * step
            p1_x, p1_y = tr.transform(dam_lon, dam_lat)
            p2_x, p2_y = tr.transform(p2_lon, p2_lat)
            r1, c1 = rowcol(dem_tf, p1_x, p1_y)
            r2, c2 = rowcol(dem_tf, p2_x, p2_y)
            dr_px = float(r2 - r1)
            dc_px = float(c2 - c1)
            norm_px = np.hypot(dr_px, dc_px)
            if norm_px > 1e-6:
                river_dir_px = np.array([dr_px, dc_px]) / norm_px

    _deadline = time.time() + _PLACEMENT_BUDGET_S

    # ---- Stage 1: direct placement ----
    nominal = _try_terrain_placement_once(
        dem_utm, dam_r0, dam_c0, dam_elev,
        dam_length_m, dam_height, spillway_height, capacity_m3, pixel_area,
        river_dir_px, wall_thickness, seed_dist,
        deadline=_deadline,
    )
    if nominal is not None:
        footprint, n_pixels, footprint_area_km2, dam_r, dam_c, dam_elev_out, wall_vec, eff_length_m = nominal
        placement_upstream_shift_m = 0.0
        placement_method = "stage_1_fast_path"
    else:
        # ---- Stage 2: upstream walk ----
        out = search_terrain_wall_extended_upstream(
            dem_utm, dam_r0, dam_c0, dam_length_m,
            dam_height, spillway_height, capacity_m3, pixel_area, river_dir_px,
            wall_thickness, seed_dist,
            skip_duplicate_nominal=True,
            deadline=_deadline,
        )
        (footprint, n_pixels, footprint_area_km2, dam_r, dam_c,
         dam_elev_out, placement_upstream_shift_m, wall_vec, eff_length_m) = out
        if footprint is not None:
            placement_method = "stage_2_upstream_walk"

    # ---- Stage 3: quality recovery ----
    if (
        footprint is not None
        and placement_method in ("stage_1_fast_path", "stage_2_upstream_walk")
        and time.time() < _deadline
    ):
        ds_nom = get_downstream_direction_from_dem(dem_utm, dam_r, dam_c)
        approx_v0 = _approx_cone_volume_m3(n_pixels, pixel_area, spillway_height)
        vol_short = approx_v0 < 0.34 * capacity_m3 and capacity_m3 >= 2.5e6
        geom_bad = _pool_downstream_skewed(footprint, dam_r, dam_c, ds_nom)
        if not geom_bad and n_pixels > 50:
            _rr, _cc = np.where(footprint)
            _cdist = float(np.hypot(np.mean(_rr) - dam_r, np.mean(_cc) - dam_c))
            _scale = max(1.0, np.sqrt(float(n_pixels)))
            if _cdist / _scale > 1.5:
                geom_bad = True
        if vol_short or geom_bad:
            out2 = search_terrain_wall_extended_upstream(
                dem_utm, dam_r0, dam_c0, dam_length_m,
                dam_height, spillway_height, capacity_m3, pixel_area, river_dir_px,
                wall_thickness, seed_dist,
                skip_duplicate_nominal=True,
                deadline=_deadline,
            )
            fp2, n2, a2, dr2, dc2, de2, up_m2, wv2, el2 = out2
            if fp2 is not None:
                ds2 = get_downstream_direction_from_dem(dem_utm, dr2, dc2)
                bad2 = _pool_downstream_skewed(fp2, dr2, dc2, ds2)
                approx_v2 = _approx_cone_volume_m3(n2, pixel_area, spillway_height)
                # Applies the stage-3 acceptance ratios
                take = False
                if geom_bad and (not bad2) and approx_v2 >= approx_v0 * 0.82:
                    take = True
                elif geom_bad and approx_v2 > approx_v0 * 1.06:
                    take = True
                elif geom_bad and (not bad2) and float(up_m2) >= 3.0 * pixel_size and approx_v2 >= approx_v0 * 0.68:
                    take = True
                elif vol_short and approx_v2 > approx_v0 * 1.1:
                    take = True
                elif vol_short and (not bad2) and approx_v2 >= approx_v0 * 0.95 and up_m2 > 5.0:
                    take = True
                if take:
                    footprint, n_pixels, footprint_area_km2 = fp2, n2, a2
                    dam_r, dam_c, dam_elev_out = dr2, dc2, de2
                    placement_upstream_shift_m = up_m2
                    wall_vec, eff_length_m = wv2, el2
                    placement_method = "stage_3_quality_recovery"

    # ---- Stage 4: river-direction retry ----
    if (
        footprint is not None
        and placement_method in ("stage_1_fast_path", "stage_2_upstream_walk", "stage_3_quality_recovery")
        and river_dir_px is not None
        and time.time() < _deadline
    ):
        _rr0, _cc0 = np.where(footprint)
        _cdist0 = float(np.hypot(np.mean(_rr0) - dam_r, np.mean(_cc0) - dam_c))
        _scale0 = max(1.0, np.sqrt(float(n_pixels)))
        _cratio0 = _cdist0 / _scale0
        _approx_v_rr = _approx_cone_volume_m3(n_pixels, pixel_area, spillway_height)
        _vol_short_rr = _approx_v_rr < 0.34 * capacity_m3 and capacity_m3 >= 2.5e6
        if (_cratio0 > 1.5 or _vol_short_rr) and n_pixels > 50:
            _river_up = np.asarray(river_dir_px, dtype=float)
            _rn = float(np.linalg.norm(_river_up))
            if _rn > 1e-9:
                _river_up /= _rn
                # Walks the wall along the river, upstream and then downstream, and keeps of the first accepted candidate of each direction the one whose volume lies closer to the capacity
                _best_rr = None
                for _sign in (1.0, -1.0):
                    for _off_px in [3, 5, 8, 12, 16, 20]:
                        if time.time() > _deadline:
                            break
                        _nr = int(round(dam_r0 + _sign * _river_up[0] * _off_px))
                        _nc = int(round(dam_c0 + _sign * _river_up[1] * _off_px))
                        if not (0 <= _nr < dem_utm.shape[0] and 0 <= _nc < dem_utm.shape[1]):
                            continue
                        _nr, _nc, _ne = _snap_dam_elev(dem_utm, _nr, _nc)
                        if not np.isfinite(_ne):
                            continue
                        _res = _try_terrain_placement_once(
                            dem_utm, _nr, _nc, _ne,
                            dam_length_m, dam_height, spillway_height, capacity_m3,
                            pixel_area, river_dir_px, wall_thickness, seed_dist,
                            deadline=_deadline,
                        )
                        if _res is not None:
                            _rfp, _rn_px, _ra, _rdr, _rdc, _rde, _rwv, _rel = _res
                            _rrR, _ccR = np.where(_rfp)
                            _cdistR = float(np.hypot(np.mean(_rrR) - _rdr, np.mean(_ccR) - _rdc))
                            _scaleR = max(1.0, np.sqrt(float(_rn_px)))
                            _cratioR = _cdistR / _scaleR
                            _vR = _approx_cone_volume_m3(_rn_px, pixel_area, spillway_height)
                            _accept_rr = _cratioR < _cratio0 * 0.85
                            if not _accept_rr and _vol_short_rr:
                                _accept_rr = _vR >= _approx_v_rr * 0.5
                            if _accept_rr:
                                _err_rr = abs(np.log(max(_vR, 1e-9) / capacity_m3))
                                if _best_rr is None or _err_rr < _best_rr[0]:
                                    _best_rr = (_err_rr, _res, _sign * _off_px)
                                break
                # Replaces the fill only when the candidate lies closer to the capacity. The shift is positive upstream and negative downstream
                _err0_rr = abs(np.log(max(_approx_v_rr, 1e-9) / capacity_m3))
                if _best_rr is not None and _best_rr[0] < _err0_rr:
                    _, _res, _signed_off_px = _best_rr
                    _rfp, _rn_px, _ra, _rdr, _rdc, _rde, _rwv, _rel = _res
                    footprint, n_pixels, footprint_area_km2 = _rfp, _rn_px, _ra
                    dam_r, dam_c, dam_elev_out = _rdr, _rdc, _rde
                    placement_upstream_shift_m = float(_signed_off_px) * pixel_size
                    wall_vec, eff_length_m = _rwv, _rel
                    placement_method = "stage_4_river_retry"

    # ---- Stage 5: relaxed-alignment retry ----
    if footprint is None and time.time() < _deadline:
        _relax_kw = dict(
            prepend_angles_deg=[0, 90, 45, 135],
            prepend_bypass_flow_align=True,
        )
        relax_nom = _try_terrain_placement_once(
            dem_utm, dam_r0, dam_c0, dam_elev,
            dam_length_m, dam_height, spillway_height, capacity_m3, pixel_area,
            river_dir_px, wall_thickness, seed_dist,
            deadline=_deadline,
            **_relax_kw,
        )
        if relax_nom is not None:
            footprint, n_pixels, footprint_area_km2, dam_r, dam_c, dam_elev_out, wall_vec, eff_length_m = relax_nom
            placement_upstream_shift_m = 0.0
            placement_method = "stage_5_relaxed_alignment"
        elif time.time() < _deadline:
            out_r = search_terrain_wall_extended_upstream(
                dem_utm, dam_r0, dam_c0, dam_length_m,
                dam_height, spillway_height, capacity_m3, pixel_area, river_dir_px,
                wall_thickness, seed_dist,
                skip_duplicate_nominal=True,
                deadline=_deadline,
                **_relax_kw,
            )
            fp_r, n_r, a_r, dr_r, dc_r, de_r, up_r, wv_r, el_r = out_r
            if fp_r is not None:
                footprint, n_pixels, footprint_area_km2 = fp_r, n_r, a_r
                dam_r, dam_c, dam_elev_out = dr_r, dc_r, de_r
                placement_upstream_shift_m = up_r
                wall_vec, eff_length_m = wv_r, el_r
                placement_method = "stage_5_relaxed_alignment"

    # ---- Stage 6: fallback ----
    if footprint is None:
        dam_r, dam_c = dam_r0, dam_c0
        dam_elev = float(dem_utm[dam_r, dam_c])
        if np.isnan(dam_elev):
            dam_r, dam_c, dam_elev = _snap_dam_elev(dem_utm, dam_r, dam_c)
        z_spillway = dam_elev + spillway_height
        z_wall = dam_elev + dam_height
        footprint, n_pixels, footprint_area_km2, wall_vec = fallback_multidirection_fill(
            dem_utm, dam_r, dam_c, dam_elev, z_spillway, z_wall,
            spillway_height, dam_height, capacity_m3, pixel_area,
            wall_thickness, seed_dist, area_cap_km2,
            river_dir_px=river_dir_px, dam_length_m=dam_length_m,
        )
        eff_length_m = dam_length_m
        if footprint is None:
            raise ValueError(
                "placement_failed: no valid flood fill after extension, "
                f"upstream search (0\u2013{UPSTREAM_MAX_SHIFT_PX:.0f} px along walk), and fallback"
            )
        placement_method = "stage_6_fallback"
        placement_upstream_shift_m = np.nan
    else:
        dam_elev = float(dam_elev_out)
        z_spillway = dam_elev + spillway_height

    void_fraction = float(void_mask[footprint].sum()) / n_pixels if n_pixels > 0 else 0.0
    if void_fraction >= VOID_THRESHOLD:
        raise ValueError(f"srtm_voids: void_fraction={void_fraction:.3f}")

    dem_fp = np.where(footprint, dem_utm, np.nan)
    z_min = float(np.nanmin(dem_fp))
    z_max = z_spillway

    if z_max <= z_min:
        raise ValueError(f"z_max ({z_max:.1f}) <= z_min ({z_min:.1f})")

    # Snaps z_min to the level grid, a shift of at most 0.25 m
    z_min = round(float(z_min) * 2.0) / 2.0
    # Levels BIN_Z apart from the floor, and the spillway elevation itself as the last level. A regular level within LEVEL_MERGE_M of the spillway gives way to it, and no two rows of the released table share an elevation
    elev_bins = np.arange(z_min, z_max, BIN_Z)
    if elev_bins.size > 1 and z_max - elev_bins[-1] < LEVEL_MERGE_M:
        elev_bins[-1] = z_max
    else:
        elev_bins = np.append(elev_bins, z_max)

    def _area_at(z):
        return float(np.nansum(dem_fp <= z)) * pixel_area

    area_m2 = np.array([_area_at(z) for z in elev_bins])
    vol_m3 = cumulative_trapezoid(area_m2, elev_bins, initial=0)

    vol_cap = capacity_m3
    capped = False
    if vol_m3[-1] > vol_cap:
        # The volume reaches the catalog capacity below the spillway. The last level moves to the elevation where the trapezoid volume equals the capacity. Inside the step that crosses it the area runs linearly between the two bounding levels, as the trapezoid rule assumes. The volume is then continuous in the level and the solution exact
        k = int(np.searchsorted(vol_m3, vol_cap))
        z0, a0, v0 = float(elev_bins[k - 1]), float(area_m2[k - 1]), float(vol_m3[k - 1])
        z1, a1 = float(elev_bins[k]), float(area_m2[k])

        def _area_between(z):
            return a0 + (a1 - a0) * (z - z0) / (z1 - z0)

        def _vol_at(z):
            return v0 + 0.5 * (a0 + _area_between(z)) * (z - z0)

        z_lo, z_hi = z0, z1
        for _ in range(60):
            z_mid = 0.5 * (z_lo + z_hi)
            if _vol_at(z_mid) < vol_cap:
                z_lo = z_mid
            else:
                z_hi = z_mid
        z_cap = z_hi
        a_cap = _area_between(z_cap)
        # A capped level within LEVEL_MERGE_M of the level below it replaces that level
        keep = k if z_cap - z0 >= LEVEL_MERGE_M else max(k - 1, 1)
        elev_bins = np.append(elev_bins[:keep], z_cap)
        area_m2 = np.append(area_m2[:keep], a_cap)
        vol_m3 = np.append(vol_m3[:keep], vol_cap)
        z_max = z_cap
        footprint_area_km2 = a_cap / 1e6
        footprint = footprint & (dem_utm <= z_max)
        n_pixels = int(footprint.sum())
        void_fraction = float(void_mask[footprint].sum()) / n_pixels if n_pixels > 0 else 0.0
        capped = True

    year_unknown = construction_year is None
    is_pre2000 = (not year_unknown) and construction_year < 2000
    curve_type = "full"
    srtm_water_level = np.nan
    coverage_fraction = 1.0

    # Runs the flat-water check for pre-2000 and unknown-year dams, which may be impounded in the February 2000 SRTM scene
    if is_pre2000 or year_unknown:
        is_flat, water_level = detect_flat_water(dem_fp)
        if is_flat:
            curve_type = "partial"
            srtm_water_level = water_level
            z_range = z_max - z_min
            if z_range > 0:
                terrain_range = z_max - water_level
                coverage_fraction = max(0.0, min(1.0, terrain_range / z_range))

    if curve_type == "partial" and not np.isnan(srtm_water_level):
        fit_mask = elev_bins >= srtm_water_level
        c, b, r2 = fit_power_law(area_m2[fit_mask], vol_m3[fit_mask])
    else:
        c, b, r2 = fit_power_law(area_m2, vol_m3)

    flood_river_overlay = _flood_river_overlay_from_segment(
        gdf_rivers,
        dam_row_data.get("snapped_segment_id"),
        dem_tf,
        target_epsg,
    )

    # ---- Post-placement QC gate ----
    _qc_reasons = []
    if n_pixels > 50:
        _rr_qc, _cc_qc = np.where(footprint)
        _centroid_r = float(np.mean(_rr_qc))
        _centroid_c = float(np.mean(_cc_qc))
        _cdist_qc = float(np.hypot(_centroid_r - dam_r, _centroid_c - dam_c))
        _scale_qc = max(1.0, np.sqrt(float(n_pixels)))
        _cratio_qc = _cdist_qc / _scale_qc
        if _cratio_qc > 2.5:
            _qc_reasons.append(
                f"Flood centroid ratio {_cratio_qc:.2f} > 2.5 "
                f"(cdist={_cdist_qc:.0f} px, n_px={n_pixels}), fill displaced"
            )
    if n_pixels > 0 and capacity_m3 >= 1e6:
        _srtm_vol = float(vol_m3[-1]) if len(vol_m3) > 0 else 0.0
        _vol_frac = _srtm_vol / capacity_m3
        if _vol_frac < 0.20:
            _qc_reasons.append(
                f"Volume fraction {_vol_frac:.2f} < 0.20 "
                f"(~{_srtm_vol/1e6:.1f} vs {capacity_mcm:.1f} MCM), fill too small"
            )
    if _qc_reasons:
        raise ValueError("bad_fill_auto: " + "; ".join(_qc_reasons))

    return {
        "dam_id": dam_id,
        "construction_year": (construction_year
                              if construction_year is not None else np.nan),
        "dam_height_m": dam_height,
        "spillway_height_m": spillway_height,
        "capacity_mcm": capacity_mcm,
        "curve_type": curve_type,
        "srtm_water_level_m": srtm_water_level,
        "coverage_fraction": coverage_fraction,
        "z_min": z_min,
        "z_max": z_max,
        "footprint_area_km2": footprint_area_km2,
        "c": c,
        "b": b,
        "r_squared": r2,
        "n_pixels": n_pixels,
        "void_fraction": void_fraction,
        "capped": capped,
        "elev_bins": elev_bins,
        "area_m2": area_m2,
        "vol_m3": vol_m3,
        "dem_utm": dem_utm,
        "footprint": footprint,
        "dem_transform": dem_tf,
        "dam_rc": (dam_r, dam_c),
        "placement_upstream_shift_m": (
            float(placement_upstream_shift_m)
            if np.isfinite(placement_upstream_shift_m) else np.nan
        ),
        "placement_method": placement_method,
        "flood_river_overlay": flood_river_overlay,
        "wall_vec": wall_vec,
        "eff_length_m": eff_length_m,
        "pixel_size": pixel_size,
    }
