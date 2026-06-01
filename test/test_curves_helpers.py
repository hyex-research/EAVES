"""Unit tests for small pure helpers in :mod:`eaves.pipeline.curves`.

Currently covers construction-year parsing, which deliberately leaves an
unknown year as ``None`` (never the old fabricated 2001 sentinel).
"""

from __future__ import annotations

import numpy as np
import pytest

from eaves.pipeline.curves import _parse_construction_year


class TestParseConstructionYear:

    @pytest.mark.parametrize("raw,expected", [
        (2009, 2009),
        (2009.0, 2009),      # pandas hands numeric columns back as float
        ("2009", 2009),
        (1955, 1955),
    ])
    def test_numeric_values_parse_to_int(self, raw, expected):
        assert _parse_construction_year(raw) == expected

    @pytest.mark.parametrize("raw", [
        None,                # genuinely absent
        "",                  # blank cell
        "historical",        # non-numeric catalogue note
        np.nan,              # pandas NaN for a missing numeric cell
        "n/a",
    ])
    def test_missing_or_non_numeric_returns_none(self, raw):
        # The key regression guard: must be None, never the old 2001 sentinel.
        assert _parse_construction_year(raw) is None

    def test_never_returns_2001_sentinel_for_missing(self):
        for raw in (None, "", np.nan, "historical"):
            assert _parse_construction_year(raw) != 2001
