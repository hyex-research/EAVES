# Repository structure

The EAVES repository layout, top to bottom.

```text
.
├── eaves/                       # Installable Python package (region settings, inputs and outputs in region/)
│   ├── __main__.py              # `python -m eaves` entry point
│   ├── cli.py                   # `eaves` command-line entry point (the pipeline flags and the read-only info and mcp commands) and orchestration of the per-dam run
│   ├── config.py                # Paths, algorithm constants, runtime configuration
│   ├── settings.py              # JSON settings loader
│   ├── preprocess.py            # MERIT-Basins network closed upstream and split along the channel, dam snapping
│   ├── utils.py                 # Shared helpers, power-law fit, SRTM tile and UTM utilities, precision of the released tables
│   ├── agent/                   # Run view and read-only MCP server
│   ├── pipeline/                # Per-dam EAV computation, run in parallel workers
│   │   ├── terrain.py           # DEM loading, clipping, reprojection, river direction
│   │   ├── placement.py         # Wall search, flood fill, upstream walk (six stages)
│   │   ├── drainage.py          # Drainage of the DEM window, drainage rule
│   │   ├── curves.py            # Per-dam EAV curve construction
│   │   └── workers.py           # Multiprocessing workers
│   └── postprocess/             # Steps after the per-dam computation
│       ├── plots.py             # Flood check maps
│       ├── regionalization.py   # Reliability tagging, threshold analysis, parameter assignment
│       ├── reliability.py       # Trusted and training masks, uncertainty flags
│       ├── external_data.py     # Sediment yield and open-water evaporation columns of the summary
│       ├── validation.py        # Leave-one-out validation and internal-consistency diagnostics
│       ├── sensitivity.py       # Sensitivity sweep of the placement and acceptance constants, on request
│       ├── dem_error.py         # DEM vertical-error Monte-Carlo, on request
│       ├── uncertainty.py       # Per-dam volume uncertainty band
│       ├── report.py            # Domain characterization table with its JSON twin and Markdown report
│       └── panels/              # Main (p1 to p6) and supplementary (s1 to s5) panels as PNG and PDF
│
├── pyproject.toml               # Build backend, `eaves` console-script entry point, extras, and the pytest and ruff configuration
│
├── region/                      # Settings, inputs and outputs of the study areas, one folder per country
│   └── ksa/                     # Saudi Arabia
│       ├── ksa.json             # Settings of the Saudi Arabian run
│       ├── input/               # Dam catalog with its list of excluded entries, water-extent series, sediment and evaporation inputs, GRDL curves, Baish design and sonar tables, preprocessing cache
│       └── output/              # Released tables, panels, check maps and report (see outputs.md)
│
├── test/                        # Test suite and the 15-dam regression fixture
│   ├── README.md                # Test layers and how to run them
│   ├── test_*.py                # Fast unit tests and the slow regression test
│   ├── golden_hashes.json       # SHA-256 hashes of the fixture tables that the regression test expects
│   ├── build_fixture_srtm.py    # Cuts the fixture elevation set from full SRTM tiles
│   └── fixture/                 # Settings, inputs and reference outputs of the 15 fixture dams
│
├── documentation/               # Method, structure, usage, outputs and data docs, with their images in img/
├── .github/workflows/ci.yml     # Continuous integration, the fast tier of the pytest suite on every push to main and every pull request
├── run_eaves.py                 # Wrapper equivalent to `python -m eaves`
├── run_all.sh                   # End-to-end run, pipeline, validation, uncertainty, panels and report
├── README.md                    # Overview, quick start and documentation index
├── AGENTS.md                    # Operational brief for AI coding agents
├── CHANGELOG.md                 # Changes per release
├── CITATION.cff                 # Citation metadata
├── LICENSE                      # Apache-2.0 license of the code
├── LICENSE-DATA                 # CC BY 4.0 license of the data this project produced
└── environment.yml              # Conda environment specification
```

## Region pattern

The package holds the method, and each study area lives in its own folder `region/<country>/` with a settings JSON, an `input/` folder and an `output/` folder. The settings name the inputs under `input/` and the output folder by paths relative to the settings file, and the external rasters and shapefiles by path ([data-dependencies.md](data-dependencies.md)). A new region needs its own folder, dam catalog and settings file, and its first run builds the preprocessing cache. [usage.md](usage.md#configuration) lists the settings keys.
