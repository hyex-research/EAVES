"""
Tests for ``eaves.agent.info``, the machine-readable view behind the MCP server.

They build a small synthetic output tree of three dams in a temporary folder,
with the settings of the fixture pointed at it, and the JSON twin of its domain
characterization through the writer of the report step. They do NOT read the
outputs of a real run.
"""

from __future__ import annotations

import importlib
import json
import re
from pathlib import Path

import pytest

import eaves.config as _cfg
from eaves.agent import info
from eaves.config import configure
from eaves.postprocess import report

from .conftest import REPO_ROOT, TEST_SETTINGS

PARAMS_CSV = (
    "dam_id,dam_name,capacity_mcm,c,b,source\n"
    "id_010000,Wadi Alpha,0.08,0.007043,1.5065,regi_multi\n"
    "id_010001,Tamir,0.0615,0.1008,1.2084,srtm_derived\n"
    "id_120000,Baish,193.6,0.0204,1.6,srtm_derived\n"
)
SUMMARY_CSV = (
    "dam_id,dam_name,construction_year,capacity_mcm,c,b,r_squared,n_pixels,capped,quality,uncertainty_flags,uncertainty_score,lat,lon\n"
    "id_010000,Wadi Alpha,1970,0.08,,,,,,,,,24.757882,46.527667\n"
    "id_010001,Tamir,2008,0.0615,0.1008,1.2084,0.9905,34,True,A,height_noise;pre_srtm,2,24.1,45.2\n"
    "id_120000,Baish,2010,193.6,0.0204,1.6,0.98,5000,False,B,,0,17.5,42.6\n"
)
FAILED_CSV = (
    "dam_id,dam_name,reason,detail,capacity_mcm\n"
    "id_010000,Wadi Alpha,placement_failed,placement_failed: no valid flood fill,0.08\n"
)
STATISTICS = {
    "region": "Testland",
    "reference_year": 2026,
    "n_dams_with_params": 3,
    "b_regionalized": 1.50654321,
    "capacity_total_mcm": 193.7415,
    "b_cluster_best_set": "raw morphometry",
    "fill_median": float("nan"),
}
MISSING = object()


def _write(path: Path, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _settings_file(folder: Path, **changes) -> Path:
    """Write the settings of the fixture into a folder with output_dir pointed at its output/ subfolder, and return the file."""
    settings = {**json.loads(TEST_SETTINGS.read_text()), "output_dir": "output", **changes}
    path = folder / "settings.json"
    _write(path, json.dumps({key: value for key, value in settings.items() if value is not MISSING}))
    return path


@pytest.fixture
def settings(tmp_path) -> Path:
    """Settings file of a run with its tables, two EAV tables, three check maps, two validation tables, one panel and the domain characterization with its JSON twin."""
    path = _settings_file(tmp_path)
    out = tmp_path / "output"
    _write(out / info.TABLES["eaves_params"][0], PARAMS_CSV)
    _write(out / info.TABLES["eaves_summary"][0], SUMMARY_CSV)
    _write(out / info.TABLES["failed_dams"][0], FAILED_CSV)
    for dam_id in ("id_010001", "id_120000"):
        _write(out / info.EAV_TABLE.format(dam_id=dam_id), "elevation_m,depth_m,area_m2,volume_m3\n257.5,0.0,907.57,0.0\n")
        _write(out / "0_check_dams" / f"{dam_id}_srtm.png")
    _write(out / "0_check_dams" / "id_010000_regi.png")
    _write(out / info.VALIDATION_TABLES["regionalization_loo"][0], "dam_id\n")
    _write(out / info.UNCERTAINTY_TABLE[0], "dam_id\n")
    _write(out / "2_results_plots" / "p1_domain_flowchart.png")
    csv_path = out / info.TABLES["domain_characterization"][0]
    report.write_characterization_csv(STATISTICS, csv_path)
    report.write_characterization_json(csv_path)
    return path


def _catalog_paths() -> set[str]:
    return {
        *(rel for rel, _ in info.TABLES.values()),
        *(rel for rel, _ in info.VALIDATION_TABLES.values()),
        info.UNCERTAINTY_TABLE[0],
        *(f"{info.LAYOUT['2_results_plots']}/{stem}.png" for stem in info.PANELS),
        info.REPORT[0],
        info.EAV_TABLE,
        info.CHECK_PLOT,
    }


# ---- Step catalog ----

def test_steps_follow_run_all_in_order() -> None:
    script = (REPO_ROOT / "run_all.sh").read_text()
    commands = re.findall(r"^python -m (eaves\S*) (.*)$", script, flags=re.MULTILINE)
    assert [s["step"] for s in info.steps()] == [1, 2, 3, 4, 5]
    assert [s["module"] for s in info.steps()] == [module for module, _ in commands]
    assert [s["command"].replace("<settings>", '"$SETTINGS"') for s in info.steps()] == [f"python -m {module} {rest}" for module, rest in commands]


def test_step_modules_import() -> None:
    for step in info.steps():
        importlib.import_module(step["module"])


def test_every_step_output_is_in_the_catalog() -> None:
    catalog = _catalog_paths()
    for step in info.steps():
        assert step["what"] and step["cost"]
        assert set(step["outputs"]) | set(step.get("outputs_on_request", [])) <= catalog, step["name"]


def test_layout_names_the_folders_of_configure(tmp_path, monkeypatch) -> None:
    for name in ("OUTPUT_DIR", "FLOOD_DIR", "CSV_DIR", "EAV_DIR", "PLOT_DIR"):
        monkeypatch.setattr(_cfg, name, None, raising=False)
    configure(output_dir=str(tmp_path))
    folders = {"0_check_dams": _cfg.FLOOD_DIR, "1_results_csv": _cfg.CSV_DIR, "eav_tables": _cfg.EAV_DIR, "2_results_plots": _cfg.PLOT_DIR}
    assert {name: str(tmp_path / info.LAYOUT[name]) for name in folders} == folders


# ---- Resolved configuration ----

def test_resolved_config_resolves_paths_against_the_settings_file(settings) -> None:
    out = info.resolved_config(settings)
    root = settings.parent
    assert out["settings_file"] == str(settings.resolve())
    assert out["settings"]["output_dir"] == str(root / "output")
    assert out["settings"]["merit_rivers_shp"].startswith("/path/to/")
    assert out["output_layout"]["eav_tables"] == str(root / "output" / "1_results_csv" / "eav_tables")
    assert out["output_layout"]["report.md"] == str(root / "output" / "report.md")
    assert out["output_layout"]["domain_cache"] == str(root / "input" / "domain_inputs")
    assert out["defaults_applied"] == {"bathymetry_eav_csv": None, "bathymetry_dam_id": None, "bathymetry_survey_date": None}


def test_resolved_config_reports_the_defaults_of_the_keys_left_out(tmp_path) -> None:
    path = _settings_file(tmp_path, max_seg_len_m=MISSING, max_snap_distance_m=MISSING, country_name_col=MISSING)
    defaults = info.resolved_config(path)["defaults_applied"]
    assert defaults["max_seg_len_m"] == _cfg.MAX_SEG_LEN_M == 2000.0
    assert defaults["max_snap_distance_m"] == 1000.0
    assert defaults["country_name_col"] == "NAME"


@pytest.mark.parametrize(
    "text, error",
    [("{", json.JSONDecodeError), ('{"bogus": 1}', ValueError), ('{"max_seg_len_m": -1, "output_dir": "out"}', ValueError), ('{"srtm_dir": "srtm"}', ValueError)],
    ids=["malformed", "unknown_key", "bad_value", "no_output_dir"],
)
def test_resolved_config_refuses_an_invalid_settings_file(tmp_path, text, error) -> None:
    path = tmp_path / "settings.json"
    path.write_text(text)
    with pytest.raises(error):
        info.resolved_config(path)


def test_resolved_config_refuses_a_missing_settings_file(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        info.resolved_config(tmp_path / "absent.json")


def test_payloads_leave_the_configuration_as_it_was(settings) -> None:
    before = {name: vars(_cfg).get(name, MISSING) for name in info.CONFIG_ATTRIBUTES}
    info.resolved_config(settings)
    info.run_status(settings)
    with pytest.raises(ValueError):
        info.resolved_config(_settings_file(settings.parent / "other", output_dir=MISSING))
    assert {name: vars(_cfg).get(name, MISSING) for name in info.CONFIG_ATTRIBUTES} == before


# ---- Status ----

def test_run_status_reads_which_outputs_exist(settings) -> None:
    out = info.run_status(settings)
    assert out["output_dir"]["exists"]
    assert all(entry["exists"] for entry in out["tables"].values() if entry is not out["tables"]["threshold_analysis"])
    assert not out["tables"]["threshold_analysis"]["exists"]
    assert (out["eav_tables"]["count"], out["check_plots"]["count"]) == (2, 3)
    assert out["validation"]["regionalization_loo"]["exists"]
    assert not out["validation"]["sensitivity_sweep"]["exists"]
    assert out["uncertainty"]["exists"]
    assert list(out["panels"]) == list(info.PANELS)
    assert [stem for stem, entry in out["panels"].items() if entry["exists"]] == ["p1_domain_flowchart"]
    assert not out["report"]["exists"]
    assert all(not entry["exists"] for entry in out["domain_cache"].values())


def test_run_status_counts_the_rows_of_the_tables(settings) -> None:
    assert info.run_status(settings)["counts"] == {
        "dams_with_params": 3,
        "params_by_source": {"regi_multi": 1, "srtm_derived": 2},
        "summary_rows": 3,
        "dams_with_fill": 2,
        "failed_rows": 1,
        "failed_by_reason": {"placement_failed": 1},
    }


def test_run_status_of_a_run_not_started(tmp_path) -> None:
    out = info.run_status(_settings_file(tmp_path))
    assert not out["output_dir"]["exists"]
    assert all(value is None for value in out["counts"].values())
    assert (out["eav_tables"]["count"], out["check_plots"]["count"]) == (0, 0)


# ---- Outputs ----

def test_run_outputs_describe_the_key_tables_and_figures(settings) -> None:
    out = info.run_outputs(settings)
    assert out["panels"]["p1_domain_flowchart"]["exists"]
    assert out["panels"]["p1_domain_flowchart"]["path"].endswith("output/2_results_plots/p1_domain_flowchart.png")
    assert not out["panels"]["s5_sensitivity"]["exists"]
    assert out["tables"]["domain_characterization_json"]["exists"]
    entries = [*out["tables"].values(), *out["validation"].values(), out["uncertainty"], *out["panels"].values(), out["report"], *out["per_dam"].values()]
    assert all(entry["what"] and entry["path"] for entry in entries)


# ---- Domain characterization ----

def test_characterization_types_every_value(settings) -> None:
    out = info.characterization(settings)
    statistics = out["statistics"]
    assert list(statistics) == list(STATISTICS)
    assert statistics["region"] == "Testland"
    assert statistics["reference_year"] == 2026
    assert statistics["b_regionalized"] == 1.5065
    assert statistics["capacity_total_mcm"] == 193.74
    assert statistics["b_cluster_best_set"] == "raw morphometry"
    assert statistics["fill_median"] is None


def test_json_twin_holds_the_rows_of_the_csv(settings) -> None:
    out = info.characterization(settings)
    twin = Path(out["path"]).with_suffix(".json")
    assert json.loads(twin.read_text()) == out["statistics"]
    assert twin.read_text().endswith("}\n")


def test_characterization_refuses_a_run_without_the_report(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        info.characterization(_settings_file(tmp_path))


# ---- Dam lookup ----

def test_dam_matches_the_identifier_whatever_its_case(settings) -> None:
    out = info.dam("ID_010001", settings)
    assert [m["dam_id"] for m in out["matches"]] == ["id_010001"]
    match = out["matches"][0]
    assert match["dam_name"] == "Tamir"
    assert match["params"] == {"dam_name": "Tamir", "capacity_mcm": 0.0615, "c": 0.1008, "b": 1.2084, "source": "srtm_derived"}
    summary = match["summary"]
    assert (summary["construction_year"], summary["n_pixels"], summary["capped"], summary["quality"]) == (2008, 34, True, "A")
    assert summary["uncertainty_flags"] == "height_noise;pre_srtm"
    assert match["failure"] is None
    assert match["eav_table"].endswith("1_results_csv/eav_tables/id_010001_eav.csv")
    assert match["check_plot"].endswith("0_check_dams/id_010001_srtm.png")


def test_dam_without_a_fill_carries_its_failure(settings) -> None:
    match = info.dam("alpha", settings)["matches"][0]
    assert match["dam_id"] == "id_010000"
    assert match["params"]["source"] == "regi_multi"
    assert match["summary"]["c"] is None and match["summary"]["n_pixels"] is None
    assert match["failure"]["reason"] == "placement_failed"
    assert match["eav_table"] is None
    assert match["check_plot"].endswith("id_010000_regi.png")


def test_dam_matches_part_of_a_name_but_not_part_of_an_identifier(settings) -> None:
    assert [m["dam_id"] for m in info.dam("a", settings)["matches"]] == ["id_010000", "id_010001", "id_120000"]
    assert info.dam("id_0100", settings)["matches"] == []


def test_dam_refuses_an_empty_query(settings) -> None:
    with pytest.raises(ValueError):
        info.dam("  ", settings)


# ---- Read-only ----

def test_payloads_write_nothing_and_are_json_ready(settings) -> None:
    root = settings.parent
    before = sorted(root.rglob("*"))
    payloads = [
        info.steps(), info.resolved_config(settings), info.run_status(settings), info.run_outputs(settings),
        info.characterization(settings), info.dam("baish", settings),
    ]
    assert sorted(root.rglob("*")) == before
    for payload in payloads:
        json.dumps(payload, allow_nan=False)
