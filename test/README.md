# EAVES test suite

Three layers, in order of cost.

## Layers

| File | Marker | Runtime | What it covers |
| --- | --- | --- | --- |
| `test_smoke.py` | (none) | under 1 s | Imports, settings loading, constants. Run on every push. |
| `test_regionalization.py` | (none) | under 1 s | Unit tests for the multi-feature LR helpers in `eaves/postprocess/regionalization.py`. |
| `test_panels_helpers.py` | (none) | under 1 s | Unit tests for the s1 / s2 supplementary-panel helpers (`_silhouette_curve`, `_loo_cluster_sigma`, `_baseline_sigma`, `_chosen_threshold`). |
| `test_preprocess.py` | (none) | under 1 s | Unit tests for the domain preprocessing in `eaves/preprocess.py`: segment split, upstream closure, removal of zero-length reaches. |
| `test_drainage.py` | (none) | under 1 s | Unit tests for the drainage of a DEM window and the drain-through-the-wall rule in `eaves/pipeline/drainage.py`. |
| `test_curves_helpers.py` | (none) | under 1 s | Unit tests for the construction-year parsing in `eaves/pipeline/curves.py` and for the precision of the released tables (`round_released_columns` in `eaves/utils.py`). |
| `test_uncertainty.py` | (none) | under 1 s | Unit tests for the V uncertainty band in `eaves/postprocess/uncertainty.py`: `b_sigma` estimator, anchor back-solve, band algebra. |
| `test_sediment.py` | (none) | under 1 s | Unit tests for the sediment-budget helpers in `eaves/postprocess/report.py`: delivered-yield budget, trap-saturation cap, silt-risk bands. |
| `test_regression.py` | `slow` | about 80 s | End-to-end: re-runs the 15-dam fixture through `run_eaves.py` and compares every emitted CSV against the SHA-256 golden hashes in `golden_hashes.json`. |

Run times are measured on a 112-core workstation and grow as the core count falls. The fast tests (everything except the regression test) take about 3 s in total.

## Running

```bash
pytest                       # everything (fast tests + the slow regression test)
pytest -m slow               # the regression test in isolation
pytest -m "not slow"         # explicit fast subset
pytest -k regionalization    # one file by keyword
pytest test/test_smoke.py -v
```

The first run of the regression test invokes the full pipeline. Subsequent runs in the same `pytest` session reuse the `fixture_output` session-scoped fixture.

## The 15-dam fixture

`test/fixture/input/dams_example.csv` lists 15 dams chosen to exercise every code path the production pipeline takes, while the regression run stays at about 80 s on a 112-core workstation:

- **12 dams** that produce SRTM-derived curves (4 large, 4 medium, 4 small reservoirs).
- **3 dams** that receive regionalized parameters. `id_010007` (`placement_failed`) and `id_030036` (`bad_fill_auto`) have no flood fill, and `id_020072` has a fill graded C, below the trusted gates.

If you add a dam to the fixture, the slow test will fail because the CSVs change. Update `golden_hashes.json` after verifying the new outputs are correct (see below).

## Settings

`test/fixture/settings.json` points the pipeline at the fixture inputs and at a writable `test/fixture/output/` tree, with paths relative to the settings file. Every input a regression run reads sits under `test/fixture/input/`, so the regression test runs with the tracked settings and needs no external data.

Three paths in the file are placeholders (`/path/to/...`): the MERIT Hydro river shapefile, the MERIT Hydro basin shapefile, and the country shapefile. The pipeline reads them only when it rebuilds the domain cache with `--rebuild-domain`. To rebuild the cache, copy `settings.json` to `settings_local.json` in the same folder, set the three paths in the copy, and pass the copy to `run_eaves.py` together with `--rebuild-domain`. `settings_local.json` is ignored by git, and the test suite uses it whenever it exists.

`grdl_dir` names a folder the fixture does not ship. Only the `--panels` step reads it, and the regression run skips that step (see `conftest.py`).

## Running the regression test in CI

The fixture is self-contained. `pytest -m slow` runs from a fresh clone, in CI and on any machine, with the environment of `environment.yml` and no machine-specific path. `test/fixture/input/` holds every input of a regression run:

| Path | Content |
| --- | --- |
| `dams_example.csv` | The 15-dam catalog. |
| `water_extent_ts/` | The per-dam water-extent series. |
| `sedimentation_owe/` | The sedimentation and evaporation inputs. |
| `domain_inputs/` | The cached river and dam geometry (`rivers_split.geojson`, `dams_snapped.geojson`). |
| `srtm/` | The SRTM GL1 elevation around the 15 dams (17 files, about 6 MB). |

`srtm/` holds one file for every SRTM GL1 tile the pipeline opens for a fixture dam. Each file has the name, grid, georeference, data type and nodata value of the original tile. Cells inside the window the pipeline loads around a dam keep their elevation, and every other cell holds the nodata value. The window spans the dam buffer (0.03° to 0.12°, set by the storage capacity) plus the 0.02° loading margin and four cells of padding on every side, taken at the catalog coordinate and at the snapped coordinate of the dam. The files are deflate-compressed GeoTIFFs that carry the `.hgt` tile names, and GDAL identifies the format from the file content. The pipeline derives the same outputs from them as from the full tiles, byte for byte. SRTM GL1 is public domain data from NASA and USGS.

The elevation set covers the 15 fixture dams only. When a dam is added to the catalog or moved, rebuild the set from the full tiles with `python -m test.build_fixture_srtm --srtm-dir <full SRTM folder>`, run from the repository root.

## Golden hashes

`golden_hashes.json` stores SHA-256 hashes of every CSV the fixture produces. The regression test compares actual hashes to these expected values.

When a legitimate change alters the output schema or values (new column, fixed bug, recipe change), regenerate the goldens:

```bash
# 1. run the fixture end-to-end
python run_eaves.py --settings test/fixture/settings.json

# 2. inspect the new CSVs under test/fixture/output/1_results_csv/

# 3. once you're satisfied, regenerate golden_hashes.json
python -c "
import hashlib, json
from pathlib import Path
out = Path('test/fixture/output')
h = {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest()
     for p in sorted((out / '1_results_csv').rglob('*.csv'))}
Path('test/golden_hashes.json').write_text(json.dumps(h, indent=2, sort_keys=True))
"

# 4. commit golden_hashes.json with the same commit that changed behavior
```

## Common gotchas

- **Stale domain cache.** If you change the dam catalog or the rivers shapefile, delete `test/fixture/input/domain_inputs/` and rerun with `--rebuild-domain` (the pipeline reuses the cached `rivers_split.geojson` and `dams_snapped.geojson` whenever both exist).
- **Slow test takes longer than expected.** A single bad SRTM tile or a dam with a very large reservoir can dominate runtime. The fixture avoids the worst offenders. If you swap a dam, re-time the run.
- **Floating-point drift between machines.** The golden hashes are byte-exact. Different NumPy / GDAL / SciPy versions can produce slightly different floats. If you see hash mismatches but the values look identical, regenerate the goldens.
- **PNG timestamps.** PNGs under `0_check_dams/` get rewritten on every run with a new timestamp in the metadata. The regression test only hashes CSVs, so this is not a problem.
