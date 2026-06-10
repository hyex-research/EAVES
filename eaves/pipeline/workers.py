"""Per-dam multiprocessing workers.

One dam per call: load and reproject the SRTM tiles, extract topographic
features, run :func:`eaves.pipeline.curves.process_dam` (with a
snapped-coordinate fallback), write the per-dam EAV table and QC flood
map, and return a summary dict or a self-contained failure record.
Top-level functions so the spawn-context Pool can pickle them.
"""

from __future__ import annotations

import os

import numpy as np
import pandas as pd
import geopandas as gpd
from rasterio.transform import rowcol

import eaves.config as _cfg
from ..utils import (
    _get_placement_override,
    _ov_bool,
    utm_epsg_from_lon,
    buffer_deg_for_dam,
    _classify_failure,
)
from .terrain import (
    load_srtm_tiles,
    clip_and_reproject_dem,
    _extract_topo_features,
)
from .placement import _snap_dam_elev
from .curves import process_dam
from ..postprocess.plots import save_flood_map


class DamRow:
    """Lightweight stand-in for a GeoDataFrame row passed via multiprocessing."""
    def __init__(self, data, geom):
        self._data = data
        self.geometry = geom
    def __getitem__(self, key):
        return self._data[key]
    def get(self, key, default=None):
        return self._data.get(key, default)


def _catalogue_features(dam_data):
    """Catalogue-available features attached to every failure record.

    Returns the four catalogue/external columns that we can populate without
    running placement (capacity, dam height, spillway height, upstream catchment
    area). Non-numeric or missing values come through as NaN.
    """
    def _f(key):
        try:
            v = float(dam_data.get(key))
        except (TypeError, ValueError):
            return np.nan
        return v if np.isfinite(v) else np.nan
    sc = dam_data.get("storage_capacity_m3")
    try:
        cap_mcm = float(sc) / 1e6
        if not np.isfinite(cap_mcm):
            cap_mcm = np.nan
    except (TypeError, ValueError):
        cap_mcm = np.nan
    return {
        "capacity_mcm":        cap_mcm,
        "dam_height_m":        _f("dam_height_m"),
        "spillway_height_m":   _f("spillway_height_m"),
        "dam_length_m":        _f("dam_length_m"),
        "upstream_area_km2":   _f("upstream_area_km2"),
    }


def _process_dam_worker(dam_data, gdf_rivers_data):
    _cfg._srtm_cache = {}

    dam_id = dam_data.get("dam_id", "")
    dam_name_latin = dam_data.get("dam_name_latin", "")
    ov_early = _get_placement_override(dam_id)
    if _ov_bool(ov_early, "mark_placement_failed"):
        return None, {
            "dam_id": dam_id,
            "dam_name": dam_name_latin,
            "reason": "manual_skip",
            "detail": (
                "mark_placement_failed=1 in dam_placement_overrides.csv "
                "(QC: skip SRTM placement; catalogue/terrain not trustworthy for this site)."
            ),
            **_catalogue_features(dam_data),
        }

    from shapely.geometry import Point
    from pyproj import Transformer
    dam_geom = Point(dam_data["_lon"], dam_data["_lat"])
    dam_row = DamRow(dam_data, dam_geom)

    gdf_rivers = None
    if gdf_rivers_data is not None:
        gdf_rivers = gpd.GeoDataFrame.from_features(gdf_rivers_data)

    kml_lat = dam_data["_lat"]
    kml_lon = dam_data["_lon"]
    snapped_lat = dam_data.get("_snapped_lat", kml_lat)
    snapped_lon = dam_data.get("_snapped_lon", kml_lon)

    try:
        dam_height = float(dam_data["dam_height_m"])
        capacity_m3 = float(dam_data["storage_capacity_m3"])
        spillway_height = float(dam_data.get("spillway_height_m", dam_height * 0.75))
        if spillway_height <= 0:
            spillway_height = dam_height * 0.75
    except (ValueError, TypeError):
        return None, {
            "dam_id": dam_id,
            "dam_name": dam_name_latin,
            "reason": "missing_attributes",
            "detail": "Invalid dam_height_m or storage_capacity_m3",
            **_catalogue_features(dam_data),
        }

    buf_deg = buffer_deg_for_dam(capacity_m3)

    # --- Extract topo features ---
    topo_features = {
        "valley_width_m": np.nan, "valley_ratio": np.nan,
        "channel_slope": np.nan, "mean_catchment_slope": np.nan,
    }
    try:
        srtm_data_feat, srtm_tf_feat, srtm_crs_feat = load_srtm_tiles(
            kml_lat, kml_lon, buffer_deg=buf_deg + 0.02,
        )
        target_epsg = utm_epsg_from_lon(kml_lon)
        dem_utm_feat, dem_tf_feat, pixel_area_feat, _ = clip_and_reproject_dem(
            srtm_data_feat, srtm_tf_feat, srtm_crs_feat,
            kml_lat, kml_lon, buf_deg, target_epsg,
        )
        tr_feat = Transformer.from_crs("EPSG:4326", f"EPSG:{target_epsg}", always_xy=True)
        dx, dy = tr_feat.transform(kml_lon, kml_lat)
        dr, dc = rowcol(dem_tf_feat, dx, dy)
        dr, dc = int(dr), int(dc)
        if 0 <= dr < dem_utm_feat.shape[0] and 0 <= dc < dem_utm_feat.shape[1]:
            dr, dc, de = _snap_dam_elev(dem_utm_feat, dr, dc)
            if np.isfinite(de):
                ps = np.sqrt(pixel_area_feat)
                topo_features = _extract_topo_features(
                    dem_utm_feat, dr, dc, de, spillway_height, ps,
                )
    except Exception:
        pass

    # --- Flood fill with coordinate fallbacks ---
    coords_to_try = [(kml_lat, kml_lon, "kml")]
    if abs(snapped_lat - kml_lat) > 0.001 or abs(snapped_lon - kml_lon) > 0.001:
        coords_to_try.append((snapped_lat, snapped_lon, "snapped"))

    last_error = None
    for dam_lat, dam_lon, coord_type in coords_to_try:
        try:
            srtm_data, srtm_tf, srtm_crs = load_srtm_tiles(
                dam_lat, dam_lon, buffer_deg=buf_deg + 0.02
            )
            result = process_dam(dam_row, gdf_rivers, srtm_data, srtm_tf, srtm_crs,
                                 override_lat=dam_lat, override_lon=dam_lon)
            result.update(topo_features)
            result["dam_id"] = dam_id
            result["dam_name_latin"] = dam_name_latin

            eav_df = pd.DataFrame({
                "elevation_m": result["elev_bins"],
                "area_m2": result["area_m2"],
                "volume_m3": result["vol_m3"],
            })
            eav_df.to_csv(os.path.join(_cfg.EAV_DIR, f"{dam_id}_eav.csv"), index=False)

            try:
                save_flood_map(result, _cfg.FLOOD_DIR,
                               dam_id=dam_id, dam_name=dam_name_latin)
            except Exception:
                pass

            for src in _cfg._srtm_cache.values():
                try:
                    src.close()
                except Exception:
                    pass

            return result, None

        except Exception as e:
            last_error = e
            continue

    for src in _cfg._srtm_cache.values():
        try:
            src.close()
        except Exception:
            pass

    failure = {
        "dam_id": dam_id,
        "dam_name": dam_name_latin,
        "reason": _classify_failure(str(last_error)),
        "detail": str(last_error),
        **_catalogue_features(dam_data),
    }
    failure.update(topo_features)
    return None, failure


def _worker_indexed(args, gdf_rivers_data):
    """Return (list_index, result, failure) so parent can reorder results."""
    idx, dam_data = args
    result, failure = _process_dam_worker(dam_data, gdf_rivers_data)
    return idx, result, failure
