# EAVES test suite

Three layers, in order of cost.

## Layers

| File | Marker | Runtime | What it covers |
| --- | --- | --- | --- |
| `test_smoke.py` | (none) | < 1 s | Imports, settings loading, constants. Run on every push. |
| `test_regionalization.py` | (none) | a few seconds | Unit tests for the multi-feature LR helpers in `eaves/postprocess/regionalization.py`. |
| `test_panels_helpers.py` | (none) | a few seconds | Unit tests for the s1 / s2 supplementary-panel helpers (`_silhouette_curve`, `_loo_cluster_sigma`, `_baseline_sigma`, `_chosen_threshold`). |
| `test_regression.py` | `slow` | ~5 min | End-to-end: re-runs the 15-dam fixture through `run_eaves.py` and compares every emitted CSV against the SHA-256 golden hashes in `golden_hashes.json`. |

## Running

```bash
pytest                       # fast tests only (smoke + unit)
pytest -m slow               # the regression test in isolation
pytest -m "not slow"         # explicit fast subset
pytest -k regionalization    # one file by keyword
pytest test/test_smoke.py -v
```

The first run of the regression test invokes the full pipeline; subsequent runs in the same `pytest` session reuse the `fixture_output` session-scoped fixture.

## The 15-dam fixture

`test/fixture/input/dams_example.csv` lists 15 dams chosen to exercise every code path the production pipeline takes, without exceeding ~5 min wall time on a workstation:

- **12 dams** that produce SRTM-derived curves — 4 large, 4 medium, 4 small reservoirs.
- **3 dams** that fail SRTM placement and fall through to regionalization (`id_010007`, `id_020072`, `id_030036`).

If you add a dam to the fixture, the slow test will fail because the CSVs change. Update `golden_hashes.json` after verifying the new outputs are correct (see below).

## Settings

`test/fixture/settings.json` points the pipeline at the fixture inputs and at a writable `test/fixture/output/` tree. It uses the same SRTM tiles, MERIT shapefiles, and country shapefile as the production KSA run — those paths are absolute and machine-specific.

If you need to run the tests on a different machine, override those paths in `settings.json` or set the corresponding environment variables before `pytest`.

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
root = Path('test/fixture/output')
csvs = sorted(p for p in root.rglob('*.csv'))
out = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in csvs}
Path('test/golden_hashes.json').write_text(json.dumps(out, indent=2) + '\n')
"

# 4. commit golden_hashes.json with the same commit that changed behavior
```

## Common gotchas

- **Stale domain cache.** If you change the dam catalogue or the rivers shapefile, delete `test/fixture/input/domain_inputs/` and rerun with `--rebuild-domain` (the pipeline caches MERIT clips per catchment).
- **Slow test takes longer than expected.** A single bad SRTM tile or a dam with a very large reservoir can dominate runtime. The fixture was curated to avoid the worst offenders — if you swap a dam, re-time the run.
- **Floating-point drift between machines.** The golden hashes are byte-exact. Different NumPy / GDAL / SciPy versions can produce slightly different floats. Hashes were last refreshed on the workstation listed in the project README; if you see hash mismatches but the values look identical, regenerate the goldens.
- **PNG timestamps.** PNGs under `0_check_dams/` get rewritten on every run with a new timestamp in the metadata. The regression test only hashes CSVs, so this is not a problem.
