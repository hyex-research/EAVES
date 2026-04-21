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

## 🔁 **Usage**

EAVES is configured via a JSON settings file that points to the input catalogues, external rasters/shapefiles, and the output directory. Reference deployments live in `settings/`:

- `settings/<country>.json` — full regional run
- `settings/test.json` — 9-dam example fixture under `test/`

### Full run

```bash
conda activate eaves
python run_eaves.py --settings settings/<country>.json
```

### Test run (9 example dams, ~5 min end-to-end)

```bash
python run_eaves.py --settings settings/test.json
```

### Other flags

| Flag | Effect |
|------|--------|
| `--plot-only` | Skip per-dam calculation and regenerate plots from existing results |
| `--only id_120000 id_020017 ...` | Process only the listed dam IDs |
| `--rebuild-domain` | Rebuild the preprocessing cache (MERIT clip + segment split + dam snap) instead of loading from `<domain_dir>/` |

### Settings file

A settings file is a flat JSON object with any subset of the keys accepted by `eaves.config.configure`. Typical fields:

| Key | Purpose |
|-----|---------|
| `output_dir`, `srtm_dir`, `dams_csv`, `water_extent_dir`, `domain_dir` | Paths to local inputs / outputs |
| `merit_rivers_shp`, `merit_basins_shp`, `country_shp` | External shapefiles for preprocessing |
| `target_country`, `country_name_col` | Country filter applied to `country_shp` |
| `max_seg_len_m`, `max_snap_distance_m` | Preprocessing knobs |

Unknown keys raise `ValueError` — a typo in a deployment file fails loudly rather than silently reverting to defaults.

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
│       └── regionalization.py   # Reliability tagging, threshold analysis, parameter assignment
│
├── settings/                    # Reference deployment configurations
│   ├── <country>.json           # Full regional run
│   └── test.json                # 9-dam example fixture
│
├── input/                       # Deployment inputs (gitignored; licensed data)
│   ├── <country>_dams/          # Dam catalogue CSV, water-extent time series
│   ├── grdl/                    # Reference EAV curves for validation dams
│   └── domain_inputs/           # Preprocessing cache (rivers_split, dams_snapped)
│
├── output/                      # Generated outputs (gitignored)
│   ├── 0_check_dams/            # Per-dam flood QC maps (100 DPI)
│   ├── 1_results_csv/           # Summary CSVs, EAV tables, failed dams
│   │   └── eav_tables/          # Individual dam EAV curves ({dam_id}_eav.csv)
│   └── 2_results_plots/         # Analysis figures (300 DPI)
│
├── test/                        # 9-dam example fixture (committed)
│   ├── input/                   # Dams subset + water-extent TS + preprocessing cache
│   └── output/                  # Expected outputs after running settings/test.json
│
├── environment.yml              # Conda environment specification
├── LICENSE                      # CC BY-NC 4.0
└── README.md
```

## 📊 **Outputs**

### CSV files (`output/1_results_csv/`)

| File | Description |
|------|-------------|
| `eaves_summary.csv` | One row per successfully processed dam: fitted $c$, $b$, $R^2$, footprint area, quality grade, placement method |
| `eaves_params.csv` | Final EAV parameters for **all** dams (SRTM-direct + regionalized fallback) |
| `failed_dams.csv` | Dams that failed placement or QC, with failure reason |
| `threshold_analysis.csv` | Capacity-threshold sweep for reliability classification |
| `bathymetry_validation.csv` | Sonar bathymetry vs SRTM comparison data |

### Analysis plots (`output/2_results_plots/`)

| Plot | Panels | Description |
|------|--------|-------------|
| `exponent_diagnostics.png` | a, b, c | Histogram of $b$, exponent vs dam height, spatial map |
| `threshold_analysis.png` | a, b | Quality grade scatter, reliability fraction vs threshold |
| `bathymetry_validation.png` | a, b | Sonar bathymetry vs SRTM: area–volume and elevation–area |
| `grdl_validation.png` | a–d | GRDL reference vs SRTM (area–volume and elevation–area panels) |
| `regression_diagnostics.png` | a, b, c | LOO predictions, feature importances, residuals (if regression $R^2 \geq 0.25$) |

### Flood QC maps (`output/0_check_dams/`)

One PNG per dam showing the DEM, flood footprint, river network overlay, and dam marker. Named by dam ID (e.g., `id_120000_flood.png`).

## 📥 **Data dependencies**

EAVES runs standalone — all preprocessing (country clip, segment split, dam snap) is done inside the package. The settings file points to the external rasters and shapefiles; licensed or bulky data is not redistributed.

### Included in this repository

- 9-dam example fixture (`test/input/`) — dams CSV subset + water-extent time series + preprocessing cache
- GRDL reference EAV curves (`input/grdl/` — user-provided)

### External (referenced by path in the settings file)

| Dataset | Source | Purpose |
|---------|--------|---------|
| **SRTM GL1 v003** (1 arc-second, ~30 m) | [NASA/USGS SRTMGL1](https://lpdaac.usgs.gov/products/srtmgl1v003/) — tiles mirrored at [ESA STEP](https://step.esa.int/auxdata/dem/SRTMGL1/) | Pre-dam valley topography |
| **MERIT Hydro v0.7** (pfaf_level_1) | [Yamazaki et al. 2019](https://hydro.iis.u-tokyo.ac.jp/~yamadai/MERIT_Hydro/) | River network + basins (clipped to country during preprocessing) |
| **Natural Earth admin boundaries** (10 m, lakes-cut) | [naturalearthdata.com](https://www.naturalearthdata.com/downloads/10m-cultural-vectors/) | Country polygon for clipping MERIT |
| **Dam catalogue** (e.g. `<country>_dams.csv`) | User-provided | Dam locations, attributes, capacities |
| **Filtered satellite water extent** | User-provided | Empirical area estimates for regionalization |
| **Sonar bathymetry** (optional) | Field survey | Ground-truth validation for one or more reservoirs |

> **Note on SRTM data:** EAVES uses `.hgt` tiles from the Shuttle Radar Topography Mission Global 1 arc-second dataset (SRTMGL1 v003), acquired in February 2000. Tiles can be downloaded from [USGS EarthExplorer](https://earthexplorer.usgs.gov/) or the [ESA STEP mirror](https://step.esa.int/auxdata/dem/SRTMGL1/). The Saudi dam catalogue used in this study is not publicly available.

## 📦 **Installation**

```bash
conda env create -f environment.yml
conda activate eaves
```

Key dependencies: `numpy`, `scipy`, `pandas`, `geopandas`, `rasterio`, `pyproj`, `matplotlib`, `scikit-learn`, `tqdm`.

## 📜 **License**

This work is licensed under a [Creative Commons Attribution-NonCommercial 4.0 International License](https://creativecommons.org/licenses/by-nc/4.0/).

[![CC BY-NC 4.0](https://licensebuttons.net/l/by-nc/4.0/88x31.png)](https://creativecommons.org/licenses/by-nc/4.0/)
