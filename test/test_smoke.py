"""Fast sanity checks — run on every push.

These tests exercise imports, settings loading, and value validation without
invoking the per-dam pipeline. Total runtime should stay well under a second.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from eaves.settings import load_settings
import eaves.config as _cfg


def test_package_imports():
    """All key modules must import cleanly."""
    import eaves                          # noqa: F401
    import eaves.cli                      # noqa: F401
    import eaves.config                   # noqa: F401
    import eaves.preprocess               # noqa: F401
    import eaves.settings                 # noqa: F401
    import eaves.utils                    # noqa: F401
    import eaves.pipeline.curves          # noqa: F401
    import eaves.pipeline.placement       # noqa: F401
    import eaves.pipeline.terrain         # noqa: F401
    import eaves.pipeline.workers         # noqa: F401
    import eaves.postprocess.external_data   # noqa: F401
    import eaves.postprocess.plots           # noqa: F401
    import eaves.postprocess.regionalization # noqa: F401
    import eaves.postprocess.reliability     # noqa: F401


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
    import pandas as pd
    from eaves.postprocess.reliability import add_uncertainty_flags
    df = pd.DataFrame()
    out = add_uncertainty_flags(df)
    assert "uncertainty_flags" in out.columns
    assert "uncertainty_score" in out.columns


def test_sedimentation_merge_is_noop_when_unset():
    """add_sedimentation_columns is a no-op when sedimentation_dir is None."""
    import pandas as pd
    from eaves.postprocess.external_data import add_sedimentation_columns
    df = pd.DataFrame({"dam_id": ["id_x", "id_y"]})
    out = add_sedimentation_columns(df, None)
    assert list(out.columns) == ["dam_id"]
