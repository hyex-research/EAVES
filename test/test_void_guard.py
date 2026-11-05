"""Gaps of the DEM that terrain encloses enter the fill at the height of their rim and count against the void threshold."""
import json

import numpy as np
import pandas as pd
import pytest
from pyproj import Transformer
from rasterio.transform import rowcol
from shapely.geometry import Point

from eaves.config import VOID_THRESHOLD
from eaves.pipeline.curves import DamRow, fill_enclosed_voids, process_dam
from eaves.pipeline.placement import flood_fill_8
from eaves.pipeline.terrain import load_srtm_tiles
from eaves.settings import load_settings
from eaves.utils import buffer_deg_for_dam, utm_epsg_from_lon


def _bowl(n=41, depth=10.0):
    """Paraboloid basin, 100 m at the center and 100 m + depth at the rim."""
    r, c = np.mgrid[0:n, 0:n] - n // 2
    return (100.0 + depth * (r ** 2 + c ** 2) / (n // 2) ** 2).astype(np.float32)


def _two_basins(n=61, crest=110.0, drop=0.9):
    """Ridge along the middle column, 110 m at the crest and falling 0.9 m per cell to either side."""
    c = np.abs(np.arange(n) - n // 2)
    return np.tile((crest - drop * c).astype(np.float32), (n, 1))


class TestFillEnclosedVoids:

    def test_complete_window_is_untouched(self):
        dem = _bowl()
        out, voids = fill_enclosed_voids(dem)
        assert out is dem
        assert not voids.any()

    def test_margin_stays_missing_and_gap_takes_its_rim(self):
        dem = _bowl()
        dem[:3, :] = np.nan
        dem[18:21, 18:21] = np.nan
        out, voids = fill_enclosed_voids(dem)
        assert voids.sum() == 9 and voids[18:21, 18:21].all()
        assert np.isnan(out[:3, :]).all()
        assert (out[18:21, 18:21] == np.nanmax(dem[17:22, 17:22])).all()
        assert np.isnan(dem[18:21, 18:21]).all()

    def test_gap_enters_the_fill_and_the_count(self):
        dem = _bowl()
        dem[18:21, 18:21] = np.nan
        hole = flood_fill_8(dem, 20, 24, 103.0)
        assert not hole[18:21, 18:21].any()
        out, voids = fill_enclosed_voids(dem)
        fp = flood_fill_8(out, 20, 24, 103.0)
        assert fp.sum() == hole.sum() + 9
        assert voids[fp].sum() == 9
        assert voids[fp].sum() / fp.sum() < VOID_THRESHOLD

    def test_large_gap_crosses_the_threshold(self):
        dem = _bowl()
        dem[16:23, 16:23] = np.nan
        out, voids = fill_enclosed_voids(dem)
        fp = flood_fill_8(out, 20, 24, 103.0)
        assert voids[fp].sum() == 49
        assert voids[fp].sum() / fp.sum() >= VOID_THRESHOLD

    def test_gap_over_a_divide_keeps_the_basins_apart(self):
        dem = _two_basins()
        dem[15:40, 22:39] = np.nan
        out, voids = fill_enclosed_voids(dem)
        assert (out[15:40, 22:39] == 110.0).all()
        fp = flood_fill_8(out, 27, 5, 103.0)
        assert fp[:, :23].any()
        assert not fp[:, 30:].any()
        assert not voids[fp].any()


@pytest.mark.slow
class TestGapInAFixtureWindow:
    """A gap cut into the SRTM window of a fixture dam at the centroid of its footprint."""

    @pytest.fixture(scope="class")
    def dam(self, test_settings_path):
        load_settings(str(test_settings_path))
        catalog = pd.read_csv(json.loads(test_settings_path.read_text())["dams_csv"])
        data = catalog[catalog["dam_id"] == "id_020002"].iloc[0].to_dict()
        lat, lon = float(data["latitude"]), float(data["longitude"])
        row = DamRow(data, Point(lon, lat))
        srtm, tf, crs = load_srtm_tiles(lat, lon, buffer_deg=buffer_deg_for_dam(float(data["storage_capacity_m3"])) + 0.02)
        clean = process_dam(row, None, srtm, tf, crs, override_lat=lat, override_lon=lon)
        rows, cols = np.nonzero(clean["footprint"])
        x, y = clean["dem_transform"] * (float(cols.mean()), float(rows.mean()))
        to_geo = Transformer.from_crs(f"EPSG:{utm_epsg_from_lon(lon)}", "EPSG:4326", always_xy=True)
        r, c = rowcol(tf, *to_geo.transform(x, y))
        return row, lat, lon, srtm, tf, crs, clean, (int(r), int(c))

    @staticmethod
    def _with_gap(srtm, center, half):
        r, c = center
        gapped = srtm.copy()
        gapped[r - half:r + half, c - half:c + half] = np.nan
        return gapped

    def test_small_gap_is_counted_and_filled(self, dam):
        row, lat, lon, srtm, tf, crs, clean, center = dam
        assert clean["void_fraction"] == 0.0
        result = process_dam(row, None, self._with_gap(srtm, center, 2), tf, crs, override_lat=lat, override_lon=lon)
        assert 0.0 < result["void_fraction"] < VOID_THRESHOLD
        assert not np.isnan(result["dem_utm"][result["footprint"]]).any()
        assert result["n_pixels"] >= 0.95 * clean["n_pixels"]

    def test_large_gap_fails_the_dam(self, dam):
        row, lat, lon, srtm, tf, crs, clean, center = dam
        with pytest.raises(ValueError, match="srtm_voids"):
            process_dam(row, None, self._with_gap(srtm, center, 6), tf, crs, override_lat=lat, override_lon=lon)
