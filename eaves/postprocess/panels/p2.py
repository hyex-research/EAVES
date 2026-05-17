"""Panel set p2 — dam wall placement, three exemplars from the six-stage algorithm.

Panel a — Stage 1 fast path (King Fahad).
Panel b — Stage 4 river-direction retry (Hafar Al-Batin).
Panel c — Stage 6 synthetic fallback (Marat).
"""

from __future__ import annotations

import os
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LightSource
from matplotlib.patches import Patch

import eaves.config as _cfg

from ._shared import (
    COL_BASIN,
    COL_DAM,
    COL_LAND,
    COL_RIVER,
    COL_WALL,
    mm_to_in,
    panel_label,
    save_panel,
)


_EXPECTED_METHODS: dict[str, str] = {
    "a": "stage_1_fast_path",
    "b": "stage_4_river_retry",
    "c": "stage_6_fallback",
}

_STAGE_TITLES: dict[str, str] = {
    "a": "Stage 1: fast path",
    "b": "Stage 4: river-direction retry",
    "c": "Stage 6: multi-direction fallback",
}

# Preferred exemplar dam IDs (tried first; automatic ranking used as fallback).
_PINNED_EXEMPLARS: dict[str, str] = {
    "a": "id_070014",  # King Fahad Dam — Stage 1 fast path
    "b": "id_050001",  # Hafar Al-Batin Dam — Stage 4 river-direction retry
    "c": "id_010024",  # Marat Dam — Stage 6 synthetic fallback
}


def _candidate_pool(summary_df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Return ranked candidate DataFrames keyed by panel letter ('a','b','c').

    Selection rules (NATURE_FIG_SPEC.md §11f):
      a — Stage 1, quality A, height ≥ 20 m, vol_ratio in [0.8, 1.3].
      b — Stage 4; rank by height descending.
      c — Stage 6; rank by closeness of vol_ratio to 1.0.
    """
    mask_a = (
        (summary_df["placement_method"] == "stage_1_fast_path")
        & (summary_df["quality"] == "A")
        & (summary_df["dam_height_m"] >= 20)
        & (summary_df["vol_ratio"].between(0.8, 1.3))
    )
    cand_a = summary_df[mask_a].sort_values("dam_height_m", ascending=False)
    cand_b = (
        summary_df[summary_df["placement_method"] == "stage_4_river_retry"]
        .sort_values("dam_height_m", ascending=False)
    )
    cand_c_raw = summary_df[summary_df["placement_method"] == "stage_6_fallback"]
    cand_c = (
        cand_c_raw
        .assign(_vol_dist=(cand_c_raw["vol_ratio"] - 1.0).abs())
        .sort_values("_vol_dist")
    )
    return {"a": cand_a, "b": cand_b, "c": cand_c}


class _DamRow:
    """Lightweight stand-in for a GeoDataFrame row passed to ``process_dam``."""
    def __init__(self, data, geom):
        self._d = data
        self.geometry = geom

    def __getitem__(self, key):
        return self._d[key]

    def get(self, key, default=None):
        return self._d.get(key, default)


def _compute_placement_result(dam_id: str, gdf_dams: gpd.GeoDataFrame,
                              gdf_rivers: gpd.GeoDataFrame) -> dict:
    """Re-run the placement pipeline for ``dam_id`` and return the result dict."""
    from ...pipeline.curves import process_dam
    from ...pipeline.terrain import load_srtm_tiles
    from ...utils import buffer_deg_for_dam

    sub = gdf_dams[gdf_dams["dam_id"] == dam_id]
    if sub.empty:
        raise RuntimeError(f"Dam {dam_id!r} missing from snapped GeoDataFrame.")
    g = sub.iloc[0]

    dam_dict = {col: g[col] for col in g.index if col != "geometry"}
    dam_dict["_lat"] = float(g["latitude"])
    dam_dict["_lon"] = float(g["longitude"])
    dam_dict["_snapped_lat"] = float(g.geometry.y)
    dam_dict["_snapped_lon"] = float(g.geometry.x)
    dam_dict["dam_id"] = dam_id
    dam_dict["storage_capacity_m3"] = float(g["storage_capacity_m3"])
    dam_row = _DamRow(dam_dict, g.geometry)

    coords_to_try = [
        (float(g["latitude"]), float(g["longitude"]), "kml"),
        (float(g.geometry.y), float(g.geometry.x), "snapped"),
    ]
    buf_deg = buffer_deg_for_dam(float(g["storage_capacity_m3"]))

    last_error = None
    for lat, lon, _tag in coords_to_try:
        try:
            srtm_data, srtm_tf, srtm_crs = load_srtm_tiles(
                lat, lon, buffer_deg=buf_deg + 0.02,
            )
            result = process_dam(
                dam_row, gdf_rivers, srtm_data, srtm_tf, srtm_crs,
                override_lat=lat, override_lon=lon,
            )
            for src in getattr(_cfg, "_srtm_cache", {}).values():
                try:
                    src.close()
                except Exception:
                    pass
            _cfg._srtm_cache = {}
            return result
        except Exception as exc:
            last_error = exc
            continue
    raise RuntimeError(f"All placement attempts failed for {dam_id!r}: {last_error}")


def _dem_extent_m(dem_transform, dem_shape: tuple) -> tuple[float, float, float, float]:
    """Return (left, right, bottom, top) in DEM CRS metres for ``imshow``."""
    h, w = dem_shape
    left = dem_transform.c
    top = dem_transform.f
    pix_x = abs(dem_transform.a)
    pix_y = abs(dem_transform.e)
    return left, left + w * pix_x, top - h * pix_y, top


def _xy_from_rc(rows, cols, dem_transform) -> tuple[np.ndarray, np.ndarray]:
    """Convert pixel (row, col) arrays to (x, y) in DEM CRS."""
    pix_x = abs(dem_transform.a)
    pix_y = abs(dem_transform.e)
    x = dem_transform.c + (np.asarray(cols, float) + 0.5) * pix_x
    y = dem_transform.f - (np.asarray(rows, float) + 0.5) * pix_y
    return x, y


def _clip_rivers_to_bbox(gdf_rivers: gpd.GeoDataFrame, bbox_lonlat: tuple,
                         target_epsg: int) -> gpd.GeoDataFrame:
    """Clip MERIT polylines to a lon/lat bounding box and reproject to UTM."""
    from shapely.geometry import box as _shp_box
    if gdf_rivers is None or gdf_rivers.empty:
        return gpd.GeoDataFrame(geometry=[], crs=f"EPSG:{target_epsg}")
    poly = _shp_box(*bbox_lonlat)
    candidate_idx = list(gdf_rivers.sindex.intersection(poly.bounds))
    if not candidate_idx:
        return gpd.GeoDataFrame(geometry=[], crs=f"EPSG:{target_epsg}")
    candidates = gdf_rivers.iloc[candidate_idx]
    candidates = candidates[candidates.intersects(poly)]
    if candidates.empty:
        return candidates.to_crs(f"EPSG:{target_epsg}")
    return candidates.clip(poly).to_crs(f"EPSG:{target_epsg}")


def _footprint_to_polygon_patches(footprint_mask: np.ndarray,
                                  dem_transform) -> list[np.ndarray]:
    """Return XY polygon arrays (DEM CRS) outlining the flooded-basin mask."""
    fig_aux, ax_aux = plt.subplots()
    try:
        rows = np.arange(footprint_mask.shape[0])
        cols = np.arange(footprint_mask.shape[1])
        cs = ax_aux.contour(cols, rows, footprint_mask.astype(float), levels=[0.5])
        polys: list[np.ndarray] = []
        for level_segs in cs.allsegs:
            for seg in level_segs:
                if len(seg) < 4:
                    continue
                x, y = _xy_from_rc(seg[:, 1], seg[:, 0], dem_transform)
                polys.append(np.column_stack([x, y]))
    finally:
        plt.close(fig_aux)
    return polys


def _render_placement_panel(ax, result: dict, *, dam_name: str,
                            letter: str, gdf_rivers_lonlat: gpd.GeoDataFrame,
                            cat_lat: float, cat_lon: float,
                            snap_lat: float, snap_lon: float,
                            target_epsg: int,
                            panel_extent_m: float = 4000.0) -> None:
    """Render one placement panel: hillshade + wall + flooded basin + rivers."""
    from pyproj import Transformer

    dem = np.asarray(result["dem_utm"], dtype=float)
    dem_tf = result["dem_transform"]
    fp = np.asarray(result["footprint"], dtype=bool)
    dam_r, dam_c = result["dam_rc"]
    pixel_size_m = float(result["pixel_size"])

    full_left, full_right, full_bottom, full_top = _dem_extent_m(dem_tf, dem.shape)

    # Centre window on midpoint between catalogue dam and accepted wall pixel.
    tr_fwd = Transformer.from_crs("EPSG:4326", f"EPSG:{target_epsg}", always_xy=True)
    tr_back = Transformer.from_crs(f"EPSG:{target_epsg}", "EPSG:4326", always_xy=True)
    cat_x, cat_y = tr_fwd.transform(cat_lon, cat_lat)
    wall_x = dem_tf.c + (dam_c + 0.5) * abs(dem_tf.a)
    wall_y = dem_tf.f - (dam_r + 0.5) * abs(dem_tf.e)
    centre_x = 0.5 * (cat_x + wall_x)
    centre_y = 0.5 * (cat_y + wall_y)

    half = float(panel_extent_m)
    win_left, win_right = centre_x - half, centre_x + half
    win_bottom, win_top = centre_y - half, centre_y + half

    # Gainsboro land base + LightSource hillshade overlay at alpha=0.45.
    ax.set_facecolor(COL_LAND)
    ls = LightSource(azdeg=315, altdeg=45)
    dem_for_shade = np.where(np.isnan(dem), np.nanmean(dem), dem)
    intensity = ls.hillshade(dem_for_shade, vert_exag=1.5,
                             dx=max(pixel_size_m, 1.0), dy=max(pixel_size_m, 1.0))
    if np.isnan(dem).any():
        intensity = np.where(np.isnan(dem), 0.5, intensity)
    ax.imshow(intensity, extent=(full_left, full_right, full_bottom, full_top),
              origin="upper", cmap="gray", vmin=0.0, vmax=1.0, alpha=0.45,
              interpolation="bilinear", zorder=1)

    # Flooded basin (filled polygon + outline).
    for poly_xy in _footprint_to_polygon_patches(fp, dem_tf):
        ax.fill(poly_xy[:, 0], poly_xy[:, 1],
                facecolor=COL_BASIN, alpha=0.45, edgecolor="none", zorder=3)
        ax.plot(poly_xy[:, 0], poly_xy[:, 1],
                color=COL_BASIN, alpha=0.85, lw=0.8, zorder=4)

    # MERIT rivers within the panel window.
    if gdf_rivers_lonlat is not None and not gdf_rivers_lonlat.empty:
        corners_x = [win_left, win_right, win_right, win_left]
        corners_y = [win_bottom, win_bottom, win_top, win_top]
        lons, lats = tr_back.transform(corners_x, corners_y)
        rivers_utm = _clip_rivers_to_bbox(
            gdf_rivers_lonlat,
            (min(lons), min(lats), max(lons), max(lats)),
            target_epsg,
        )
        if not rivers_utm.empty:
            order_col = "order" if "order" in rivers_utm.columns else None
            for _, riv in rivers_utm.iterrows():
                if riv.geometry is None or riv.geometry.is_empty:
                    continue
                lw = 0.4
                if order_col is not None:
                    try:
                        lw = float(np.clip(0.35 + 0.18 * int(riv.get(order_col)),
                                           0.4, 0.9))
                    except (TypeError, ValueError):
                        pass
                geoms = (
                    [riv.geometry] if riv.geometry.geom_type == "LineString"
                    else list(riv.geometry.geoms)
                )
                for line in geoms:
                    xs_l, ys_l = zip(*list(line.coords))
                    ax.plot(xs_l, ys_l, color=COL_RIVER, lw=lw,
                            solid_capstyle="round", zorder=2)

    # Accepted wall (black halo + amber core for contrast on any hillshade).
    wall_vec = result.get("wall_vec")
    eff_length_m = result.get("eff_length_m")
    if wall_vec is not None and eff_length_m and pixel_size_m:
        half_len_px = (float(eff_length_m) / pixel_size_m) / 2.0
        wr, wc = wall_vec
        x_wall, y_wall = _xy_from_rc(
            np.array([dam_r - wr * half_len_px, dam_r + wr * half_len_px]),
            np.array([dam_c - wc * half_len_px, dam_c + wc * half_len_px]),
            dem_tf,
        )
        ax.plot(x_wall, y_wall, color="black", lw=4.0,
                solid_capstyle="round", zorder=5)
        ax.plot(x_wall, y_wall, color=COL_WALL, lw=2.6,
                solid_capstyle="round", zorder=6)

    # Catalogue dam location (red star) and MERIT-snapped node (if offset).
    ax.scatter([cat_x], [cat_y], marker="*", s=85,
               facecolor=COL_DAM, edgecolor="white", linewidth=0.8, zorder=7)
    snap_x, snap_y = tr_fwd.transform(snap_lon, snap_lat)
    if abs(cat_x - snap_x) > pixel_size_m or abs(cat_y - snap_y) > pixel_size_m:
        ax.scatter([snap_x], [snap_y], marker="v", s=28,
                   facecolor="white", edgecolor="black", linewidth=0.4, zorder=7)

    # Window + axes cosmetics (geographic degree tick labels).
    ax.set_xlim(win_left, win_right)
    ax.set_ylim(win_bottom, win_top)
    ax.set_aspect("equal")
    ax.tick_params(labelsize=8.5, direction="out", length=2.5, pad=1.5)

    def _lon_fmt(val, _pos):
        lon, _ = tr_back.transform(val, centre_y)
        return f"{lon:.2f}"

    def _lat_fmt(val, _pos):
        _, lat = tr_back.transform(centre_x, val)
        return f"{lat:.2f}"

    ax.xaxis.set_major_formatter(plt.FuncFormatter(_lon_fmt))
    ax.yaxis.set_major_formatter(plt.FuncFormatter(_lat_fmt))
    ax.set_xticks([centre_x])
    ax.set_yticks([centre_y])
    ax.set_xlabel("Longitude (°E)", fontsize=10)
    ax.set_ylabel("Latitude (°N)" if letter == "a" else "", fontsize=10)

    panel_label(ax, letter, y_offset_pt=22.0, fontsize=12)
    ax.set_title(_STAGE_TITLES[letter], fontsize=10, pad=4, loc="left")

    # Dam name, top-right corner (name only — no dam_id).
    if dam_name:
        ax.text(0.98, 0.97, dam_name, transform=ax.transAxes,
                fontsize=10, ha="right", va="top",
                bbox=dict(facecolor="white", alpha=0.85, edgecolor="none", pad=1.5),
                zorder=8)


def _placement_legend(fig) -> None:
    """Shared figure-level legend below all three placement panels."""
    handles = [
        plt.Line2D([0], [0], marker="*", linestyle="none",
                   markerfacecolor=COL_DAM, markeredgecolor="white",
                   markersize=8, label="catalogue dam"),
        plt.Line2D([0], [0], color=COL_WALL, lw=2.0, label="accepted wall"),
        Patch(facecolor=COL_BASIN, edgecolor=COL_BASIN, alpha=0.55,
              label="flooded basin"),
        plt.Line2D([0], [0], color=COL_RIVER, lw=0.9, label="MERIT river"),
    ]
    fig.legend(
        handles=handles, loc="lower center", bbox_to_anchor=(0.5, 0.01),
        ncol=4, frameon=False, handlelength=1.6, handletextpad=0.6,
        columnspacing=2.0, borderaxespad=0.0, fontsize=10,
    )


def _select_with_reproducibility(letter: str, candidates: pd.DataFrame,
                                 gdf_dams: gpd.GeoDataFrame,
                                 gdf_rivers: gpd.GeoDataFrame,
                                 max_attempts: int = 5,
                                 ) -> tuple[str, pd.Series, dict]:
    """Pick the first candidate whose placement re-run reproduces the expected stage.

    Falls back to the first successful placement if no candidate matches, so
    the figure still renders rather than aborts.
    """
    expected = _EXPECTED_METHODS[letter]
    if candidates.empty:
        raise RuntimeError(f"No CSV candidates for panel {letter} ({expected}).")
    first_success: tuple[str, pd.Series, dict] | None = None
    last_exc: Exception | None = None
    for _, row in candidates.head(max_attempts).iterrows():
        dam_id = str(row["dam_id"])
        try:
            print(f"[p2] panel {letter}: trying {dam_id} (expects {expected})")
            result = _compute_placement_result(dam_id, gdf_dams, gdf_rivers)
        except Exception as exc:
            print(f"[p2]   {dam_id}: placement raised {exc}; trying next.")
            last_exc = exc
            continue
        method = result.get("placement_method", "")
        print(f"[p2]   {dam_id}: produced {method}")
        if first_success is None:
            first_success = (dam_id, row, result)
        if method == expected:
            return dam_id, row, result
    if first_success is not None:
        dam_id, row, result = first_success
        method = result.get("placement_method", "?")
        print(
            f"[p2] WARNING panel {letter}: no candidate reproduced "
            f"{expected!r}; falling back to {dam_id} ({method!r})."
        )
        return first_success
    raise RuntimeError(
        f"All {min(max_attempts, len(candidates))} candidates for panel "
        f"{letter} failed: {last_exc}"
    )


def make_p2_placement(output_dir: str | os.PathLike) -> Path:
    """Render p2 (dam wall placement, 1×3 panels). Returns the PNG path."""
    from ...utils import utm_epsg_from_lon

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_png = out_dir / "p2_placement.png"

    summary_df = pd.read_csv(Path(_cfg.CSV_DIR) / "eaves_summary.csv")
    pools = _candidate_pool(summary_df)

    # Prepend pinned exemplars so _select_with_reproducibility tries them first.
    for letter, pinned_id in _PINNED_EXEMPLARS.items():
        pin_rows = summary_df[summary_df["dam_id"] == pinned_id]
        if not pin_rows.empty:
            pools[letter] = pd.concat(
                [pin_rows, pools[letter]], ignore_index=True
            ).drop_duplicates("dam_id")

    gdf_dams = gpd.read_file(Path(_cfg.DOMAIN_DIR) / "dams_snapped.geojson")
    rivers_path = Path(_cfg.DOMAIN_DIR) / "rivers_split.geojson"
    gdf_rivers = gpd.read_file(rivers_path) if rivers_path.exists() else None
    catalogue = pd.read_csv(_cfg.DAMS_CSV)

    exemplars: dict = {}
    results: dict = {}
    for letter in ("a", "b", "c"):
        dam_id, sum_row, result = _select_with_reproducibility(
            letter, pools[letter], gdf_dams, gdf_rivers,
        )
        exemplars[letter] = (dam_id, sum_row)
        results[letter] = result

    # Uniform 10 pt text across every element; panel labels overridden to 12.
    rc_override = {
        "font.size":       10,
        "axes.labelsize":  10,
        "axes.titlesize":  10,
        "xtick.labelsize": 10,
        "ytick.labelsize": 10,
        "legend.fontsize": 10,
    }
    rc_stack = plt.rc_context(rc_override)
    rc_stack.__enter__()

    fig, axes = plt.subplots(
        nrows=1, ncols=3,
        figsize=(mm_to_in(220.0), mm_to_in(100.0)),
        constrained_layout=False,
    )

    def _half_m_from_area(km2: float) -> float:
        radius_m = np.sqrt(max(float(km2), 0.05) * 1e6 / np.pi)
        return float(np.clip(2.5 * radius_m, 1500.0, 3000.0))

    panel_half_m = {
        lt: _half_m_from_area(float(exemplars[lt][1]["footprint_area_km2"]))
        for lt in ("a", "b", "c")
    }

    for letter, ax in zip(["a", "b", "c"], axes):
        dam_id, sum_row = exemplars[letter]
        result = results[letter]
        cat_row = catalogue[catalogue["dam_id"] == dam_id]
        if cat_row.empty:
            cat_lat = float(sum_row["lat"])
            cat_lon = float(sum_row["lon"])
            dam_name = ""
        else:
            cat_lat = float(cat_row.iloc[0]["latitude"])
            cat_lon = float(cat_row.iloc[0]["longitude"])
            dam_name = str(cat_row.iloc[0].get("dam_name", "")).strip()
        snap_row = gdf_dams[gdf_dams["dam_id"] == dam_id]
        if not snap_row.empty:
            snap_lon = float(snap_row.iloc[0].geometry.x)
            snap_lat = float(snap_row.iloc[0].geometry.y)
        else:
            snap_lon, snap_lat = cat_lon, cat_lat
        _render_placement_panel(
            ax, result,
            dam_name=dam_name,
            letter=letter,
            gdf_rivers_lonlat=gdf_rivers,
            cat_lat=cat_lat, cat_lon=cat_lon,
            snap_lat=snap_lat, snap_lon=snap_lon,
            target_epsg=utm_epsg_from_lon(cat_lon),
            panel_extent_m=panel_half_m[letter],
        )

    _placement_legend(fig)
    plt.subplots_adjust(left=0.05, right=0.99, top=0.85, bottom=0.18, wspace=0.30)

    save_panel(fig, out_png)
    plt.close(fig)
    rc_stack.__exit__(None, None, None)
    print(f"wrote {out_png}")
    return out_png
