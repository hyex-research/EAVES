# Usage

EAVES is configured via a JSON settings file that points to the input catalogs, external rasters/shapefiles, and the output directory. Each region keeps its config alongside its inputs and outputs in `region/<country>/`.

## Full run

```bash
conda activate eaves
python run_eaves.py --settings region/<country>/<country>.json
```

## End-to-end (pipeline + validation + uncertainty + panels + report)

```bash
./run_all.sh region/<country>/<country>.json
```

Defaults to `region/ksa/ksa.json` if no settings file is supplied. Runs five steps in order: the placement-and-fit pipeline, LOO regionalization validation, V-uncertainty propagation, panel figures (p1-p5 main + s1-s5 supplementary), and the prose Markdown report. The order matters: panels read validation and uncertainty outputs, and the report embeds the freshly rendered panels. Set `RUN_TESTS=1 ./run_all.sh ...` to additionally rebuild the 15-dam test fixture and refresh `test/golden_hashes.json`.

## Other flags

| Flag | Effect |
| ---- | ------ |
| `--plot-only` | Skip per-dam calculation and regenerate plots from existing results |
| `--only id_120000 id_020017 ...` | Process only the listed dam IDs |
| `--rebuild-domain` | Rebuild the preprocessing cache (MERIT clip + segment split + dam snap) instead of loading from `<domain_dir>/` |

## Validation diagnostics

`eaves.postprocess.validation` runs three cheap internal-consistency diagnostics by default: the LOO regionalization evaluation, the DEM-vs-satellite-P95 area check, and the deployed-direction goodness-of-fit residual. Each is skippable with `--skip-loo`, `--skip-area-check`, `--skip-gof`. It also hosts two heavier diagnostics that are opt-in (off by default) because each re-runs the real flood fill many times. Both are param-safe: they never call regionalization, never overwrite `eaves_params.csv` or any released artifact, and write only their own CSV under `validation/`.

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

`--sensitivity` perturbs the three swept placement/acceptance constants (`ALIGN_WEIGHT`, `MAX_CREST_FLOW_DOT`, `VOID_THRESHOLD`) one at a time by 20-30% over a trusted-dam sample and reports how the trusted-set size, grade distribution, and median `b` move. `--dem-mc` perturbs the SRTM mosaic with spatially correlated Gaussian noise (point sigma ~3.6 m, LE90 ~6 m) and re-fits, reporting the fractional spread of recovered volume and `b`. The DEM-MC writes each dam's row incrementally with a per-dam wall-clock budget, so a killed run is resumable: re-launch to skip dams already in the CSV, or pass `--dem-mc-fresh` to start over.

## Testing

The test workflow is pytest-only. The 15-dam fixture and its internal settings file live under `test/fixture/`.

```bash
pytest -m "not slow"    # fast sanity suite (~25 s)
pytest -m slow          # full 15-dam regression run (~5 min), writes test/fixture/output/ and checks SHA256s
pytest                  # everything
```

## Settings file

A settings file is a flat JSON object with any subset of the keys accepted by `eaves.config.configure`. Typical fields:

| Key | Purpose |
| --- | ------- |
| `output_dir`, `srtm_dir`, `dams_csv`, `water_extent_dir`, `domain_dir` | Paths to local inputs and outputs |
| `merit_rivers_shp`, `merit_basins_shp`, `country_shp` | External shapefiles for preprocessing |
| `target_country`, `country_name_col` | Country filter applied to `country_shp` |
| `bathymetry_eav_csv`, `bathymetry_dam_id` *(optional)* | Sonar/design EAV table for the cross-reference panels |
| `grdl_dir` *(optional)* | Folder of GRDL reference curves ([Hao et al. 2024](https://doi.org/10.1029/2023WR035781)) for the cross-reference panels |
| `sedimentation_dir` *(optional)* | Folder with `sedimentation_yield.csv` + `owe_annual_mean.csv` to merge into `eaves_summary.csv` (currently KSA-specific, see [Dash et al. 2025](https://doi.org/10.1016/j.jenvman.2025.127199)) |
| `max_seg_len_m`, `max_snap_distance_m` | Preprocessing knobs |

Unknown keys raise `ValueError`: a typo in a settings file fails loudly rather than silently reverting to defaults.
