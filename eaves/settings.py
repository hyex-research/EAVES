"""JSON settings loader -> :func:`eaves.config.configure`.

A settings file is a flat JSON object whose keys are a subset of the kwargs
accepted by :func:`eaves.config.configure`. Unknown keys raise ``ValueError``
so typos in a settings file fail loudly rather than silently reverting to
defaults.

Usage::

    from eaves.settings import load_settings
    load_settings("settings/<country>.json")
"""

from __future__ import annotations

import json
import os

from .config import configure


_ALLOWED_KEYS = {
    "output_dir",
    "srtm_dir",
    "dams_csv",
    "water_extent_dir",
    "domain_dir",
    "merit_rivers_shp",
    "merit_basins_shp",
    "country_shp",
    "target_country",
    "country_name_col",
    "bathymetry_eav_csv",
    "bathymetry_dam_id",
    "grdl_dir",
    "sedimentation_dir",
    "max_seg_len_m",
    "max_snap_distance_m",
}

_POSITIVE_NUMERIC_KEYS = {"max_seg_len_m", "max_snap_distance_m"}
_NON_EMPTY_STRING_KEYS = {"target_country", "country_name_col", "bathymetry_dam_id"}


def load_settings(path: str) -> dict:
    """Read a settings JSON file and apply it via :func:`configure`.

    Returns the parsed settings dict (useful for logging).
    """
    with open(path, "r") as f:
        settings = json.load(f)

    if not isinstance(settings, dict):
        raise ValueError(f"{path}: expected a JSON object, got {type(settings).__name__}")

    unknown = set(settings) - _ALLOWED_KEYS
    if unknown:
        raise ValueError(
            f"{path}: unknown setting key(s): {sorted(unknown)}. "
            f"Allowed keys: {sorted(_ALLOWED_KEYS)}"
        )

    _validate_values(path, settings)

    base = os.path.dirname(os.path.abspath(path))
    resolved = {k: _resolve_path(v, base, k) for k, v in settings.items()}
    configure(**resolved)
    return resolved


def _validate_values(path: str, settings: dict) -> None:
    """Raise ``ValueError`` for malformed numeric knobs or empty scalar strings."""
    for key in _POSITIVE_NUMERIC_KEYS & settings.keys():
        v = settings[key]
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not v > 0:
            raise ValueError(f"{path}: {key!r} must be a positive number, got {v!r}")
    for key in _NON_EMPTY_STRING_KEYS & settings.keys():
        v = settings[key]
        if not isinstance(v, str) or not v.strip():
            raise ValueError(f"{path}: {key!r} must be a non-empty string, got {v!r}")


def _resolve_path(value, base: str, key: str):
    """Expand ``~`` and make relative filesystem-like values absolute to ``base``.

    Non-path scalars (``target_country``, ``country_name_col``, numeric knobs)
    pass through untouched.
    """
    if not isinstance(value, str):
        return value
    if key in {"target_country", "country_name_col", "bathymetry_dam_id"}:
        return value
    expanded = os.path.expanduser(value)
    if os.path.isabs(expanded):
        return expanded
    return os.path.normpath(os.path.join(base, expanded))
