"""Formatting helpers of the report and the survey-date settings key."""

import json

import pytest

from eaves.postprocess.report import _pctfmt, _updown
from eaves.settings import load_settings


def test_pctfmt_keeps_one_decimal_short_of_full():
    assert _pctfmt(220 / 221) == "99.5%"
    assert _pctfmt(1.0) == "100%"
    assert _pctfmt(0.5) == "50%"
    assert _pctfmt(1.3) == "2.3×"


def test_updown_signs_only_percentages():
    assert _updown(0.48, 0.33) == "+48% / -33%"
    assert _updown(1.3, 0.5) == "2.3× / -50%"


def test_survey_date_key_is_validated(tmp_path):
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"bathymetry_survey_date": "2025-02"}))
    assert load_settings(str(good))["bathymetry_survey_date"] == "2025-02"
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"bathymetry_survey_date": "Feb 2025"}))
    with pytest.raises(ValueError):
        load_settings(str(bad))
