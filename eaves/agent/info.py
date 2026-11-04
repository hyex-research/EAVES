"""
Machine-readable view of EAVES and its runs.

Plain functions that return JSON-ready dicts and lists: the catalog of the five
steps of an end-to-end run, the resolved configuration of a settings file,
which outputs of a run exist with the headline counts of its tables, the key
tables and figures, the domain characterization and the results of single
dams. ``eaves.agent.mcp_server`` serves them as tools, and ``eaves info``
prints the resolved configuration. Nothing here runs a step, creates a folder
or writes a file, and the only files read are the settings JSON and the CSV
tables of a run.

A run is named by its settings JSON. ``eaves.settings.load_settings``
validates the file and resolves its relative paths against the folder of the
file, and the values it applies to ``eaves.config`` are put back afterwards,
so a call leaves the configuration of the process as it found it.

The functions that take a settings file raise ``FileNotFoundError``,
``json.JSONDecodeError`` or ``ValueError`` when it is missing or invalid, and
callers decide how to present errors.
"""

from __future__ import annotations

import csv
import inspect
from collections import Counter
from pathlib import Path
from typing import Any

import eaves.config as _cfg
from eaves.config import configure
from eaves.postprocess.report import read_characterization
from eaves.preprocess import DAMS_SNAPPED_GEOJSON, RIVERS_SPLIT_GEOJSON
from eaves.settings import load_settings
from eaves.utils import typed_value

# ---- Settings ----

# Keys of a settings file, the keyword arguments of eaves.config.configure
SETTINGS_KEYS: tuple[str, ...] = tuple(inspect.signature(configure).parameters)

# Attributes of eaves.config that configure() sets, every settings key under its upper-case name and the four folders of the output tree
CONFIG_ATTRIBUTES: tuple[str, ...] = (*(key.upper() for key in SETTINGS_KEYS), "FLOOD_DIR", "CSV_DIR", "EAV_DIR", "PLOT_DIR")

# Value of eaves.config for every settings key as the module holds it on import, None where it holds none
CONFIG_DEFAULTS: dict[str, Any] = {key: getattr(_cfg, key.upper(), None) for key in SETTINGS_KEYS}

# ---- Run layout ----

# Folders and files of the output tree relative to output_dir, as eaves.config.configure and the steps name them
LAYOUT: dict[str, str] = {
    "0_check_dams": "0_check_dams",
    "1_results_csv": "1_results_csv",
    "eav_tables": "1_results_csv/eav_tables",
    "validation": "1_results_csv/validation",
    "2_results_plots": "2_results_plots",
    "report.md": "report.md",
}

# Tables of 1_results_csv, as (path under output_dir, what it holds)
TABLES: dict[str, tuple[str, str]] = {
    "eaves_params": ("1_results_csv/eaves_params.csv", "Released parameters c and b of every dam with their source, srtm_derived or regi_multi"),
    "eaves_summary": ("1_results_csv/eaves_summary.csv", "One row per dam with the catalog attributes, the fill and the fit, the quality grade, the uncertainty flags, the topographic features and the sediment columns"),
    "failed_dams": ("1_results_csv/failed_dams.csv", "Dams that fail the wall placement, the fill acceptance or the power-law fit, with the reason"),
    "threshold_analysis": ("1_results_csv/threshold_analysis.csv", "Capacity-threshold sweep behind the training cut of the regional exponent"),
    "domain_characterization": ("1_results_csv/domain_characterization.csv", "Key/value table of the domain statistics that the report quotes"),
    "domain_characterization_json": ("1_results_csv/domain_characterization.json", "JSON twin of the domain characterization with typed values"),
}

# Diagnostic tables of the validation folder, as (path under output_dir, what it holds), the last two written only on request
VALIDATION_TABLES: dict[str, tuple[str, str]] = {
    "regionalization_loo": ("1_results_csv/validation/regionalization_loo.csv", "Leave-one-out residuals of every regionalization anchor on the training dams"),
    "dem_vs_sat_area": ("1_results_csv/validation/dem_vs_sat_area.csv", "DEM full-pool area against the 95th-percentile satellite area of every trusted dam"),
    "goodness_of_fit": ("1_results_csv/validation/goodness_of_fit.csv", "Per-dam maximum and root-mean-square absolute fractional volume residual of the released curves over the fitted levels, its medians by fill level, its departure at the typical satellite extent and the residual of the two-segment alternative"),
    "acap_regression_diagnostics": ("1_results_csv/validation/acap_regression_diagnostics.csv", "Collinearity, incremental and drop-one leave-one-out skill of the features of the full-pool area regression"),
    "b_clustering_diagnostic": ("1_results_csv/validation/b_clustering_diagnostic.csv", "Silhouette, leave-one-out spread of b and leave-one-out R² of the per-cluster median over the number of clusters, with the variance share of the first principal component of the features and the rank correlation of b with it, written by panel s1"),
    "sensitivity_sweep": ("1_results_csv/validation/sensitivity_sweep.csv", "Trusted-set size, grades and median b under perturbed placement and acceptance constants, written by --sensitivity"),
    "dem_error_montecarlo": ("1_results_csv/validation/dem_error_montecarlo.csv", "Per-dam spread of the volume and of b across SRTM vertical-error realizations, written by --dem-mc"),
}

# Per-dam volume uncertainty table, as (path under output_dir, what it holds)
UNCERTAINTY_TABLE: tuple[str, str] = ("1_results_csv/validation/v_uncertainty.csv", "Per-dam 1σ band of the volume at half, quarter and tenth pool")

# Panels of 2_results_plots by file stem with what each shows, each PNG with a PDF twin of the same stem
PANELS: dict[str, str] = {
    "p1_domain_flowchart": "Domain map and pipeline flowchart",
    "p2_placement": "Three examples of the six-stage dam-wall placement procedure",
    "p3_baish_example": "EAVES outputs at the reservoir with sonar bathymetry and the distribution of the unconstrained exponents of the trusted dams",
    "p4_regionalization_validation": "Leave-one-out evaluation of the regionalization procedure on the training dams at three fill levels",
    "p5_comparison": "Area-volume and elevation-area curves of the reservoir with sonar bathymetry from SRTM, sonar and the design table, and the distribution of the volume ratio over the domain",
    "p6_grdl_comparison": "Area-volume and depth-area curves of EAVES against the GRDL reference curves, one row per reference reservoir",
    "s1_b_clustering_silhouette": "K-means clustering diagnostic of b on the training set, with the training dams in the plane of the first two principal components",
    "s2_uncertainty_band": "Volume uncertainty band on the worked example and against normalized area",
    "s3_dem_error": "Volume spread under SRTM vertical error by size class, from the table of --dem-mc",
    "s4_threshold_analysis": "Capacity-threshold sweep behind the training cut of the regional exponent",
    "s5_sensitivity": "Sensitivity of the trusted set to the placement and acceptance constants, from the table of --sensitivity",
}

# Markdown report, as (path under output_dir, what it holds)
REPORT: tuple[str, str] = ("report.md", "Report of the domain characterization, the method, the validation and the uncertainty, with the main panels and the first two supplementary panels embedded")

# Per-dam EAV table and flood check map under output_dir, the map named after the source of the parameters of the dam
EAV_TABLE = "1_results_csv/eav_tables/{dam_id}_eav.csv"
CHECK_PLOT = "0_check_dams/{dam_id}_{srtm|regi}.png"

# ---- Step catalog ----

# The five steps of run_all.sh in order, served by the pipeline_steps tool, each output relative to output_dir
STEPS: list[dict[str, Any]] = [
    {
        "step": 1,
        "name": "pipeline",
        "module": "eaves",
        "command": "python -m eaves --settings <settings>",
        "what": "Clips the MERIT-Basins network to the domain closed upstream, splits it along the channel and snaps the dams into the cache of domain_dir, then places the wall, floods the valley to the spillway, tabulates the EAV curve and fits V = c * A^b for every dam in a worker pool, grades and flags every fill and regionalizes the parameters of the dams without a trusted fit. --only narrows the run to listed dams, --plot-only and --panels-only re-enter from the existing outputs and --rebuild-domain rebuilds the cache",
        "cost": "heavy over a country, minutes on a many-core machine and hours on a few cores, minutes on the 15-dam fixture, do not launch casually",
        "outputs": [TABLES[key][0] for key in ("eaves_summary", "failed_dams", "eaves_params", "threshold_analysis")] + [EAV_TABLE, CHECK_PLOT],
    },
    {
        "step": 2,
        "name": "validation",
        "module": "eaves.postprocess.validation",
        "command": "python -m eaves.postprocess.validation --settings <settings>",
        "what": "Leave-one-out evaluation of the regionalization on the training dams, DEM against satellite area, goodness of fit of the released curves over the fitted levels and the diagnostics of the full-pool area regression, each skipped by its --skip-* flag. --sensitivity and --dem-mc add the sweep of the placement and acceptance constants and the Monte Carlo of the SRTM vertical error on request",
        "cost": "light by default, heavy with --sensitivity or --dem-mc, which rerun the flood fill many times",
        "outputs": [VALIDATION_TABLES[key][0] for key in ("regionalization_loo", "dem_vs_sat_area", "goodness_of_fit", "acap_regression_diagnostics")],
        "outputs_on_request": [VALIDATION_TABLES[key][0] for key in ("sensitivity_sweep", "dem_error_montecarlo")],
    },
    {
        "step": 3,
        "name": "uncertainty",
        "module": "eaves.postprocess.uncertainty",
        "command": "python -m eaves.postprocess.uncertainty --settings <settings>",
        "what": "Per-dam 1σ band of the volume at half, quarter and tenth pool from the spread of the exponent, the error of the full-pool area of the regionalized dams and the error of the catalog capacity",
        "cost": "light",
        "outputs": [UNCERTAINTY_TABLE[0]],
    },
    {
        "step": 4,
        "name": "panels",
        "module": "eaves.postprocess.panels",
        "command": "python -m eaves.postprocess.panels --settings <settings>",
        "what": "Main panels p1 to p6 and supplementary panels s1 to s5 as PNG with a PDF twin, from the tables of the steps before, s3 and s5 from the tables of --dem-mc and --sensitivity when they exist. A panel whose input is missing is skipped. Panel s1 also writes the b-clustering diagnostic",
        "cost": "moderate, minutes",
        "outputs": [f"{LAYOUT['2_results_plots']}/{stem}.png" for stem in PANELS] + [VALIDATION_TABLES["b_clustering_diagnostic"][0]],
    },
    {
        "step": 5,
        "name": "report",
        "module": "eaves.postprocess.report",
        "command": "python -m eaves.postprocess.report --settings <settings> --ref-year 2026",
        "what": "Domain characterization with its JSON twin and the Markdown report with the main panels and the first two supplementary panels embedded, and the sediment risk columns of eaves_summary.csv. --ref-year sets the reference year of the sediment budget",
        "cost": "light, seconds",
        "outputs": [TABLES["domain_characterization"][0], TABLES["domain_characterization_json"][0], REPORT[0], TABLES["eaves_summary"][0]],
    },
]


# ---- Helpers ----

def load(settings_file: str | Path) -> dict[str, Any]:
    """Load and validate a settings JSON through ``eaves.settings.load_settings`` and return its resolved values, with the configuration of ``eaves.config`` put back as it was."""
    path = Path(settings_file)
    if not path.is_file():
        raise FileNotFoundError(f"settings file not found: {settings_file}")
    saved = {name: getattr(_cfg, name) for name in CONFIG_ATTRIBUTES if hasattr(_cfg, name)}
    try:
        settings = load_settings(str(path))
    finally:
        for name in CONFIG_ATTRIBUTES:
            if name in saved:
                setattr(_cfg, name, saved[name])
            elif hasattr(_cfg, name):
                delattr(_cfg, name)
    if "output_dir" not in settings:
        raise ValueError(f"{settings_file}: names no output_dir, the folder a run writes to")
    return settings


def where(path: Path) -> dict[str, Any]:
    """Return a path and whether it exists."""
    return {"path": str(path), "exists": path.exists()}


def described(path: Path, what: str) -> dict[str, Any]:
    """Return what a file shows, its path and whether it exists."""
    return {"what": what, **where(path)}


def read_rows(path: Path) -> list[dict[str, str]] | None:
    """Return the rows of a CSV table as text, or None when the file is missing."""
    if not path.is_file():
        return None
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def tally(rows: list[dict[str, str]] | None, column: str) -> dict[str, int] | None:
    """Return the number of rows per value of a column, or None when the table is missing."""
    if rows is None:
        return None
    return dict(sorted(Counter(row.get(column) or "" for row in rows).items()))


def count_files(folder: Path, pattern: str) -> int:
    """Return the number of files in a folder that match a pattern, 0 when the folder is missing."""
    return sum(1 for p in folder.glob(pattern) if p.is_file()) if folder.is_dir() else 0


def typed_row(row: dict[str, str] | None) -> dict[str, Any] | None:
    """Return a table row without its dam_id, every cell typed as its text reads, or None for a missing row."""
    if row is None:
        return None
    return {key: typed_value(value) for key, value in row.items() if key != "dam_id"}


# ---- Payloads ----

def steps() -> list[dict[str, Any]]:
    """Return the catalog of the five steps of an end-to-end run in order, with the module of each, what it makes, its compute cost class and its output files."""
    return STEPS


def resolved_config(settings_file: str | Path) -> dict[str, Any]:
    """Return the resolved settings of a settings file, the layout of its output tree and the value of ``eaves.config`` for every key the file leaves out."""
    settings = load(settings_file)
    output_dir = Path(settings["output_dir"])
    return {
        "settings_file": str(Path(settings_file).resolve()),
        "settings": settings,
        "output_layout": {
            "output_dir": str(output_dir),
            **{name: str(output_dir / rel) for name, rel in LAYOUT.items()},
            "domain_cache": settings.get("domain_dir"),
        },
        "defaults_applied": {key: CONFIG_DEFAULTS[key] for key in SETTINGS_KEYS if key not in settings},
    }


def run_status(settings_file: str | Path) -> dict[str, Any]:
    """
    Return which outputs of a run exist and the headline counts of its tables.

    Every table, panel and the report carry their path and whether they exist,
    the per-dam EAV tables and check maps their folder and count, and the
    preprocessing cache its two files. The counts come from the parameter,
    summary and failure tables, and each is None while its table is missing.
    """
    settings = load(settings_file)
    out = Path(settings["output_dir"])
    domain = settings.get("domain_dir")
    params = read_rows(out / TABLES["eaves_params"][0])
    summary = read_rows(out / TABLES["eaves_summary"][0])
    failed = read_rows(out / TABLES["failed_dams"][0])
    return {
        "settings_file": str(Path(settings_file).resolve()),
        "output_dir": where(out),
        "domain_cache": None if domain is None else {name: where(Path(domain) / name) for name in (RIVERS_SPLIT_GEOJSON, DAMS_SNAPPED_GEOJSON)},
        "tables": {key: where(out / rel) for key, (rel, _) in TABLES.items()},
        "eav_tables": {"folder": str(out / LAYOUT["eav_tables"]), "count": count_files(out / LAYOUT["eav_tables"], "*_eav.csv")},
        "check_plots": {"folder": str(out / LAYOUT["0_check_dams"]), "count": count_files(out / LAYOUT["0_check_dams"], "*.png")},
        "validation": {key: where(out / rel) for key, (rel, _) in VALIDATION_TABLES.items()},
        "uncertainty": where(out / UNCERTAINTY_TABLE[0]),
        "panels": {stem: where(out / LAYOUT["2_results_plots"] / f"{stem}.png") for stem in PANELS},
        "report": where(out / REPORT[0]),
        "counts": {
            "dams_with_params": None if params is None else len(params),
            "params_by_source": tally(params, "source"),
            "summary_rows": None if summary is None else len(summary),
            "dams_with_fill": None if summary is None else sum(1 for row in summary if row.get("n_pixels")),
            "failed_rows": None if failed is None else len(failed),
            "failed_by_reason": tally(failed, "reason"),
        },
    }


def run_outputs(settings_file: str | Path) -> dict[str, Any]:
    """Return the key tables and figures of a run with what each shows, its path and whether it exists, and the per-dam EAV table and check map as path patterns."""
    settings = load(settings_file)
    out = Path(settings["output_dir"])
    return {
        "output_dir": where(out),
        "tables": {key: described(out / rel, what) for key, (rel, what) in TABLES.items()},
        "validation": {key: described(out / rel, what) for key, (rel, what) in VALIDATION_TABLES.items()},
        "uncertainty": described(out / UNCERTAINTY_TABLE[0], UNCERTAINTY_TABLE[1]),
        "panels": {stem: described(out / LAYOUT["2_results_plots"] / f"{stem}.png", what) for stem, what in PANELS.items()},
        "report": described(out / REPORT[0], REPORT[1]),
        "per_dam": {
            "eav_table": {"what": "Elevation, depth, area and volume of the dam at levels 0.5 m apart", "path": str(out / EAV_TABLE)},
            "check_plot": {"what": "Flood check map of the dam, suffixed by the source of its parameters", "path": str(out / CHECK_PLOT)},
        },
    }


def characterization(settings_file: str | Path) -> dict[str, Any]:
    """Return the domain characterization of a run, every statistic by name with a typed value in the order of the CSV rows."""
    settings = load(settings_file)
    path = Path(settings["output_dir"]) / TABLES["domain_characterization"][0]
    if not path.is_file():
        raise FileNotFoundError(f"no domain characterization at {path}, run the report step first")
    return {"path": str(path), "statistics": read_characterization(path)}


def dam(query: str, settings_file: str | Path) -> dict[str, Any]:
    """
    Return the results of the dams whose identifier equals the query or whose name contains it, case-insensitive.

    Each match carries its row of the parameter table, its row of the summary
    with the catalog attributes, the fill and the fit, the quality grade and
    the uncertainty flags, its row of the failure table, and the paths of its
    EAV table and check map, each None where the dam has none.
    """
    q = str(query).strip().lower()
    if not q:
        raise ValueError("the query is empty, give a dam identifier or part of a dam name")
    settings = load(settings_file)
    out = Path(settings["output_dir"])
    sources = ("eaves_params", "eaves_summary", "failed_dams")
    rows = {key: {row.get("dam_id") or "": row for row in read_rows(out / TABLES[key][0]) or []} for key in sources}

    names: dict[str, str] = {}
    for table in rows.values():
        for dam_id, row in table.items():
            names.setdefault(dam_id, row.get("dam_name") or "")
    matched = sorted(d for d, name in names.items() if d and (d.lower() == q or q in name.lower()))

    matches = []
    for d in matched:
        eav_table = out / EAV_TABLE.format(dam_id=d)
        check_plots = sorted((out / LAYOUT["0_check_dams"]).glob(f"{d}_*.png"))
        matches.append({
            "dam_id": d,
            "dam_name": names[d],
            "params": typed_row(rows["eaves_params"].get(d)),
            "summary": typed_row(rows["eaves_summary"].get(d)),
            "failure": typed_row(rows["failed_dams"].get(d)),
            "eav_table": str(eav_table) if eav_table.is_file() else None,
            "check_plot": str(check_plots[0]) if check_plots else None,
        })
    return {
        "query": query,
        "output_dir": str(out),
        "sources": {key: where(out / TABLES[key][0]) for key in sources},
        "matches": matches,
    }
