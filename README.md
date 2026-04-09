# 🏔️💧 **EAVES — Elevation–Area–Volume Estimation from SRTM**

*Reconstructing reservoir bathymetry for Saudi dams from pre-impoundment SRTM topography.*

---

[![Python](https://img.shields.io/badge/python-3.14-blue.svg)](environment.yml)
[![DOI](https://img.shields.io/badge/DOI-pending-yellow.svg)](#)
[![KAUST](https://img.shields.io/badge/KAUST-HYEX-red.svg)](https://github.com/hyex-research)

---

## 🗺️ **Overview**

Reservoir storage dynamics are central to the **RUSH** hydrological model, yet bathymetric surveys are unavailable for the vast majority of Saudi dams. **EAVES** reconstructs **Elevation–Area–Volume (EAV) curves** from the **Shuttle Radar Topography Mission (SRTM)** digital elevation model, exploiting the fact that SRTM was acquired in February 2000 — before many dams were constructed or filled.

For each dam the pipeline:

1. **Locates** the dam site on the SRTM DEM and searches for an optimal wall placement across the valley
2. **Flood-fills** the pre-dam valley up to the spillway height to reconstruct the reservoir footprint
3. **Integrates** the depth–area relationship into a continuous EAV curve
4. **Fits** a power-law model $V = c \cdot A^b$ to parameterise the area–volume relationship
5. **Regionalises** the fitted exponent $b$ so that dams with unreliable SRTM fills still receive physically plausible parameters

The resulting `eaves_params.csv` provides the area–volume relationship for every dam in the RUSH domain, enabling satellite-observed water extent to be converted into storage estimates for model calibration.

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

### Full run (compute EAV curves + plots + regionalization)

```bash
conda activate eaves
python run_eaves.py
```

### Plot-only mode (skip calculation, regenerate plots from existing results)

```bash
python run_eaves.py --plot-only
```

### Process specific dams

```bash
python run_eaves.py --only id_120000 id_020017
```

### Force recalculation when combined with plot-only

```bash
python run_eaves.py --plot-only --rerun
```

## 🗂️ **Repository Structure**

```text
.
├── run_eaves.py                 # Thin CLI wrapper
│
├── eaves/                       # Core Python package
│   ├── __init__.py              # Package metadata
│   ├── __main__.py              # CLI entry point (argparse, multiprocessing, CSV I/O)
│   ├── config.py                # Paths, constants, caches, matplotlib rcParams
│   ├── utils.py                 # Math helpers, override loaders, SRTM/UTM utilities
│   ├── terrain.py               # DEM loading, clipping, reprojection, flow direction
│   ├── placement.py             # Wall search, flood fill, upstream walk (6 stages)
│   ├── curves.py                # Per-dam EAV curve construction (process_dam)
│   ├── regionalization.py       # Reliability tagging, threshold analysis, parameter assignment
│   ├── plots.py                 # All plotting functions (analysis-style + QC flood maps)
│   └── workers.py               # Multiprocessing workers
│
├── input/                       # Input data
│   └── GRDL/                    # GRDL reference curves (Baish, Hali, Rabigh)
│
├── output/                      # Generated outputs
│   ├── 0_check_dam_flood/       # Per-dam flood QC maps (100 DPI)
│   ├── 1_results_csv/           # Summary CSVs, EAV tables, failed dams
│   │   └── eav_tables/          # Individual dam EAV curves ({dam_id}_eav.csv)
│   └── 2_results_plots/         # Analysis figures (300 DPI)
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
| `eaves_params.csv` | Final EAV parameters for **all** dams (SRTM-direct + regionalized + Baish sonar override) |
| `failed_dams.csv` | Dams that failed placement or QC, with failure reason |
| `threshold_analysis.csv` | Capacity-threshold sweep for reliability classification |
| `baish_validation.csv` | Baish sonar vs SRTM comparison data |

### Analysis plots (`output/2_results_plots/`)

| Plot | Panels | Description |
|------|--------|-------------|
| `exponent_diagnostics.png` | a, b, c | Histogram of $b$, exponent vs dam height, spatial map |
| `threshold_analysis.png` | a, b | Quality grade scatter, reliability fraction vs threshold |
| `baish_validation.png` | a, b | Sonar bathymetry vs SRTM: area–volume and elevation–area |
| `grdl_comparison.png` | a–f | GRDL reference vs SRTM for Baish, Hali, Rabigh |
| `regression_diagnostics.png` | a, b, c | LOO predictions, feature importances, residuals (if regression $R^2 \geq 0.25$) |

### Flood QC maps (`output/0_check_dam_flood/`)

One PNG per dam showing the DEM, flood footprint, river network overlay, and dam marker. Named by dam ID (e.g., `id_120000_flood.png`).

## 📥 **Data Dependencies**

### Included in this repository

- GRDL reference EAV curves (`input/GRDL/`)

### External (referenced by path in `config.py`)

| Dataset | Source | Purpose |
|---------|--------|---------|
| **SRTM GL1 v003** (1 arc-second, ~30 m) | [NASA/USGS SRTMGL1](https://lpdaac.usgs.gov/products/srtmgl1v003/) — tiles mirrored at [ESA STEP](https://step.esa.int/auxdata/dem/SRTMGL1/) | Pre-dam valley topography |
| **RUSH domain GeoJSON** (`gdf_dams_subset_snapped.geojson`) | RUSH `A01_domain_input.py` | Dam locations, attributes, river network |
| **Baish sonar bathymetry** | Field survey (2025) | Ground-truth validation |
| **Satellite water extent** (filtered time series) | RUSH `A03_dam_input.py` | Empirical area estimates for regionalization |

> **Note on SRTM data:** EAVES uses `.hgt` tiles from the Shuttle Radar Topography Mission Global 1 arc-second dataset (SRTMGL1 v003), acquired in February 2000. Tiles can be downloaded from [USGS EarthExplorer](https://earthexplorer.usgs.gov/) or the [ESA STEP mirror](https://step.esa.int/auxdata/dem/SRTMGL1/). The dam catalogue used in this study is not publicly available.

## 🎛️ **Key Parameters**

Processing parameters are defined in `eaves/config.py`:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `BIN_Z` | 0.5 m | Elevation bin spacing for EAV integration |
| `WALL_THICKNESS` | 3 px | Virtual dam wall thickness |
| `UPSTREAM_MAX_SHIFT_PX` | 100 px | Maximum upstream walk distance |
| `MAX_CREST_FLOW_DOT` | 0.74 | Flow-alignment filter for wall orientation |
| `TERRAIN_WALL_TOP_K` | 18 | Number of candidate wall angles to evaluate |
| `_PLACEMENT_BUDGET_S` | 300 s | Per-dam time budget for placement search |

## 📦 **Installation**

```bash
conda env create -f environment.yml
conda activate eaves
```

Alternatively, EAVES runs within the parent RUSH conda environment (`conda activate rush`) if already installed.

Key dependencies: `numpy`, `scipy`, `pandas`, `geopandas`, `rasterio`, `pyproj`, `matplotlib`, `scikit-learn`, `tqdm`.

## 📄 **Related Manuscript**

EAVES is part of the RUSH modelling framework, accompanying the manuscript:

> Ivanović et al. (2026). *Title TBD.* Nature Water.

## 📜 **License**

This work is licensed under a [Creative Commons Attribution-NonCommercial 4.0 International License](https://creativecommons.org/licenses/by-nc/4.0/).

[![CC BY-NC 4.0](https://licensebuttons.net/l/by-nc/4.0/88x31.png)](https://creativecommons.org/licenses/by-nc/4.0/)
