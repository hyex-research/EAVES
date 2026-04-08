"""Per-dam EAV curve construction (``process_dam``)."""

from __future__ import annotations

import time

import numpy as np
import pandas as pd
from rasterio.transform import rowcol
from scipy.integrate import cumulative_trapezoid

from .config import (
    BIN_Z,
    VOID_THRESHOLD,
    WALL_THICKNESS,
    UPSTREAM_MAX_SHIFT_PX,
    _PLACEMENT_BUDGET_S,
)
from .utils import (
    _get_placement_override,
    _ov_float,
    _ov_bool,
    _ov_int,
    _ov_preferred_crest_angles_deg,
    utm_epsg_from_lon,
    buffer_deg_for_dam,
    fit_power_law,
    interpolate_nans,
    _approx_cone_volume_m3,
)
from .terrain import (
    clip_and_reproject_dem,
    get_flow_direction_from_segment,
    _flood_river_overlay_from_segment,
    get_downstream_direction_from_dem,
)
from .placement import (
    _snap_cross_channel_barrier_px,
    _snap_dam_elev,
    _try_terrain_placement_once,
    search_terrain_wall_extended_upstream,
    fallback_multidirection_fill,
    _pool_downstream_skewed,
    detect_flat_water,
)


def process_dam(dam_row_data, gdf_rivers, srtm_data, srtm_transform, srtm_crs,
                override_lat=None, override_lon=None):
    from pyproj import Transformer

    csv_id = dam_row_data["csv_id"]
    ov = _get_placement_override(csv_id)
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
    if (
        spillway_height <= 1.25
        and dam_height >= 3.0
        and capacity_m3 >= 5e6
    ):
        spillway_height = float(np.clip(dam_height * 0.78, dam_height * 0.55, dam_height - 0.5))
    sh_ov = _ov_float(ov, "spillway_height_m")
    if sh_ov is not None and sh_ov > 0:
        spillway_height = sh_ov
    construction_year = int(dam_row_data["construction_year_gregorian"])

    target_epsg = utm_epsg_from_lon(dam_lon)
    radius = buffer_deg_for_dam(capacity_m3, dam_height)

    dem_utm, dem_tf, pixel_area, dst_crs = clip_and_reproject_dem(
        srtm_data, srtm_transform, srtm_crs,
        dam_lat, dam_lon, radius, target_epsg,
    )

    tr = Transformer.from_crs("EPSG:4326", f"EPSG:{target_epsg}", always_xy=True)
    dam_x, dam_y = tr.transform(dam_lon, dam_lat)
    dam_r, dam_c = rowcol(dem_tf, dam_x, dam_y)
    dam_r, dam_c = int(dam_r), int(dam_c)

    if dam_r < 0 or dam_r >= dem_utm.shape[0] or dam_c < 0 or dam_c >= dem_utm.shape[1]:
        raise ValueError("Dam pixel outside clipped DEM extent")

    dam_r, dam_c, dam_elev = _snap_dam_elev(dem_utm, dam_r, dam_c)
    if not np.isfinite(dam_elev):
        raise ValueError("Dam location has NaN elevation and no nearby valid pixels")

    if _ov_bool(ov, "snap_cross_channel_ridge"):
        ps_bar = float(np.sqrt(pixel_area))
        hw_m = _ov_float(ov, "snap_barrier_half_width_m", 120.0)
        if hw_m is None or hw_m < 5.0:
            hw_m = 120.0
        st_m = _ov_float(ov, "snap_barrier_step_m", 15.0)
        if st_m is None or st_m < 5.0:
            st_m = 15.0
        br, bc = _snap_cross_channel_barrier_px(
            dem_utm, dam_r, dam_c, ps_bar,
            half_width_m=float(hw_m), step_m=float(st_m),
        )
        if (br, bc) != (int(dam_r), int(dam_c)):
            dam_r, dam_c = br, bc
            dam_r, dam_c, dam_elev = _snap_dam_elev(dem_utm, dam_r, dam_c)
            if not np.isfinite(dam_elev):
                raise ValueError(
                    "Dam location after snap_cross_channel_ridge has NaN elevation"
                )

    ar_off = _ov_int(ov, "anchor_row_offset_px", 0) or 0
    ac_off = _ov_int(ov, "anchor_col_offset_px", 0) or 0
    if ar_off != 0 or ac_off != 0:
        h0, w0 = dem_utm.shape
        dam_r = int(np.clip(dam_r + ar_off, 0, h0 - 1))
        dam_c = int(np.clip(dam_c + ac_off, 0, w0 - 1))
        dam_r, dam_c, dam_elev = _snap_dam_elev(dem_utm, dam_r, dam_c)
        if not np.isfinite(dam_elev):
            raise ValueError(
                "Dam location after anchor_row/col offset has NaN elevation"
            )

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

    flow_dir_px = None
    seg_id = dam_row_data.get("snapped_segment_id")
    if gdf_rivers is not None and seg_id is not None and str(seg_id) != "nan":
        dir_geo = get_flow_direction_from_segment(
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
                flow_dir_px = np.array([dr_px, dc_px]) / norm_px

    z_spillway = dam_elev + spillway_height
    z_wall = dam_elev + dam_height

    pre_angles = _ov_preferred_crest_angles_deg(ov)
    pre_bypass = _ov_bool(ov, "relax_preferred_crest_align")
    crest_kw = {}
    if pre_angles:
        crest_kw["prepend_angles_deg"] = pre_angles
        crest_kw["prepend_bypass_flow_align"] = pre_bypass

    _deadline = time.time() + _PLACEMENT_BUDGET_S

    # --- Stage 1: fast path ---
    nominal = _try_terrain_placement_once(
        dem_utm, dem_tf, dam_r0, dam_c0, dam_elev,
        dam_length_m, dam_height, spillway_height, capacity_m3, pixel_area,
        flow_dir_px, wall_thickness, seed_dist,
        deadline=_deadline,
        **crest_kw,
    )
    if nominal is not None:
        footprint, n_pixels, footprint_area_km2, dam_r, dam_c, dam_elev_out = nominal
        placement_upstream_shift_m = 0.0
        placement_method = "stage_1_fast_path"
    else:
        # --- Stage 2: upstream walk ---
        out = search_terrain_wall_extended_upstream(
            dem_utm, dem_tf, dam_r0, dam_c0, dam_length_m,
            dam_height, spillway_height, capacity_m3, pixel_area, flow_dir_px,
            wall_thickness, seed_dist,
            skip_duplicate_nominal=True,
            deadline=_deadline,
            **crest_kw,
        )
        footprint, n_pixels, footprint_area_km2, dam_r, dam_c, dam_elev_out, placement_upstream_shift_m = out
        if footprint is not None:
            placement_method = "stage_2_upstream_walk"

    # --- Stage 3: quality recovery ---
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
                dem_utm, dem_tf, dam_r0, dam_c0, dam_length_m,
                dam_height, spillway_height, capacity_m3, pixel_area, flow_dir_px,
                wall_thickness, seed_dist,
                skip_duplicate_nominal=True,
                deadline=_deadline,
                **crest_kw,
            )
            fp2, n2, a2, dr2, dc2, de2, up_m2 = out2
            if fp2 is not None:
                ds2 = get_downstream_direction_from_dem(dem_utm, dr2, dc2)
                bad2 = _pool_downstream_skewed(fp2, dr2, dc2, ds2)
                approx_v2 = _approx_cone_volume_m3(n2, pixel_area, spillway_height)
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
                    placement_method = "stage_3_quality_recovery"

    # --- Stage 4: river-direction retry ---
    if (
        footprint is not None
        and placement_method in ("stage_1_fast_path", "stage_2_upstream_walk", "stage_3_quality_recovery")
        and flow_dir_px is not None
        and time.time() < _deadline
    ):
        _rr0, _cc0 = np.where(footprint)
        _cdist0 = float(np.hypot(np.mean(_rr0) - dam_r, np.mean(_cc0) - dam_c))
        _scale0 = max(1.0, np.sqrt(float(n_pixels)))
        _cratio0 = _cdist0 / _scale0
        _approx_v_rr = _approx_cone_volume_m3(n_pixels, pixel_area, spillway_height)
        _vol_short_rr = _approx_v_rr < 0.34 * capacity_m3 and capacity_m3 >= 2.5e6
        if (_cratio0 > 1.5 or _vol_short_rr) and n_pixels > 50:
            _river_up = -np.asarray(flow_dir_px, dtype=float)
            _rn = float(np.linalg.norm(_river_up))
            if _rn > 1e-9:
                _river_up /= _rn
                for _off_px in [3, 5, 8, 12, 16, 20]:
                    if time.time() > _deadline:
                        break
                    _nr = int(round(dam_r0 + _river_up[0] * _off_px))
                    _nc = int(round(dam_c0 + _river_up[1] * _off_px))
                    if not (0 <= _nr < dem_utm.shape[0] and 0 <= _nc < dem_utm.shape[1]):
                        continue
                    _nr, _nc, _ne = _snap_dam_elev(dem_utm, _nr, _nc)
                    if not np.isfinite(_ne):
                        continue
                    _res = _try_terrain_placement_once(
                        dem_utm, dem_tf, _nr, _nc, _ne,
                        dam_length_m, dam_height, spillway_height, capacity_m3,
                        pixel_area, flow_dir_px, wall_thickness, seed_dist,
                        deadline=_deadline,
                        **crest_kw,
                    )
                    if _res is not None:
                        _rfp, _rn_px, _ra, _rdr, _rdc, _rde = _res
                        _rrR, _ccR = np.where(_rfp)
                        _cdistR = float(np.hypot(np.mean(_rrR) - _rdr, np.mean(_ccR) - _rdc))
                        _scaleR = max(1.0, np.sqrt(float(_rn_px)))
                        _cratioR = _cdistR / _scaleR
                        _accept_rr = _cratioR < _cratio0 * 0.85
                        if not _accept_rr and _vol_short_rr:
                            _vR = _approx_cone_volume_m3(_rn_px, pixel_area, spillway_height)
                            _accept_rr = _vR >= _approx_v_rr * 0.5
                        if _accept_rr:
                            footprint, n_pixels, footprint_area_km2 = _rfp, _rn_px, _ra
                            dam_r, dam_c, dam_elev_out = _rdr, _rdc, _rde
                            placement_upstream_shift_m = float(_off_px) * pixel_size
                            placement_method = "stage_4_river_retry"
                            break

    # --- Stage 5: relaxed-alignment retry ---
    if footprint is None and time.time() < _deadline:
        _relax_kw = dict(
            prepend_angles_deg=[0, 90, 45, 135],
            prepend_bypass_flow_align=True,
        )
        relax_nom = _try_terrain_placement_once(
            dem_utm, dem_tf, dam_r0, dam_c0, dam_elev,
            dam_length_m, dam_height, spillway_height, capacity_m3, pixel_area,
            flow_dir_px, wall_thickness, seed_dist,
            deadline=_deadline,
            **_relax_kw,
        )
        if relax_nom is not None:
            footprint, n_pixels, footprint_area_km2, dam_r, dam_c, dam_elev_out = relax_nom
            placement_upstream_shift_m = 0.0
            placement_method = "stage_5_relaxed_alignment"
        elif time.time() < _deadline:
            out_r = search_terrain_wall_extended_upstream(
                dem_utm, dem_tf, dam_r0, dam_c0, dam_length_m,
                dam_height, spillway_height, capacity_m3, pixel_area, flow_dir_px,
                wall_thickness, seed_dist,
                skip_duplicate_nominal=True,
                deadline=_deadline,
                **_relax_kw,
            )
            fp_r, n_r, a_r, dr_r, dc_r, de_r, up_r = out_r
            if fp_r is not None:
                footprint, n_pixels, footprint_area_km2 = fp_r, n_r, a_r
                dam_r, dam_c, dam_elev_out = dr_r, dc_r, de_r
                placement_upstream_shift_m = up_r
                placement_method = "stage_5_relaxed_alignment"

    # --- Stage 6: fallback ---
    if footprint is None:
        dam_r, dam_c = dam_r0, dam_c0
        dam_elev = float(dem_utm[dam_r, dam_c])
        if np.isnan(dam_elev):
            dam_r, dam_c, dam_elev = _snap_dam_elev(dem_utm, dam_r, dam_c)
        z_spillway = dam_elev + spillway_height
        z_wall = dam_elev + dam_height
        footprint, n_pixels, footprint_area_km2 = fallback_multidirection_fill(
            dem_utm, dem_tf, dam_r, dam_c, dam_elev, z_spillway, z_wall,
            spillway_height, dam_height, capacity_m3, pixel_area,
            wall_thickness, seed_dist, area_cap_km2,
            flow_dir_px=flow_dir_px,
        )
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

    nan_in_footprint = np.isnan(dem_utm[footprint]).sum()
    void_fraction = nan_in_footprint / n_pixels if n_pixels > 0 else 0.0

    if void_fraction >= VOID_THRESHOLD:
        raise ValueError(f"srtm_voids: void_fraction={void_fraction:.3f}")

    dem_filled = dem_utm.copy()
    if nan_in_footprint > 0:
        dem_filled = interpolate_nans(dem_filled)

    dem_fp = np.where(footprint, dem_filled, np.nan)
    z_min = float(np.nanmin(dem_fp))
    z_max = z_spillway

    if z_max <= z_min:
        raise ValueError(f"z_max ({z_max:.1f}) <= z_min ({z_min:.1f})")

    elev_bins = np.arange(z_min, z_max + BIN_Z, BIN_Z)
    area_m2 = np.array([
        np.nansum(dem_fp <= z) * pixel_area for z in elev_bins
    ])
    vol_m3 = cumulative_trapezoid(area_m2, elev_bins, initial=0)

    CAP_FACTOR = 1.0
    vol_cap = CAP_FACTOR * capacity_m3
    capped = False
    if len(vol_m3) > 0 and vol_m3[-1] > vol_cap:
        cap_idx = np.searchsorted(vol_m3, vol_cap)
        if cap_idx < len(vol_m3) - 1:
            cap_idx = min(cap_idx + 1, len(vol_m3))
            elev_bins = elev_bins[:cap_idx]
            area_m2 = area_m2[:cap_idx]
            vol_m3 = vol_m3[:cap_idx]
            z_max = float(elev_bins[-1])
            footprint_area_km2 = float(area_m2[-1]) / 1e6
            footprint = footprint & (dem_filled <= z_max)
            n_pixels = int(footprint.sum())
            capped = True

    is_pre2000 = construction_year < 2000
    curve_type = "full"
    srtm_water_level = np.nan
    coverage_fraction = 1.0

    if is_pre2000:
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
        dem_utm.shape,
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
                f"(cdist={_cdist_qc:.0f} px, n_px={n_pixels}); fill displaced"
            )
    if n_pixels > 0 and capacity_m3 >= 1e6:
        _srtm_vol = float(vol_m3[-1]) if len(vol_m3) > 0 else 0.0
        _vol_frac = _srtm_vol / capacity_m3
        if _vol_frac < 0.20:
            _qc_reasons.append(
                f"Volume fraction {_vol_frac:.2f} < 0.20 "
                f"(~{_srtm_vol/1e6:.1f} vs {capacity_mcm:.1f} MCM); fill too small"
            )
    if _qc_reasons:
        raise ValueError("bad_fill_auto: " + "; ".join(_qc_reasons))

    return {
        "csv_id": csv_id,
        "construction_year": construction_year,
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
    }
