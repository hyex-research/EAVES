# Repository structure

```text
.
├── run_eaves.py                 # Thin CLI wrapper (delegates to eaves.__main__)
├── run_all.sh                   # End-to-end orchestrator: pipeline -> validation -> uncertainty -> panels -> report
│
├── eaves/                       # Core Python package
│   ├── __init__.py              # Package metadata (version)
│   ├── __main__.py              # python -m eaves entry point
│   ├── cli.py                   # Command-line interface: argparse + main()
│   ├── config.py                # Paths, algorithm constants, runtime reconfiguration
│   ├── settings.py              # JSON settings loader -> config.configure()
│   ├── preprocess.py            # MERIT -> country-clipped river network + dam snapping
│   ├── utils.py                 # Math helpers, override loaders, SRTM/UTM utilities
│   │
│   ├── pipeline/                # Per-dam EAV computation (runs in workers)
│   │   ├── terrain.py           # DEM loading, clipping, reprojection, flow direction
│   │   ├── placement.py         # Wall search, flood fill, upstream walk (6 stages)
│   │   ├── curves.py            # Per-dam EAV curve construction (process_dam)
│   │   └── workers.py           # Multiprocessing worker wrappers
│   │
│   └── postprocess/             # After all dams processed
│       ├── plots.py             # QC flood maps
│       ├── regionalization.py   # Reliability tagging, threshold analysis, parameter assignment
│       ├── reliability.py       # Trusted/training masks + uncertainty flags (sub-pixel, pre_srtm, ...)
│       ├── external_data.py     # Merge optional sedimentation / OWE columns into summary
│       ├── validation.py        # LOO validation + DEM-vs-sat-area diagnostic, plus opt-in --sensitivity / --dem-mc
│       ├── sensitivity.py       # Opt-in: placement/acceptance constant sensitivity sweep
│       ├── dem_error.py         # Opt-in: SRTM vertical-error Monte-Carlo
│       ├── uncertainty.py       # Three-term per-dam V uncertainty band (b_sigma, capacity, predicted-area terms)
│       ├── report.py            # Domain-characterization CSV + Markdown report
│       └── panels/              # Publication panels (p1-p5 main, s1-s5 supplementary; PNG + PDF)
│
├── region/                      # Per-region spatial runs
│   └── <country>/               # Full regional deployment
│       ├── <country>.json       # Settings JSON for this region
│       ├── input/               # Region inputs (licensed / user-provided)
│       │   ├── <country>_dams/  # Dam catalog CSV, water-extent time series
│       │   │   └── sedimentation_owe/  # Optional sediment yield + OWE CSVs (e.g. Dash et al. 2025 for KSA)
│       │   ├── grdl/            # Reference EAV curves for validation dams
│       │   └── domain_inputs/   # Preprocessing cache (rivers_split, dams_snapped)
│       └── output/              # Generated outputs (see documentation/outputs.md)
│           ├── 0_check_dams/    # Per-dam flood QC maps (100 DPI)
│           ├── 1_results_csv/   # Summary CSVs, EAV tables, failed dams, DATA_DICTIONARY.md
│           │   └── eav_tables/  # Individual dam EAV curves ({dam_id}_eav.csv)
│           └── 2_results_plots/ # Publication panels (300 DPI PNG + vector PDF)
│
├── documentation/               # Repository documentation (this folder)
├── test/                        # Test suite + shared 15-dam fixture
│   ├── conftest.py              # Session fixtures (repo_root, fixture_output, golden_hashes)
│   ├── test_*.py                # Fast unit suites + slow regression test
│   ├── golden_hashes.json       # Expected-output spec for the regression test
│   └── fixture/                 # Self-contained 15-dam fixture (settings, inputs, reference outputs)
│
├── pytest.ini                   # Pytest config (registers `slow` marker)
├── environment.yml              # Conda environment specification
├── pyproject.toml               # Package metadata (version from eaves.__init__)
├── CITATION.cff                 # Citation metadata
├── CHANGELOG.md                 # Versioned change log
├── LICENSE                      # Apache-2.0 (code)
├── LICENSE-DATA                 # CC BY 4.0 (data products)
└── README.md
```
