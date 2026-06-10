# 🏔️💧 **EAVES — Elevation–Area–Volume Estimation from SRTM**

*Reconstructing reservoir bathymetry for ungaged arid-basin dams from pre-impoundment SRTM topography.*

---

[![Python](https://img.shields.io/badge/python-3.13-blue.svg)](environment.yml)
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
5. **Regionalizes** the fitted exponent $b$ and coefficient $c$ so that dams with unreliable SRTM fills still receive physically plausible parameters

The resulting `eaves_params.csv` provides the area–volume relationship for every dam in the study domain, enabling satellite-observed water extent to be converted into storage estimates for downstream hydrological modelling.

> **Provenance:** EAVES was developed and validated for the arid and hyper-arid dams of **Saudi Arabia**. The codebase is portable — it can be applied to any region for which the required inputs (SRTM tiles, MERIT Hydro, a dam catalogue, and satellite water-extent time series) are available.

## ⚙️ **Method**

### Dam wall placement

The algorithm searches for a terrain-derived dam wall across the valley at or near the catalogued dam coordinates. Six placement stages are attempted in sequence, from fastest to most exhaustive:

| Stage | Strategy | Description |
| ----- | -------- | ----------- |
| 1 | **Fast path** | Try terrain-derived wall angles at the nominal location |
| 2 | **Upstream walk** | Walk upstream along the valley thalweg and retry at each position |
| 3 | **Quality recovery** | Re-search if the initial fill is geometrically suspect (downstream-skewed or too small) |
| 4 | **River-direction retry** | Shift anchor along the river-network flow vector |
| 5 | **Relaxed alignment** | Allow wall orientations that would normally be rejected by the flow-alignment filter |
| 6 | **Fallback** | Multi-direction flood fill without an explicit wall |

### EAV curve construction

Once the footprint is established, elevation bins (0.5 m intervals) are used to compute area at each level. Cumulative trapezoidal integration yields volume. A two-parameter power law ($V = c \cdot A^b$) is fitted via non-linear least squares.

### Regionalization

Dams with reliable SRTM-derived curves (quality grades A–B, $R^2 \geq 0.98$, $0.3 \leq V_\mathrm{SRTM}/V_\mathrm{cap} \leq 5.0$, $n_\mathrm{pixels} \geq 50$) provide training data. For dams that fail those quality gates, parameters are assigned by a single closed-form recipe:

- **Exponent $b$** — regional median over the trusted dams (or a multivariate regression on `valley_ratio`, `channel_slope`, `mean_catchment_slope`, `dam_height_m` if its leave-one-out $R^2 \geq 0.25$, which rarely holds for arid catchments).
- **Coefficient $c$** — back-solved as $c = V_\mathrm{cap}/A_\mathrm{cap}^{b}$ from catalogue capacity and a multi-feature linear regression that predicts $\log A_\mathrm{cap}$ from seven log-space features: `capacity_mcm`, `dam_height_m`, `spillway_height_m`, `valley_ratio`, `channel_slope`, `mean_catchment_slope`, `upstream_area_km2`. Any feature that is missing for a given dam is imputed with the training-set median so the regression always returns a finite value.

Leave-one-out cross-validation on the trusted set quantifies the recipe's accuracy. For the Saudi Arabia deployment: median bias $\times 1.07$ of the SRTM-derived reference, $1\sigma$ spread $0.18$ log10 units, 89% of predictions within a factor of 2 and 98% within a factor of 3. See `eaves.postprocess.validation` and panel `p5` for the full per-recipe comparison and the rationale for retiring two earlier candidates (a satellite-anchored recipe and a single-feature log–log regression).

### Post-placement QC

Automated quality gates detect displaced flood centroids and negligible fill volumes, flagging problematic dams for regional parameter assignment rather than propagating unreliable fits.

## ⚠️ **Limitations**

EAVES reconstructs reservoir geometry from a pre-impoundment DEM — it is not a surveyed bathymetric record. Users should treat outputs as a best-effort approximation rather than absolute capacity.

- **Valley-geometry approximation, not bathymetry**: curves follow the SRTM valley surface up to the spillway, not a measured reservoir bottom. They are sensitive to DEM noise (vertical LE90 ≈ 6 m for low-relief terrain) in the same way the underlying terrain is.
- **Synthetic dam wall**: the wall orientation and length come from a terrain-alignment search at or near the catalogue coordinates — it is the best-fit crest for that SRTM patch, not necessarily the engineered as-built structure. Small placement shifts can meaningfully change the reconstructed footprint.
- **SRTM snapshot (Feb 2000)**: dams constructed after 2000 get a clean pre-impoundment valley (ideal); dams predating 2000 carry whatever sediment and reservoir infill had already accumulated by the acquisition date, so their curves are partial rather than pre-dam.
- **Resolution-limited regimes**: sub-pixel reservoirs (`n_pixels < 30`), narrow valleys (`valley_width_m < 3 × pixel_size`), shallow depressions (`spillway_height_m < 5 m`), and urban-modified terrain produce curves with elevated uncertainty — see the `uncertainty_flags` column in `eaves_summary.csv` for per-dam tagging.

Full quantitative treatment of these limitations will be provided in the accompanying publication.

## 🔁 **Usage**

EAVES is configured via a JSON settings file that points to the input catalogues, external rasters/shapefiles, and the output directory. Each region keeps its config alongside its inputs and outputs in `region/<country>/`:

- `region/<country>/<country>.json` — full regional run (paths under `region/<country>/`)

### Full run

```bash
conda activate eaves
python run_eaves.py --settings region/<country>/<country>.json
```

### End-to-end (pipeline + validation + uncertainty + panels + report)

```bash
./run_all.sh region/<country>/<country>.json
```

Defaults to `region/ksa/ksa.json` if no settings file is supplied. Runs five steps in order — placement-and-fit pipeline, LOO regionalization validation, V-uncertainty propagation from `b_sigma`, panel figures (p1–p5 main + s1/s2/s3 supplementary; s1 computes the b-clustering diagnostic CSV on first invocation), prose Markdown report. Every panel is written as both a 300-dpi PNG (used by the report) and a vector PDF (for journal submission). The order matters: panels read validation and uncertainty outputs, and the report embeds the freshly-rendered panels. Set `RUN_TESTS=1 ./run_all.sh ...` to additionally rebuild the 15-dam test fixture and refresh `test/golden_hashes.json`.

### Other flags

| Flag | Effect |
| ---- | ------ |
| `--plot-only` | Skip per-dam calculation and regenerate plots from existing results |
| `--only id_120000 id_020017 ...` | Process only the listed dam IDs |
| `--rebuild-domain` | Rebuild the preprocessing cache (MERIT clip + segment split + dam snap) instead of loading from `<domain_dir>/` |

### Validation diagnostics

`eaves.postprocess.validation` runs three cheap, internal-consistency diagnostics by default — LOO regionalization evaluation, the $A_\mathrm{DEM}$ vs satellite-P95 area check, and the deployed-direction goodness-of-fit residual — each skippable with `--skip-loo`, `--skip-area-check`, `--skip-gof`. It also hosts two heavier diagnostics that are **opt-in (off by default)** because each re-runs the real flood-fill many times. Both are param-safe: they never call regionalization, never overwrite `eaves_params.csv` or any released artefact, and write only their own CSV under `validation/`.

```bash
# Cheap defaults only (what run_all.sh invokes):
python -m eaves.postprocess.validation --settings region/ksa/ksa.json

# Constant sensitivity sweep -> validation/sensitivity_sweep.csv
python -m eaves.postprocess.validation --settings region/ksa/ksa.json \
    --sensitivity [--sensitivity-n-dams 60] [--sensitivity-seed 7]

# SRTM vertical-error Monte-Carlo -> validation/dem_error_montecarlo.csv
python -m eaves.postprocess.validation --settings region/ksa/ksa.json \
    --dem-mc [--dem-mc-n-dams 36] [--dem-mc-n-real 32] \
    [--dem-mc-sigma-m 3.6] [--dem-mc-corr-px 2.0] [--dem-mc-workers 8]
```

`--sensitivity` perturbs the three hand-tuned placement/acceptance constants (`ALIGN_WEIGHT`, `MAX_CREST_FLOW_DOT`, `VOID_THRESHOLD`) one at a time by $\pm20$/$30\%$ over a trusted-dam sample and reports how the trusted-set size, grade distribution, and median $b$ move. `--dem-mc` perturbs the SRTM mosaic with spatially-correlated Gaussian noise (point $\sigma\approx3.6~\mathrm{m}$, LE90 $\approx 6~\mathrm{m}$) and re-fits, reporting the fractional spread of recovered volume and $b$. The DEM-MC writes each dam's row incrementally with a per-dam wall-clock budget, so a killed run is resumable — re-launch to skip dams already in the CSV, or pass `--dem-mc-fresh` to start over.

### Testing

Test workflow is pytest-only. The 15-dam fixture + its internal settings file live under `test/fixture/`.

```bash
pytest -m "not slow"    # fast sanity suite (~1 s)
pytest -m slow          # full 15-dam regression run (~5 min); writes to test/fixture/output/ and compares SHA256s to test/golden_hashes.json
pytest                  # everything
```

### Settings file

A settings file is a flat JSON object with any subset of the keys accepted by `eaves.config.configure`. Typical fields:

| Key | Purpose |
| --- | ------- |
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
│       ├── external_data.py     # Merge optional sedimentation / OWE columns into summary
│       ├── validation.py        # LOO regionalization validation + DEM-vs-sat-area diagnostic; opt-in --sensitivity / --dem-mc steps
│       ├── sensitivity.py       # Opt-in: placement/acceptance constant sensitivity sweep (writes validation/sensitivity_sweep.csv)
│       ├── dem_error.py         # Opt-in: SRTM vertical-error Monte-Carlo (writes validation/dem_error_montecarlo.csv)
│       ├── uncertainty.py       # Propagate b_sigma to per-dam V uncertainty at standard fill levels
│       ├── report.py            # Domain-characterization CSV + Markdown report
│       └── panels/              # Publication panels (p1-p5 main, s1-s3 supplementary; PNG + PDF)
│
├── region/                      # Per-region spatial runs
│   └── <country>/               # Full regional deployment
│       ├── <country>.json       # Settings JSON for this region
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
├── test/                        # Test suite + shared 15-dam fixture
│   ├── conftest.py              # Session fixtures (repo_root, fixture_output, golden_hashes)
│   ├── test_smoke.py            # Fast sanity checks (imports, settings validation)
│   ├── test_regression.py       # Slow: reruns the fixture, compares SHA256s
│   ├── golden_hashes.json       # Expected-output spec for the regression test
│   └── fixture/                 # Self-contained 15-dam fixture
│       ├── settings.json        # Pytest-internal settings (paths under fixture/)
│       ├── input/               # Dams subset + water-extent TS + preprocessing cache + GRDL
│       └── output/              # Pipeline outputs written by `pytest -m slow` (committed for reference)
│
├── pytest.ini                   # Pytest config (registers `slow` marker)
├── environment.yml              # Conda environment specification
├── LICENSE                      # Apache-2.0 (code)
├── LICENSE-DATA                 # CC BY 4.0 (data products)
└── README.md
```

## 📊 **Outputs**

### CSV files (`output/1_results_csv/`)

| File | Description |
| ---- | ----------- |
| `eaves_summary.csv` | One row per successfully processed dam: fitted $c$, $b$, $R^2$, footprint area, quality grade, placement method, reliability flags (`uncertainty_flags`, `uncertainty_score`), `upstream_area_km2`, and — when `sedimentation_dir` is provided — `sed_yield_t_ha_yr` (delivered yield), `owe_mm_year`, plus the derived `predicted_silt_fraction` and `sediment_risk`. Sorted by `dam_id`. |
| `eaves_params.csv` | Lean per-dam parameter table: six columns (`dam_id`, `dam_name`, `capacity_mcm`, `c`, `b`, `source`) with no NaN cells. `source` is `srtm_derived` (DEM-fit) or `regi_multi` (multi-feature LR anchor). Sorted by `dam_id`. The 1$\sigma$ uncertainty on $b$ is a region-level scalar stored in `validation/v_uncertainty.csv` and `domain_characterization.csv` — not duplicated per row. |
| `failed_dams.csv` | Dams that failed placement or fit, with failure reason and the full feature set attached at failure time so the row is self-contained for regionalization. Sorted by `dam_id`. |
| `threshold_analysis.csv` | Capacity-threshold sweep used to select the reliability cut. |
| `domain_characterization.csv` | Key/value table of the domain statistics surfaced in `report.md`. |
| `validation/regionalization_loo.csv` | Per-dam LOO residuals of every regionalization recipe evaluated by `eaves.postprocess.validation`. |
| `validation/dem_vs_sat_area.csv` | Per-dam $A_\mathrm{DEM}$ vs satellite-P95 area comparison (diagnostic only). |
| `validation/b_clustering_diagnostic.csv` | Silhouette and LOO $\sigma(\Delta b)$ over $k$ for the raw-morphometry feature set; written by the s1 panel on first invocation. Backs supplementary figure S1 (justifies the global-median choice for $b$). |
| `validation/v_uncertainty.csv` | Per-dam V uncertainty propagated from `b_sigma` at half, quarter, and tenth pool (in log10 units and as +%/-% bands). Written by `eaves.postprocess.uncertainty`. Backs supplementary figure S3. |
| `validation/sensitivity_sweep.csv` | Per-cell trusted-set size, A–F grade counts, and median trusted $b$ as each of three placement/acceptance constants is perturbed $\pm20$/$30\%$. Written only by the opt-in `--sensitivity` step (see [Validation diagnostics](#validation-diagnostics)). |
| `validation/dem_error_montecarlo.csv` | Per-dam spread of recovered max volume and $b$ across SRTM vertical-error realizations, relative to the unperturbed reference. Written only by the opt-in `--dem-mc` step (see [Validation diagnostics](#validation-diagnostics)). |
| `eav_tables/{dam_id}_eav.csv` | Per-dam tabulated $(z, A, V)$ on half-integer-snapped elevation bins. |

### Panel figures (`output/2_results_plots/`, written only when `--panels` is requested)

Every panel is emitted as both a 300-dpi PNG (embedded in `report.md`) and a vector PDF with the same stem (for journal submission). The table below lists the PNG names; the PDFs live next to them under the same stem (e.g. `p1_domain_flowchart.pdf`).

| File | Description |
| ---- | ----------- |
| `p1_domain_flowchart.png` | Domain map (a) + pipeline flowchart (b) |
| `p2_placement.png` | Three worked placement examples illustrating the six-stage cascade |
| `p3_baish_example.png` | Worked example for the bathymetry-cross-referenced reservoir |
| `p4_comparison.png` | Cross-reference against sonar bathymetry (Baysh) and GRDL (3 reference dams). Methodologically distinct datasets — not validation in the strict sense |
| `p5_regionalization_validation.png` | LOO validation of the shipped regionalization recipe (the only true internal validation) |
| `s1_b_clustering_silhouette.png` | Supplementary: K-means clustering diagnostic for $b$ — silhouette vs $k$ and LOO $\sigma(\Delta b)$ vs $k$ on the raw morphometry feature set. Justifies the global-median choice for $b$. |
| `s2_threshold_analysis.png` | Supplementary: capacity-threshold sweep behind the reliability cut — $R^2$ vs reservoir size by quality grade, and fraction-reliable vs candidate cutoff. |
| `s3_uncertainty_band.png` | Supplementary: V uncertainty band derived from `b_sigma`. (a) Worked example on Baysh with the $\pm b_\sigma$ band pinned through the catalogue anchor; (b) the universal $\sigma(\log_{10}V)$ curve vs normalised area with the regional typical operational fill marked. |

Pipeline runs without `--panels` produce **no** files in `2_results_plots/`; only per-dam flood maps under `0_check_dams/` are written by the workers themselves.

### Flood QC maps (`output/0_check_dams/`)

One PNG per dam showing the DEM, flood footprint, river network overlay, a red triangle at the dam location, and a darkorange line indicating the chosen dam-wall orientation and length. After regionalization each plot is renamed to reflect the parameter source: `{dam_id}_srtm.png` (direct SRTM fit), `{dam_id}_regi.png` (multi-feature LR anchor).

## 📥 **Data dependencies**

EAVES runs standalone — all preprocessing (country clip, segment split, dam snap) is done inside the package. The settings file points to the external rasters and shapefiles; licensed or bulky data is not redistributed.

### Included in this repository

- 15-dam example fixture (`test/fixture/`) — dams CSV subset + water-extent time series + preprocessing cache + GRDL reference curves
- GRDL reference EAV curves per region (`region/<country>/input/grdl/` — user-provided)

### External (referenced by path in the settings file)

| Dataset | Source | Purpose |
| ------- | ------ | ------- |
| **SRTM GL1 v003** (1 arc-second, ~30 m) | [NASA/USGS SRTMGL1](https://lpdaac.usgs.gov/products/srtmgl1v003/) — tiles mirrored at [ESA STEP](https://step.esa.int/auxdata/dem/SRTMGL1/) | Pre-dam valley topography |
| **MERIT Hydro v0.7** (pfaf_level_1) | [Yamazaki et al. 2019](https://hydro.iis.u-tokyo.ac.jp/~yamadai/MERIT_Hydro/) | River network + basins (clipped to country during preprocessing) |
| **Natural Earth admin boundaries** (10 m, lakes-cut) | [naturalearthdata.com](https://www.naturalearthdata.com/downloads/10m-cultural-vectors/) | Country polygon for clipping MERIT |
| **Dam catalogue** (e.g. `<country>_dams.csv`) | User-provided | Dam locations, attributes, capacities |
| **Filtered satellite water extent** | User-provided | Empirical area estimates for regionalization |
| **GRDL reference curves** (optional) | [Hao et al. 2024](https://doi.org/10.1029/2023WR035781) | Deep-learning-derived global area–storage–depth reference set used for the cross-reference comparison panel (`p4_comparison.png`). Methodologically distinct from EAVES — not direct validation. |
| **Sonar bathymetry** (optional) | Field survey | Cross-reference anchor for one or more reservoirs. Measures *current operational* reservoir floor, distinct from the pre-impoundment topography EAVES integrates. |
| **Sedimentation & evaporation** (optional, KSA-specific) | [Dash et al. 2025](https://doi.org/10.1016/j.jenvman.2025.127199) | Per-dam sediment yield (t ha⁻¹ yr⁻¹), upstream catchment area (km²), and open-water evaporation (mm yr⁻¹), merged into `eaves_summary.csv` when `sedimentation_dir` is set |

> **Note on SRTM data:** EAVES uses `.hgt` tiles from the Shuttle Radar Topography Mission Global 1 arc-second dataset (SRTMGL1 v003), acquired in February 2000. Tiles can be downloaded from [USGS EarthExplorer](https://earthexplorer.usgs.gov/) or the [ESA STEP mirror](https://step.esa.int/auxdata/dem/SRTMGL1/). The Saudi dam catalogue used in this study is not publicly available.

## 📦 **Installation**

```bash
conda env create -f environment.yml
conda activate eaves
```

Key dependencies: `numpy`, `scipy`, `pandas`, `geopandas`, `rasterio`, `pyproj`, `matplotlib`, `scikit-learn`, `tqdm`.

## 📜 **License**

The source code is licensed under the [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0) (`LICENSE`). The data products — the EAVES dataset and the files under `region/<country>/output/`, archived on Zenodo — are licensed under [Creative Commons Attribution 4.0 International (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/) (`LICENSE-DATA`).

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://www.apache.org/licenses/LICENSE-2.0)
[![Data: CC BY 4.0](https://licensebuttons.net/l/by/4.0/88x31.png)](https://creativecommons.org/licenses/by/4.0/)
