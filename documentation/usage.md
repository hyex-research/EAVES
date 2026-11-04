# Usage

Installation, run commands, and configuration. For the files a run writes see [outputs.md](outputs.md). For the underlying method see [method.md](method.md).

## Installation

```bash
conda env create -f environment.yml
conda activate eaves
```

The environment targets **Python 3.14** and holds the packages the codebase imports.

To register the `eaves` console script, install the package in editable mode (runtime deps come from the conda env above):

```bash
pip install -e . --no-deps
```

The `test` extra, `pip install -e ".[test]"`, adds pytest to an environment without it.

If the package is not installed, every `eaves ...` command below also works as `python -m eaves <args>` from the repository root.

## Run commands

```bash
./run_all.sh region/ksa/ksa.json                                                    # the five steps below, in order
eaves --settings region/ksa/ksa.json                                                # 1. preprocessing, placement, fill, fit and regionalization
python -m eaves.postprocess.validation --settings region/ksa/ksa.json               # 2. leave-one-out validation and consistency diagnostics
python -m eaves.postprocess.uncertainty --settings region/ksa/ksa.json              # 3. per-dam volume uncertainty band
python -m eaves.postprocess.panels --settings region/ksa/ksa.json                   # 4. main panels p1 to p6 and supplementary panels s1 to s5
python -m eaves.postprocess.report --settings region/ksa/ksa.json --ref-year 2026   # 5. domain characterization and report.md
eaves info region/ksa/ksa.json                                                      # resolved configuration and output layout as JSON, running nothing
```

Without a settings file `run_all.sh` reads `region/ksa/ksa.json`. The panels read the validation and uncertainty outputs and the report embeds the panels, so the steps run in this order. `--ref-year` sets the reference year of the sediment budget, which otherwise is the current year. `RUN_TESTS=1 ./run_all.sh ...` also runs the regression test on the 15-dam fixture after the report and stops at a failure. The golden hashes change only through the one-liner of `test/README.md`.

## Other flags

| Flag | Effect |
| --- | --- |
| `--only id_120000 id_020017 ...` | Process only the listed dams and merge them into the existing summary and failure tables |
| `--plot-only` | Rerun the regionalization from the existing tables and rename the check maps by source, without the per-dam computation (`--rerun` forces the computation) |
| `--panels` | Render the main panels p1 to p6 and the supplementary panels s1 to s5 after the run |
| `--panels-only` | Render the panels from the existing outputs and run nothing else |
| `--rebuild-domain` | Rebuild the preprocessing cache (MERIT-Basins clip with upstream closure, reach subdivision along the channel and dam snap) instead of loading from `<domain_dir>/` |
| `--output-dir`, `--srtm-dir` | Override `output_dir` and `srtm_dir` of the settings |

## Validation diagnostics

`eaves.postprocess.validation` runs four internal-consistency diagnostics by default: the leave-one-out evaluation of the regionalization, the comparison of the DEM area with the 95th-percentile satellite area, the goodness of fit as the absolute fractional volume residual at each fitted level and the diagnostics of the A_cap regression. `--skip-loo`, `--skip-area-check`, `--skip-gof` and `--skip-acap` skip them one by one. Two heavier diagnostics run only on request, since each reruns the flood fill many times. Both leave `eaves_params.csv` and every other released table as they are and write only their own CSV under `validation/`.

```bash
# Default diagnostics, as run_all.sh runs them
python -m eaves.postprocess.validation --settings region/ksa/ksa.json

# Sensitivity sweep of the placement and acceptance constants, written to validation/sensitivity_sweep.csv
python -m eaves.postprocess.validation --settings region/ksa/ksa.json \
    --sensitivity [--sensitivity-n-dams 60] [--sensitivity-seed 7]

# Monte Carlo of the SRTM vertical error, written to validation/dem_error_montecarlo.csv
python -m eaves.postprocess.validation --settings region/ksa/ksa.json \
    --dem-mc [--dem-mc-n-dams 36] [--dem-mc-n-real 32] \
    [--dem-mc-sigma-m 3.6] [--dem-mc-corr-px 2.0] [--dem-mc-workers 8]
```

`--sensitivity` perturbs the five swept placement/acceptance constants (`ALIGN_WEIGHT`, `MAX_CREST_FLOW_DOT`, `VOID_THRESHOLD` and the two constants of the drainage rule, `DRAIN_WALL_TOLERANCE_M` and `DRAIN_MAX_OUTLET_POSITION`) one at a time by ±20-30% over a trusted-dam sample and reports how the trusted-set size, grade distribution, and median `b` move. `--dem-mc` perturbs the SRTM mosaic with spatially correlated Gaussian noise (point sigma ~3.6 m, LE90 ~6 m, [Rodríguez et al. (2006)](https://doi.org/10.14358/PERS.72.3.249)) and re-fits, reporting the fractional spread of recovered volume and `b`. Its sample spans the capacity range of the trusted dams. The DEM-MC writes each dam's row incrementally with a per-dam wall-clock budget, so a killed run is resumable. Re-launch to skip dams already in the CSV, or pass `--dem-mc-fresh` to start over.

## Testing

The tests run under pytest. The 15-dam fixture and its settings live under `test/fixture/`, and [test/README.md](../test/README.md) describes the tiers, the fixture and the golden hashes.

```bash
pytest -m "not slow"    # fast sanity suite
pytest -m slow          # full 15-dam regression run, writes test/fixture/output/ and checks the SHA-256 hashes
pytest                  # everything
```

The fast suite runs in seconds and the regression run in a few minutes, longer on fewer cores.

## MCP server

For LLM agent clients, EAVES ships a read-only [Model Context Protocol](https://modelcontextprotocol.io) server behind the optional `mcp` extra:

```bash
pip install -e ".[mcp]"
eaves mcp                   # serves over stdio, this is what MCP clients spawn
```

Nothing in the server runs the pipeline, execution stays with the CLI. Register it in an MCP client with command `eaves` and args `["mcp"]`.

## Configuration

EAVES is configured through a JSON settings file that names the input catalogs, the external rasters and shapefiles, and the output folder. Each region keeps its settings beside its inputs and outputs in `region/<country>/`, and `region/ksa/ksa.json` configures the Saudi Arabian run. A settings file is a flat JSON object with the keys below. Every step needs `output_dir` and the pipeline also `srtm_dir`, `dams_csv` and `domain_dir`. The other keys not marked optional are needed by the steps that read them, and only `country_name_col`, `max_seg_len_m` and `max_snap_distance_m` fall back to defaults, which `eaves info` lists. Paths inside the repository are relative to the settings file, and the shipped settings name the external data as `/path/to/...`, to be set to your copies. The keys a settings file accepts:

| Key | Purpose |
| --- | --- |
| `output_dir`, `srtm_dir`, `dams_csv`, `water_extent_dir`, `domain_dir` | Paths to local inputs and outputs |
| `merit_rivers_shp`, `merit_basins_shp`, `country_shp` | External shapefiles of the preprocessing, the country layer also for the domain map of panel p1 |
| `target_country`, `country_name_col` | Country filter applied to `country_shp` |
| `bathymetry_eav_csv`, `bathymetry_dam_id`, `bathymetry_survey_date` _(optional)_ | Sonar/design EAV table for the cross-reference panels, and the survey date as `YYYY-MM`, at which the report evaluates the sediment budget |
| `grdl_dir` _(optional)_ | Folder of GRDL reference curves ([Hao et al. (2024)](https://doi.org/10.1029/2023WR035781)) for the cross-reference panels |
| `sedimentation_dir` _(optional)_ | Folder with `sedimentation_yield.csv` and `owe_annual_mean.csv`, merged into `eaves_summary.csv` (for Saudi Arabia from [Dash et al. (2025)](https://doi.org/10.1016/j.jenvman.2025.127199)) |
| `max_seg_len_m`, `max_snap_distance_m` | Preprocessing parameters, the length of the reach parts and the snap radius, both in meters on the ground |

An unknown key or an invalid value stops the run with an error.
