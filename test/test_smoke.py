"""Fast sanity checks, run by the continuous integration with the unit tier.

These tests exercise imports, settings loading, and value validation without
invoking the per-dam pipeline.
"""

from __future__ import annotations

import importlib
import json
import tempfile
from pathlib import Path

import pandas as pd
import pytest

import eaves.config as _cfg
from eaves.postprocess.external_data import add_sedimentation_columns
from eaves.postprocess.reliability import add_uncertainty_flags
from eaves.settings import load_settings

PACKAGE_MODULES = (
    "eaves",
    "eaves.cli",
    "eaves.config",
    "eaves.preprocess",
    "eaves.settings",
    "eaves.utils",
    "eaves.pipeline.curves",
    "eaves.pipeline.placement",
    "eaves.pipeline.terrain",
    "eaves.pipeline.workers",
    "eaves.postprocess.external_data",
    "eaves.postprocess.plots",
    "eaves.postprocess.regionalization",
    "eaves.postprocess.reliability",
)


def test_package_imports():
    """Every key module imports cleanly."""
    for module in PACKAGE_MODULES:
        importlib.import_module(module)


def test_test_settings_load(test_settings_path: Path):
    """The fixture's settings.json loads and populates expected path attributes."""
    load_settings(str(test_settings_path))
    for attr in (
        "OUTPUT_DIR", "SRTM_DIR", "DAMS_CSV", "WATER_EXTENT_DIR",
        "DOMAIN_DIR", "GRDL_DIR", "MERIT_RIVERS_SHP", "MERIT_BASINS_SHP",
    ):
        assert hasattr(_cfg, attr), f"{attr} not set after load_settings"
        assert isinstance(getattr(_cfg, attr), str) and getattr(_cfg, attr)


@pytest.mark.parametrize("override", [
    {"max_seg_len_m": -1},
    {"max_seg_len_m": 0},
    {"max_seg_len_m": "two kilometers"},
    {"max_seg_len_m": True},
    {"max_snap_distance_m": -500},
    {"target_country": ""},
    {"bathymetry_dam_id": "   "},
    {"country_name_col": 42},
])
def test_settings_rejects_malformed(test_settings_path: Path, override):
    """_validate_values fails loud on bad numeric or empty scalar inputs."""
    base = json.loads(test_settings_path.read_text())
    base.update(override)
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(base, f)
        tmp = Path(f.name)
    try:
        with pytest.raises(ValueError):
            load_settings(str(tmp))
    finally:
        tmp.unlink()


def test_settings_rejects_unknown_key(test_settings_path: Path):
    base = json.loads(test_settings_path.read_text())
    base["totally_invented_key"] = "oops"
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(base, f)
        tmp = Path(f.name)
    try:
        with pytest.raises(ValueError, match="unknown setting key"):
            load_settings(str(tmp))
    finally:
        tmp.unlink()


def test_uncertainty_flags_on_empty_df():
    """add_uncertainty_flags handles a 0-row DataFrame without crashing."""
    df = pd.DataFrame()
    out = add_uncertainty_flags(df)
    assert "uncertainty_flags" in out.columns
    assert "uncertainty_score" in out.columns


def test_sedimentation_merge_is_noop_when_unset():
    """add_sedimentation_columns is a no-op when sedimentation_dir is None."""
    df = pd.DataFrame({"dam_id": ["id_x", "id_y"]})
    out = add_sedimentation_columns(df, None)
    assert list(out.columns) == ["dam_id"]
