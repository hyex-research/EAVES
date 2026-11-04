# EAVES agent guide

Operational brief for AI coding agents (and new human contributors) working in this repository. It condenses what the full documentation explains so an agent can act without rediscovering it. When in doubt, the human docs win, they are the source of truth.

| Question | Read |
| --- | --- |
| What does each step do and what does it write | [documentation/usage.md](documentation/usage.md), [documentation/outputs.md](documentation/outputs.md) |
| How does the method work (placement, fill, fit, regionalization) | [documentation/method.md](documentation/method.md) |
| How is the repository laid out | [documentation/structure.md](documentation/structure.md) |
| What external data is required | [documentation/data-dependencies.md](documentation/data-dependencies.md) |
| What does each column of the released tables mean | [DATA_DICTIONARY.md](region/ksa/output/1_results_csv/DATA_DICTIONARY.md) |
| How is the code tested | [test/README.md](test/README.md) |
| What changed recently | [CHANGELOG.md](CHANGELOG.md) |

## What this is

EAVES (Elevation-Area-Volume Estimation from SRTM) is an open-source pipeline that reconstructs the elevation-area-volume (EAV) curves of reservoirs from SRTM topography, acquired in February 2000, before most of the Saudi Arabian dams of the dataset were built. For every dam of a catalog it places a wall across the valley on the DEM, floods the valley to the spillway, integrates the depth-area relation into an EAV table and fits V = c · A<sup>b</sup>, and the dams without a trusted fit receive regionalized parameters. The demonstration application is Saudi Arabia, whose 526 curves ship under `region/ksa/output/`.

## Repository map

| Path | Contents |
| --- | --- |
| `eaves/` | The Python package: `cli.py` (entry point), `pipeline/` (per-dam placement, flood fill and curve, run in parallel workers), `postprocess/` (regionalization, validation, uncertainty, panels and report), `agent/` (run view and MCP server), plus `config.py`, `settings.py`, `preprocess.py` and `utils.py` |
| `region/ksa/` | Settings of the Saudi Arabian run (`ksa.json`), its inputs (`input/`) and its released outputs (`output/`) |
| `documentation/` | The human docs listed above |
| `test/` | The pytest suite, the 15-dam fixture with its settings, inputs and reference outputs (`fixture/`), and the hashes the regression test expects (`golden_hashes.json`) |
| `run_all.sh` | The five steps of an end-to-end run, in order |
| `run_eaves.py` | A wrapper equivalent to `python -m eaves`, which the regression fixture and the hash refresh of `test/README.md` run |

## Setup

```bash
conda env create -f environment.yml
conda activate eaves
pip install -e . --no-deps
```

Python 3.14. Without the editable install, `eaves ...` commands also work as `python -m eaves ...` from the repository root, and the steps after the pipeline run as `python -m eaves.postprocess.<step> --settings <settings>`.

## Running

Everything is driven by a flat settings JSON (`region/ksa/ksa.json` for Saudi Arabia, `test/fixture/settings.json` for the fixture). `eaves.settings.load_settings` validates it, resolves its relative paths against the folder of the file and applies it to the module constants of `eaves.config` through `configure`. The Saudi settings name their external data as `/path/to/...`, so a run of the domain needs those paths set first.

```bash
./run_all.sh region/ksa/ksa.json                                                    # the five steps below, in order
eaves --settings region/ksa/ksa.json                                                # 1. preprocessing, placement, fill, fit and regionalization
python -m eaves.postprocess.validation --settings region/ksa/ksa.json               # 2. leave-one-out validation and consistency diagnostics
python -m eaves.postprocess.uncertainty --settings region/ksa/ksa.json              # 3. per-dam volume uncertainty band
python -m eaves.postprocess.panels --settings region/ksa/ksa.json                   # 4. main panels p1 to p6 and supplementary panels s1 to s5
python -m eaves.postprocess.report --settings region/ksa/ksa.json --ref-year 2026   # 5. domain characterization and report.md
```

The flags of step 1 and the diagnostics on request of step 2:

```bash
eaves --settings region/ksa/ksa.json --only id_120000 id_020017    # these dams, merged into the existing tables
eaves --settings region/ksa/ksa.json --plot-only                   # regionalization and check maps from the existing tables
eaves --settings region/ksa/ksa.json --panels-only                 # the panels from the existing outputs, nothing else
eaves --settings region/ksa/ksa.json --rebuild-domain              # rebuild the preprocessing cache of domain_dir
python -m eaves.postprocess.validation --settings region/ksa/ksa.json --sensitivity   # sweep of the placement and acceptance constants
python -m eaves.postprocess.validation --settings region/ksa/ksa.json --dem-mc        # DEM vertical-error Monte-Carlo
```

Outputs land in `<output_dir>/` (`0_check_dams/`, `1_results_csv/` with `eav_tables/` and `validation/`, `2_results_plots/` and `report.md`), see [documentation/outputs.md](documentation/outputs.md). The panels read the validation and uncertainty tables and the report embeds the panels, so the steps run in this order. `--sensitivity` and `--dem-mc` each rerun the flood fill many times and write only their own table under `validation/`, which panels s5 and s3 read when it exists.

Three things to know when running by hand:

- The pipeline reuses the preprocessing cache, `rivers_split.geojson` and `dams_snapped.geojson` in `domain_dir`, whenever both files exist. A new catalog or river layer needs `--rebuild-domain`, which reads the MERIT-Basins and country layers.
- `--only` merges its dams into the existing summary and failure tables instead of replacing them.
- The report step adds the sediment risk columns to `eaves_summary.csv`.

Machine-readable interfaces, prefer these over parsing Markdown or logs:

- `eaves info <settings>` prints the resolved settings, the layout of the output tree and the defaults of `eaves.config` for the keys the file leaves out as JSON, without running anything.
- The report step writes `domain_characterization.json` next to `domain_characterization.csv`, the same statistics with typed values.
- `eaves mcp` serves read-only tools over the Model Context Protocol (stdio) for MCP-capable clients. `agents_brief` returns this file, `pipeline_steps` the catalog of the five steps, and `resolved_config` the payload of `eaves info`. Four run tools take the settings JSON of a run: `run_status` (which outputs exist, with the headline counts of the parameter, summary and failure tables), `run_outputs` (the key tables and figures with what each shows), `domain_characterization` (the statistics with typed values) and `dam_results` (the parameters, summary row, failure and EAV table of matching dams). Requires the optional `mcp` extra (`pip install -e ".[mcp]"`).

## Verifying changes

```bash
pip install -e ".[test]"     # pytest, once
pytest -m "not slow"         # smoke and unit tests, seconds
pytest -m slow               # the 15-dam fixture through the pipeline against test/golden_hashes.json, about four minutes
pytest                       # both
```

The regression test is the correctness check after code changes. It runs the fixture with the tracked `test/fixture/settings.json`, or the untracked `settings_local.json` beside it when that file exists, on the inputs under `test/fixture/input/`, writes `test/fixture/output/` and compares the SHA-256 hash of every emitted CSV with `test/golden_hashes.json`, so a change of any value, column, rounding or file name fails it. It also checks that `--plot-only` and single-dam `--only` runs leave the tables of the full run unchanged. The run takes longer on fewer cores. When a change alters the outputs on purpose, verify the new tables first and then refresh the hashes with the one-liner of [test/README.md](test/README.md). For a syntax-level smoke test, `python -m py_compile <file>` is always safe.

## Compute and data reality

- Cloning this repository is not sufficient to rerun the Saudi domain. The SRTM GL1 tiles, the MERIT-Basins reaches and unit catchments and the Natural Earth country layer are external and named in the settings (`srtm_dir`, `merit_rivers_shp`, `merit_basins_shp`, `country_shp`), see [documentation/data-dependencies.md](documentation/data-dependencies.md). The Saudi inputs that are not external datasets ship under `region/ksa/input/`: the dam catalog with the list of excluded entries and the reason for each, the water-extent series, the sediment and evaporation inputs, the GRDL curves, the Baish design and sonar tables and the preprocessing cache. With the cache in place, the pipeline reads the SRTM tiles, `--rebuild-domain` also reads the MERIT-Basins and country layers, and the panels step reads the country layer for the domain map of panel p1. The fixture runs from a clone alone. Never invent or hardcode data paths, take them from the settings file at hand.
- The pipeline step over the Saudi domain is heavy. A worker pool sized by the number of cores places and fills every dam, each within a time budget, which takes minutes on a many-core machine and hours on a few cores. Do not launch it casually, prefer the fixture for verification and let a human decide on production runs. `--sensitivity` and `--dem-mc` are heavier still.
- A rerun of the Saudi domain rewrites the tracked outputs under `region/ksa/output/`.

## Conventions

- Comments: a single `#` on one line, descriptive in the present tense, without rationale clauses, first person or a trailing period. No multi-line comment blocks, no commented-out code, no breadcrumbs about moved or deleted code, no narration of numerical guards. Section dividers look like `# ---- Title ----`.
- Imports at the top of the module, grouped stdlib, third party and local, alphabetized within a group, never inside a function body.
- Docstrings: what the function or module does, concise and in the present tense, without history. A helper used by one step lives in the file of that step, not in a shared module.
- Surgical edits only. Do not restructure working code paths beyond what the task requires.
- Markdown: sentence-case headings, `| --- |` table separators with spaces, `_underscore_` italics, no TeX math (use Unicode symbols), single trailing newline. A markdownlint config is committed, respect it.
- US English in code, comments, and generated reports.
- Match the register of existing docs: concise, precise, no marketing language.
- User-visible changes get a [CHANGELOG.md](CHANGELOG.md) entry under `[Unreleased]`.

## Guardrails

- The **source code** is licensed under the [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0) (`LICENSE`). The **data products generated by this project** are licensed under [Creative Commons Attribution 4.0 International (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/) (`LICENSE-DATA`).
- When citing this software or generating citations, use [CITATION.cff](CITATION.cff), it holds the authors and the archived identifier of the software.
- Do not commit, tag, or push unless explicitly asked.
- `test/golden_hashes.json` changes only through the one-liner of [test/README.md](test/README.md), run on a fixture run whose new tables are verified, once the differences the regression test lists are understood. `RUN_TESTS=1 ./run_all.sh` runs the regression test after the report and stops at a failure.
- Do not add new top-level directories or rename the steps without discussion.
- Bulky generated outputs (the PDF twins of the panels, logs) are gitignored by design, do not force-add them. The Saudi outputs under `region/ksa/output/` (the tables, the EAV tables, the check maps, the PNG panels and the report) and the fixture outputs under `test/fixture/output/` are tracked deliberately. Settings with machine paths (`*_local.json`) stay out of commits.
