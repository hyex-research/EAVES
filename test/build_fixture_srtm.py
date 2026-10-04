"""Build the clipped SRTM set of the 15-dam fixture.

For every SRTM tile the pipeline opens for a fixture dam, the script writes a
file of the same name, grid, georeference, data type and nodata value. Cells
inside the window the pipeline loads around a dam keep their elevation, and
every other cell holds the nodata value. The files are deflate-compressed
GeoTIFFs that carry the ``.hgt`` tile name, which GDAL opens by content.

Run from the repository root::

    python -m test.build_fixture_srtm --srtm-dir <full SRTM folder>
"""

from __future__ import annotations

import argparse
import os

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.transform import rowcol

from eaves.utils import buffer_deg_for_dam, srtm_tile_name

# Margin the pipeline adds to the dam buffer when it loads tiles
LOADER_MARGIN_DEG = 0.02
# Extra cells kept around every window
PAD_CELLS = 4
FIXTURE_INPUT = os.path.join("test", "fixture", "input")
DAMS_SNAPPED = os.path.join(FIXTURE_INPUT, "domain_inputs", "dams_snapped.geojson")
OUT_DIR = os.path.join(FIXTURE_INPUT, "srtm")


def dam_windows(dams_path):
    """Return ``(dam_id, lat, lon, half_width_deg)`` for the catalog and the snapped coordinate of every dam."""
    gdf = gpd.read_file(dams_path)
    windows = []
    for _, dam in gdf.iterrows():
        half = buffer_deg_for_dam(float(dam["storage_capacity_m3"])) + LOADER_MARGIN_DEG
        windows.append((dam["dam_id"], float(dam["latitude"]), float(dam["longitude"]), half))
        windows.append((dam["dam_id"], float(dam.geometry.y), float(dam.geometry.x), half))
    return windows


def tiles_for_window(lat, lon, half):
    """Return the tile names the loader opens for one window."""
    names = []
    for la in np.arange(np.floor(lat - half), np.floor(lat + half) + 1):
        for lo in np.arange(np.floor(lon - half), np.floor(lon + half) + 1):
            names.append(srtm_tile_name(la, lo))
    return names


def build(srtm_dir, out_dir, dams_path):
    per_tile = {}
    for dam_id, lat, lon, half in dam_windows(dams_path):
        for name in tiles_for_window(lat, lon, half):
            per_tile.setdefault(name, []).append((dam_id, lat, lon, half))

    os.makedirs(out_dir, exist_ok=True)
    total_bytes = 0
    for name in sorted(per_tile):
        src_path = os.path.join(srtm_dir, name)
        # The loader skips a tile that is absent from the archive
        if not os.path.isfile(src_path):
            print(f"{name}: absent from the archive, skipped")
            continue
        with rasterio.open(src_path) as src:
            data = src.read(1)
            transform = src.transform
            crs = src.crs
            nodata = src.nodata
            dtype = src.dtypes[0]
        keep = np.zeros(data.shape, dtype=bool)
        for _, lat, lon, half in per_tile[name]:
            row_top, col_left = rowcol(transform, lon - half, lat + half)
            row_bot, col_right = rowcol(transform, lon + half, lat - half)
            r0 = max(0, min(row_top, row_bot) - PAD_CELLS)
            r1 = min(data.shape[0], max(row_top, row_bot) + 1 + PAD_CELLS)
            c0 = max(0, min(col_left, col_right) - PAD_CELLS)
            c1 = min(data.shape[1], max(col_left, col_right) + 1 + PAD_CELLS)
            if r1 > r0 and c1 > c0:
                keep[r0:r1, c0:c1] = True
        clipped = np.where(keep, data, np.asarray(nodata, dtype=dtype)).astype(dtype)

        out_path = os.path.join(out_dir, name)
        profile = {
            "driver": "GTiff",
            "height": data.shape[0],
            "width": data.shape[1],
            "count": 1,
            "dtype": dtype,
            "crs": crs,
            "transform": transform,
            "nodata": nodata,
            "compress": "DEFLATE",
            "predictor": 2,
            "zlevel": 9,
            "tiled": True,
            "blockxsize": 256,
            "blockysize": 256,
        }
        with rasterio.open(out_path, "w", **profile) as dst:
            dst.write(clipped, 1)
        size = os.path.getsize(out_path)
        total_bytes += size
        dams = sorted({w[0] for w in per_tile[name]})
        print(f"{name}: {int(keep.sum()):>8d} cells kept, {size / 1e6:6.3f} MB, dams {', '.join(dams)}")
    print(f"total: {len(os.listdir(out_dir))} files, {total_bytes / 1e6:.3f} MB")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--srtm-dir", required=True, help="Folder with the full SRTM GL1 .hgt tiles.")
    parser.add_argument("--out-dir", default=OUT_DIR, help="Folder that receives the clipped tiles.")
    parser.add_argument("--dams", default=DAMS_SNAPPED, help="Cached dam geometry of the fixture (dams_snapped.geojson).")
    args = parser.parse_args()
    build(args.srtm_dir, args.out_dir, args.dams)


if __name__ == "__main__":
    main()
