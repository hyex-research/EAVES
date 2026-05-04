# 🏔️💧 **EAVES — Elevation–Area–Volume Estimation from SRTM**

*Reconstructing reservoir bathymetry for ungaged arid-basin dams from pre-impoundment SRTM topography.*

---

[![Python](https://img.shields.io/badge/python-3.14-blue.svg)](environment.yml)
[![DOI](https://img.shields.io/badge/DOI-pending-yellow.svg)](#)
[![KAUST](https://img.shields.io/badge/KAUST-HYEX-red.svg)](https://github.com/hyex-research)

---

## 🗺️ **Overview**

Reservoir bathymetry is the missing link between remotely sensed water extent and storage. In arid and hyper-arid **ungaged basins**, bathymetric surveys are almost never available — so the Elevation–Area–Volume (EAV) relationship that ties surface area to volume has to be inferred. **EAVES** reconstructs it from the **Shuttle Radar Topography Mission (SRTM)** digital elevation model, exploiting the fact that SRTM was acquired in February 2000 — before many dams were constructed or filled, so the pre-impoundment valley topography is preserved in the DEM.

For each dam the pipeline:

1. **Locates** the dam site on the SRTM DEM and searches for an optimal wall placement across the valley
2. **Flood-fills** the pre-dam valley up to the spillway height to reconstruct the reservoir footprint
3. **Integrates** the depth–area relationship into a continuous EAV curve
4. **Fits** a power-law model $V = c \cdot A^b$ to parameterise the area–volume relationship
5. **Regionalises** the fitted exponent $b$ so that dams with unreliable SRTM fills still receive physically plausible parameters

The resulting `eaves_params.csv` provides the area–volume relationship for every dam in the study domain, enabling satellite-observed water extent to be converted into storage estimates for downstream hydrological modelling.

> **Provenance:** EAVES was developed and validated for the arid and hyper-arid dams of **Saudi Arabia**. The codebase is region-agnostic — it can be applied to any country for which the required inputs (SRTM tiles, MERIT Hydro, a dam catalogue, and satellite water-extent time series) are available.

## ⚙️ **Method**

### Dam wall placement

The algorithm searches for a terrain-derived dam wall across the valley at or near the catalogued dam coordinates. Six placement stages are attempted in sequence, from fastest to most exhaustive:

| Stage | Strategy | Description |
|-------|----------|-------------|
| 1 | **Fast path** | Try terrain-derived wall angles at the nominal location |
| 2 | **Upstream walk** | Walk upstream along the valley thalweg and retry at each position |
| 3 | **Quality recovery** | Re-search if the initial fill is geometrically suspect (downstream-skewed or too small) |
| 4 | **River-direction retry** | Shift anchor along the river-network flow vector |
| 5 | **Relaxed alignment** | Allow wall orientations that would normally be rejected by the flow-alignment filter |
| 6 | **Fallback** | Multi-direction flood fill without an explicit wall |

### EAV curve construction

Once the footprint is established, elevation bins (0.5 m intervals) are used to compute area at each level. Cumulative trapezoidal integration yields volume. A two-parameter power law ($V = c \cdot A^b$) is fitted via non-linear least squares.

### Regionalization

Dams with reliable SRTM-derived curves (quality grades A–B, $R^2 \geq 0.98$) provide training data. A capacity-based threshold separates dams where SRTM resolution is sufficient from those where it is not. For unreliable dams, the exponent $b$ is assigned via regional median (or regression if $R^2 \geq 0.25$), and the coefficient $c$ is back-calculated from catalogue capacity and an empirical area estimate.

### Post-placement QC

Automated quality gates detect displaced flood centroids and negligible fill volumes, flagging problematic dams for regional parameter assignment rather than propagating unreliable fits.

## ⚠️ **Limitations**

EAVES reconstructs reservoir geometry from a pre-impoundment DEM — it is not a surveyed bathymetric record. Users should treat outputs as a best-effort approximation rather than absolute capacity.

- **Valley-geometry approximation, not bathymetry**: curves follow the SRTM valley surface up to the spillway, not a measured reservoir bottom. They are sensitive to DEM noise (±2 m vertical, ~10 m horizontal LE90) in the same way the underlying terrain is.
- **Synthetic dam wall**: the wall orientation and length come from a terrain-alignment search at or near the catalogue coordinates — it is the best-fit crest for that SRTM patch, not necessarily the engineered as-built structure. Small placement shifts can meaningfully change the reconstructed footprint.
- **SRTM snapshot (Feb 2000)**: dams constructed after 2000 get a clean pre-impoundment valley (ideal); dams predating 2000 carry whatever sediment and reservoir infill had already accumulated by the acquisition date, so their curves are partial rather than pre-dam.
- **Resolution-limited regimes**: sub-pixel reservoirs (`n_pixels < 30`), narrow valleys (`valley_width_m < 3 × pixel_size`), shallow depressions (`spillway_height_m < 5 m`), and urban-modified terrain produce curves with elevated uncertainty — see the `uncertainty_flags` column in `eaves_summary.csv` for per-dam tagging.

Full quantitative treatment of these limitations will be provided in the accompanying publication.

## 🔁 **Usage**

EAVES is configured via a JSON settings file that points to the input catalogues, external rasters/shapefiles, and the output directory. One reference config per region lives in `settings/`:

- `settings/<country>.json` — full regional run (paths under `region/<country>/`)

### Full run

```bash
conda activate eaves
python run_eaves.py --settings settings/<country>.json
```

### Other flags

| Flag | Effect |
|------|--------|
| `--plot-only` | Skip per-dam calculation and regenerate plots from existing results |
| `--only id_120000 id_020017 ...` | Process only the listed dam IDs |
| `--rebuild-domain` | Rebuild the preprocessing cache (MERIT clip + segment split + dam snap) instead of loading from `<domain_dir>/` |

### Testing

Test workflow is pytest-only. The 9-dam fixture + its internal settings file live under `tests/fixture/`.

```bash
pytest -m "not slow"    # fast sanity suite (~1 s)
pytest -m slow          # full 9-dam regression run (~5 min); writes to tests/fixture/output/ and compares SHA256s to tests/golden_hashes.json
pytest                  # everything
```

### Settings file

A settings file is a flat JSON object with any subset of the keys accepted by `eaves.config.configure`. Typical fields:

| Key | Purpose |
|-----|---------|
| `output_dir`, `srtm_dir`, `dams_csv`, `water_extent_dir`, `domain_dir` | Paths to local inputs / outputs |
| `merit_rivers_shp`, `merit_basins_shp`, `country_shp` | External shapefiles for preprocessing |
| `target_country`, `country_name_col` | Country filter applied to `country_shp` |
| `bathymetry_eav_csv` *(optional)* | Sonar EAV table for validation plots |
| `grdl_dir` *(optional)* | Folder of GRDL reference curves ([Hao et al. 2024](https://doi.org/10.1029/2023WR035781)) for validation plots |
| `sedimentation_dir` *(optional)* | Folder with `sedimentation_yield.csv` + `owe_annual_mean.csv` to merge into `eaves_summary.csv` (currently KSA-specific, see [Dash et al. 2025](https://doi.org/10.1016/j.jenvman.2025.127199)) |
| `max_seg_len_m`, `max_snap_distance_m` | Preprocessing knobs |

Unknown keys raise `ValueError` — a typo in a settings file fails loudly rather than silently reverting to defaults.

## 🗂️ **Repository Structure**

```text
.
├── run_eaves.py                 # Thin CLI wrapper (delegates to eaves.__main__)
│
├── eaves/                       # Core Python package
│   ├── __init__.py              # Package metadata
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
│       ├── plots.py             # Diagnostic + validation plots, QC flood maps
│       ├── regionalization.py   # Reliability tagging, threshold analysis, parameter assignment
│       ├── reliability.py       # Physical uncertainty flags (sub-pixel, narrow valley, etc.)
│       └── external_data.py     # Merge optional sedimentation / OWE columns into summary
│
├── settings/                    # Reference settings
│   ├── <country>.json           # Full regional run (paths under region/<country>/)
│   └── test.json                # 9-dam example fixture (paths under tests/fixture/)
│
├── region/                      # Per-region spatial runs
│   └── <country>/               # Full regional deployment
│       ├── input/               # Region inputs (licensed / user-provided)
│       │   ├── <country>_dams/  # Dam catalogue CSV, water-extent time series
│       │   │   └── sedimentation_owe/  # Optional sediment yield + OWE CSVs (e.g. Dash et al. 2025 for KSA)
│       │   ├── grdl/            # Reference EAV curves for validation dams
│       │   └── domain_inputs/   # Preprocessing cache (rivers_split, dams_snapped)
│       └── output/              # Generated outputs
│           ├── 0_check_dams/    # Per-dam flood QC maps (100 DPI)
│           ├── 1_results_csv/   # Summary CSVs, EAV tables, failed dams
│           │   └── eav_tables/  # Individual dam EAV curves ({dam_id}_eav.csv)
│           └── 2_results_plots/ # Analysis figures (300 DPI)
│
├── tests/                       # Test suite + shared 9-dam fixture
│   ├── conftest.py              # Session fixtures (repo_root, fixture_output, golden_hashes)
│   ├── test_smoke.py            # Fast sanity checks (imports, settings validation)
│   ├── test_regression.py       # Slow: reruns the fixture, compares SHA256s
│   ├── golden_hashes.json       # Expected-output spec for the regression test
│   └── fixture/                 # Self-contained 9-dam fixture
│       ├── settings.json        # Pytest-internal settings (paths under fixture/)
│       ├── input/               # Dams subset + water-extent TS + preprocessing cache + GRDL
│       └── output/              # Pipeline outputs written by `pytest -m slow` (committed for reference)
│
├── pytest.ini                   # Pytest config (registers `slow` marker)
├── environment.yml              # Conda environment specification
├── LICENSE                      # CC BY 4.0
└── README.md
```

## 📊 **Outputs**

### CSV files (`output/1_results_csv/`)

| File | Description |
|------|-------------|
| `eaves_summary.csv` | One row per successfully processed dam: fitted $c$, $b$, $R^2$, footprint area, quality grade, placement method, reliability flags (`uncertainty_flags`, `uncertainty_score`), and — when `sedimentation_dir` is provided — `sed_yield_t_ha_yr`, `upstream_area_km2`, `owe_mm_year` |
| `eaves_params.csv` | Final EAV parameters for **all** dams with a `source` label of `srtm_derived`, `regr_derived`, or `regi_derived` |
| `failed_dams.csv` | Dams that failed placement or QC, with failure reason |
| `threshold_analysis.csv` | Capacity-threshold sweep for reliability classification |
| `bathymetry_validation.csv` | Sonar bathymetry vs SRTM comparison data (only when `bathymetry_eav_csv` is set) |

### Analysis plots (`output/2_results_plots/`)

| Plot | Panels | Description |
|------|--------|-------------|
| `exponent_diagnostics.png` | a, b, c | Histogram of $b$, exponent vs dam height, spatial map |
| `threshold_analysis.png` | a, b | Quality grade scatter, reliability fraction vs threshold |
| `bathymetry_validation.png` | a, b | Sonar bathymetry vs SRTM: area–volume and elevation–area |
| `grdl_validation.png` | a–d | GRDL reference vs SRTM (area–volume and elevation–area panels) |
| `regression_diagnostics.png` | a, b, c | LOO predictions, feature importances, residuals (if regression $R^2 \geq 0.25$) |

### Flood QC maps (`output/0_check_dams/`)

One PNG per dam showing the DEM, flood footprint, river network overlay, a red triangle at the dam location, and a darkorange line indicating the chosen dam-wall orientation and length. After regionalization each plot is renamed to reflect the parameter source: `{dam_id}_srtm.png` (direct SRTM fit), `{dam_id}_regr.png` (topographic regression), or `{dam_id}_regi.png` (regional median).

## 📥 **Data dependencies**

EAVES runs standalone — all preprocessing (country clip, segment split, dam snap) is done inside the package. The settings file points to the external rasters and shapefiles; licensed or bulky data is not redistributed.

### Included in this repository

- 9-dam example fixture (`tests/fixture/`) — dams CSV subset + water-extent time series + preprocessing cache + GRDL reference curves
- GRDL reference EAV curves per region (`region/<country>/input/grdl/` — user-provided)

### External (referenced by path in the settings file)

| Dataset | Source | Purpose |
|---------|--------|---------|
| **SRTM GL1 v003** (1 arc-second, ~30 m) | [NASA/USGS SRTMGL1](https://lpdaac.usgs.gov/products/srtmgl1v003/) — tiles mirrored at [ESA STEP](https://step.esa.int/auxdata/dem/SRTMGL1/) | Pre-dam valley topography |
| **MERIT Hydro v0.7** (pfaf_level_1) | [Yamazaki et al. 2019](https://hydro.iis.u-tokyo.ac.jp/~yamadai/MERIT_Hydro/) | River network + basins (clipped to country during preprocessing) |
| **Natural Earth admin boundaries** (10 m, lakes-cut) | [naturalearthdata.com](https://www.naturalearthdata.com/downloads/10m-cultural-vectors/) | Country polygon for clipping MERIT |
| **Dam catalogue** (e.g. `<country>_dams.csv`) | User-provided | Dam locations, attributes, capacities |
| **Filtered satellite water extent** | User-provided | Empirical area estimates for regionalization |
| **GRDL reference curves** (optional) | [Hao et al. 2024](https://doi.org/10.1029/2023WR035781) | Deep-learning-derived global area–storage–depth reference set used for cross-validation plots (`grdl_validation.png`) |
| **Sonar bathymetry** (optional) | Field survey | Ground-truth validation for one or more reservoirs |
| **Sedimentation & evaporation** (optional, KSA-specific) | [Dash et al. 2025](https://doi.org/10.1016/j.jenvman.2025.127199) | Per-dam sediment yield (t ha⁻¹ yr⁻¹), upstream catchment area (km²), and open-water evaporation (mm yr⁻¹), merged into `eaves_summary.csv` when `sedimentation_dir` is set |

> **Note on SRTM data:** EAVES uses `.hgt` tiles from the Shuttle Radar Topography Mission Global 1 arc-second dataset (SRTMGL1 v003), acquired in February 2000. Tiles can be downloaded from [USGS EarthExplorer](https://earthexplorer.usgs.gov/) or the [ESA STEP mirror](https://step.esa.int/auxdata/dem/SRTMGL1/). The Saudi dam catalogue used in this study is not publicly available.

## 📦 **Installation**

```bash
conda env create -f environment.yml
conda activate eaves
```

Key dependencies: `numpy`, `scipy`, `pandas`, `geopandas`, `rasterio`, `pyproj`, `matplotlib`, `scikit-learn`, `tqdm`.

## 📜 **License**

This work is licensed under a [Creative Commons Attribution 4.0 International License](https://creativecommons.org/licenses/by/4.0/).

[![CC BY 4.0](https://licensebuttons.net/l/by/4.0/88x31.png)](https://creativecommons.org/licenses/by/4.0/)
