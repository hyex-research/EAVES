# Changelog

All notable changes to EAVES are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
The project adheres to [Semantic Versioning](https://semver.org/).

## [1.3.2] - 2026-10-07

### Added

- **`depth_m` in every EAV table** (`eaves.pipeline.workers`). The column
  stands beside `elevation_m` and gives the water depth above the bottom
  of the fill, the elevation of the row minus that of the first row. Every
  other column keeps its values.
- **Rule against a pool downstream of the dam**
  (`eaves.pipeline.placement`, `DOWNSTREAM_POOL_RIVER_SHARE`,
  `DOWNSTREAM_POOL_SLOPE_SHARE` and `DOWNSTREAM_POOL_BUFFER_PX` in
  `eaves.config`). Every placement stage rejects a pool when at least 90%
  of it lies down the river reach from the dam cell and more than half of
  it lies down the terrain slope. A pool on open ground can drain out
  along its whole rim and pass the drainage rule, and this rule judges it
  by its position. Either direction alone can point the wrong way at a
  dam, so a pool is rejected only when both place it downstream. On the
  Saudi Arabian catalog the flood fill of one dam changes (`id_030038`).
  Its parameters become regionalized and its grade moves from A to C. The
  failure of `id_030036` reads `placement_failed` in place of
  `bad_fill_auto`. Every other flood fill, EAV table and check plot stays
  as it is.

### Changed

- **Construction years of 20 dams of the Saudi Arabian catalog**
  (`region/ksa/input/ksa_dams/ksa_dams_transliterated.csv`). The catalog
  gains the year of 20 dams that had none, the year in which satellite
  imagery shows the finished dam (2009 to 2025). All 20 postdate the SRTM
  acquisition. One dam stays without a year (`id_030038`), a historical
  dam older than the acquisition. The 20 dams lose the `unknown_year`
  flag, and 17 of them are trusted and join the training set, which grows
  from 199 to 216 dams. The sediment budget covers 525 dams in place of
  505, and the era table lists 1 dam without a year in place of 21.
- **Regionalized parameters follow from the larger training set.** The
  regional exponent moves from 1.5345 to 1.5291, and `c` and `b` of the
  207 regionalized dams change, `c` by −9.9% to +15.8% with a median of
  +6.2%. The parameters of the 319 SRTM-derived dams stay as they are. The
  leave-one-out validation covers 216 dams, with 93% of the predictions
  within a factor of 2 and all of them within a factor of 3.
- **Report** (`eaves.postprocess.report`). The paragraph on dams without a
  construction year reads correctly for a single dam.
- **Tests.** `test/test_drainage.py` gains five tests of the rule against
  a pool downstream of the dam.

## [1.3.1] - 2026-10-05

### Changed

- **`eaves_summary.csv` holds every dam of `eaves_params.csv`** (`eaves.cli`,
  `eaves.utils.dams_with_fill`). A dam without a flood fill gains a row with
  its catalog attributes, coordinates, topographic features, upstream area,
  sediment yield, evaporation and sediment risk. The cells of its fill and
  of its fit are empty, and `n_pixels` is empty for such a row alone. On
  the Saudi Arabian catalog the summary grows from 503 to 526 rows, and
  the 503 existing rows keep every value. `failed_dams.csv` lists the
  failures as before. The statistics, the validation tables, the figures
  and the report describe the dams with a flood fill, as before.
- **The regionalization reads every dam from the summary**
  (`eaves.postprocess.regionalization`). A dam without a flood fill is
  regionalized from the features of its summary row, at the precision of
  the released table, as a dam with an untrusted fill already was. The
  parameters of every dam follow from `eaves_summary.csv` alone, and the
  full run, `--plot-only` and `--only` write the same tables. On the Saudi
  Arabian catalog the coefficient `c` of 4 dams without a flood fill
  changes in its fourth significant digit (`id_030039`, `id_080026`,
  `id_090008`, `id_130016`), and `A_cap_km2` of the first three follows
  in `validation/v_uncertainty.csv`. Every other value of the released
  tables and every figure stays as it is.
- **The catalog statistics of the report span every dam**
  (`eaves.postprocess.report`). The construction-year breakdown, the dam
  height statistics and the sediment budget are computed over all dams of
  the summary, as the capacity statistics already were. The statistics of
  the fill and of the fit keep to the dams with a flood fill. On the Saudi
  Arabian catalog the era table sums to 526 dams, 21 of them of unknown
  year, and the sediment budget covers 505 dams in place of 483, with a
  median predicted capacity loss of 44.4% and 151 dams at full siltation.
- **Tests.** `test/test_summary_rows.py` pins the row of a dam without a
  flood fill, the selection of the dams with one and the column order of
  the external attributes. `test/test_regression.py` checks that the
  summary of the fixture run holds every dam of the parameter table, and
  that `--plot-only` and a single-dam `--only` run reproduce the tables of
  the full run. The golden hash of the fixture summary follows its two
  added rows.

### Fixed

- **`--only` keeps `eaves_params.csv` complete** (`eaves.cli`,
  `eaves.postprocess.regionalization`). A single-dam run handed the
  regionalization the failures of its subset alone, which removed every
  other dam without a flood fill from the parameter table.
- **`--plot-only` keeps the summary as written** (`eaves.cli`,
  `eaves.postprocess.external_data`). The table was rewritten with the
  construction years as floats, and with `sed_yield_t_ha_yr` and
  `owe_mm_year` moved behind the two sediment columns of the report step.
  The full run and `--plot-only` write the summary through one function,
  and a second pass of `add_sedimentation_columns` leaves every column in
  its place.

## [1.3.0] - 2026-10-04

### Changed

- **Dam coordinates checked against satellite imagery** in
  `region/ksa/input/ksa_dams/ksa_dams_transliterated.csv`. Every catalog
  coordinate was viewed on high-resolution imagery and the flagged ones
  rechecked by hand. In all, 28 coordinates that fell off the wall, by 12 m to
  4.8 km, now sit on it, and 6 entries with no wall visible at the
  coordinate are typed `subsurface`. `clean_catalogue.py` excludes dams by
  that catalog type alone, and its hand lists of recharge dams and of
  non-sites are gone. The non-site list held entries that were not found at
  their uncorrected coordinates, and the 6 of them with a confirmed wall
  (Al-Is, Nasifat Aban Al-Ahmar, Fihan, Sharaqib, Tahallul, Zalawam) return
  to the catalog, which holds 526 dams. The SRTM footprint and the curve
  of a dam are read at its coordinate, so every output is regenerated at
  the corrected coordinates and for the corrected dam set.
- **River parts follow the channel** (`eaves.preprocess`). Each part of a
  reach longer than `max_seg_len_m` is the piece of the channel between two
  cut points and carries an equal share of the reach length and
  unit-catchment area, in place of a straight chord between the cut points.
  On the Saudi Arabian network the chords of a split reach summed to a
  median 83% of its length. The end nodes of every part stay where they
  are. A dam snaps by its distance to the channel itself, and the flow
  direction that orients its wall follows the channel around the dam.
- **The river network is closed upstream** (`eaves.preprocess`). A reach
  that touches the country keeps every reach that drains into it, so a dam
  next to the border keeps its channel. Shab Maghawarah (`id_120006`) and
  Al-Madirah (`id_120008`), which lie just beyond the country outline, gain
  a channel to snap to. The cached domain inputs are rebuilt on this
  network, which holds 12,592 reaches in 69,884 parts and snaps 335 of the
  526 dams.
- **The flood fill is read as a labeled component**
  (`eaves.pipeline.placement.flood_fill_8`). The fill is the 8-connected
  component of cells at or below the water level that holds the seed, taken
  from one labeling of the DEM window in place of a cell-by-cell walk. The
  masks are identical and the fill runs about two orders of magnitude
  faster, which brings the placement of most dams from minutes to seconds.
  A dam that exhausted the placement time budget now completes its search,
  so its curve can differ. On the Saudi Arabian catalog this concerns
  four dams.
- **A fill must drain out through the wall** (`eaves.pipeline.drainage`,
  `eaves.pipeline.placement`). The DEM window is flooded from its edge
  inward in order of elevation, which gives each cell the cell it drains
  to, and a fill is accepted only when at least half of the pool it holds
  at catalog capacity leaves that pool within the half wall plus 1 km
  (`DRAIN_MIN_SHARE`, `DRAIN_WALL_TOLERANCE_M`) and when its outlets lie in
  the dam-side 65% of the pool's own length (`DRAIN_MAX_OUTLET_POSITION`),
  which judges a pool shorter than that distance. A fill on the downstream
  side of the wall drains out at its far end and is rejected, whichever
  way the local slope at the dam points. The rule reads the DEM and the
  catalog dam length only. On the Saudi Arabian catalog the rule changes
  the fill of 20 dams, among them Hafar Al-Batin (`id_050001`), takes the
  fill from 2 and lets 5 more reach one.
- **Zero-length reaches leave the river network** (`eaves.preprocess`).
  The hydrography stores a closed depression whose catchment just reaches
  the channel threshold as a reach of zero length that links to itself.
  Such a reach is a single cell and not a channel, so it is dropped before
  the network is clipped and no dam can snap to it.
- **The run is faster with identical results** (`eaves.cli`,
  `eaves.pipeline.workers`, `eaves.pipeline.placement`,
  `eaves.postprocess.sensitivity`). The river network is handed to each
  worker once when it starts in place of with every dam, the largest
  reservoirs start first, the scan of wall angles is vectorized, and the
  sensitivity sweep runs its sample dams in parallel. On the Saudi Arabian
  catalog the per-dam stage runs about six times faster and the sweep
  about fourteen times faster.
- **Released tables carry a fixed precision**
  (`eaves.utils.round_released_columns`). Every table writer rounds its
  floating-point columns to four significant digits and never fewer than
  two decimals, in place of full machine precision. `capacity_mcm`, the
  exponent `b` and the columns named after it keep four decimals, and the
  coordinates and dam dimensions are written as they come from the
  catalog. The volume that a
  released curve gives at full pool differs from the unrounded one by
  less than 0.2%.
- **Stage 4 keeps a candidate only when it improves the volume match**
  (`eaves.pipeline.curves`). The river-direction retry moves the wall
  along the snapped river, upstream and downstream, and replaces the
  earlier fill only when the volume of the candidate lies closer to the
  catalog capacity. It replaced a fill whenever the candidate pool sat
  more compactly at the dam, which exchanged good fills for worse ones.
  `placement_upstream_shift_m` is positive upstream and negative
  downstream. On the Saudi Arabian catalog the fill of 7 dams changes,
  5 of them toward the catalog capacity, and 5 dams stay at stage 4.
- **The river direction is named for what it holds**
  (`eaves.pipeline.terrain.get_river_direction_from_segment`). The unit
  vector along the snapped reach points up the channel, and the names in
  `terrain`, `curves` and `placement` say so, with identical results.
- **Figure 2b shows Marikh** (`id_020000`) as its stage 4 example
  (`eaves.postprocess.panels.p2`). Hafar Al-Batin (`id_050001`) is placed
  at stage 1 under the drainage rule.
- **A_cap regression diagnostics run with the validation step**
  (`eaves.postprocess.validation`). `validation/acap_regression_diagnostics.csv`
  is written with the default diagnostics and skipped with `--skip-acap`.
- **The sensitivity sweep covers the drainage rule**
  (`eaves.postprocess.sensitivity`, panel `s5`). The sweep perturbs
  `DRAIN_WALL_TOLERANCE_M` and `DRAIN_MAX_OUTLET_POSITION` beside the three
  placement constants. On the Saudi Arabian sample of 54 trusted dams the
  trusted set does not react to the wall tolerance between 700 m and
  1,300 m, and a tighter outlet position (0.52 and 0.455) removes one and
  two dams from it.
- **The regression fixture is self-contained** (`test/fixture/`). The
  fixture ships the SRTM GL1 elevation around its 15 dams (17 files, about
  6 MB, built by `test/build_fixture_srtm.py`), so the regression test runs
  with the tracked settings alone. `test/fixture/settings.json` carries no
  machine paths. Paths inside the repository are relative to the settings
  file, and the three shapefiles that only a domain rebuild reads are
  placeholders. The test suite uses an untracked `settings_local.json`
  beside it when that file exists, and `.gitignore` excludes `*_local.json`.
- **Hydrography named by its product** (`documentation/data-dependencies.md`).
  The river reaches and unit catchments are the MERIT-Basins vector product
  (Lin et al. 2019), which is built on MERIT Hydro (Yamazaki et al. 2019).
- **Documentation follows one style.** The Markdown documents, the
  generated report, the code comments and the docstrings follow the same
  writing rules: US English, no em-dashes, no semicolon or colon joining
  two clauses, Unicode exponents in place of caret notation, and one line
  per code comment. Run times in the documents are measured values.
- **Released outputs regenerated** on the corrected catalog with the
  changes above. `eaves_params.csv` holds 526 dams, 320 with an
  SRTM-derived curve and 206 regionalized, of which 23 have no flood fill.
  The regionalization trains on 199 dams and its exponent is 1.53. The
  leave-one-out volume at full pool falls within a factor of 2 for 185 of
  the 199 training dams (93%) and within a factor of 3 for all of them.
  Baish (`id_120000`) keeps its curve.
- **Tests.** `test/test_preprocess.py` pins the split to the reach, the
  upstream closure and the removal of zero-length reaches, and
  `test/test_drainage.py` pins the drainage of a DEM window and the
  drain-through-the-wall rule, and `test/test_curves_helpers.py` pins the
  released precision. The 15-dam fixture is regenerated with Buwah
  (`id_020077`) at its corrected coordinate, and the golden hashes follow
  the regenerated tables.

### Fixed

- **Hali dam height** (`id_020019`) set from 87 m to 57 m, its published
  height above the riverbed (95 m above the foundation). The catalog measures
  dam and spillway heights from the riverbed at the dam, and 87 m gave Hali
  a 40 m freeboard over its 47 m spillway instead of 10 m. Recorded in
  `region/ksa/input/ksa_dams/clean_catalogue.py`. Hali's curve fills to the
  spillway, and `dam_height_m` is a feature of the A_cap regression, so the
  regionalized curves are refit with the corrected height.
- **Dam count of the report** (`eaves.postprocess.report`). The domain
  characterization added all failed records to the dams with a flood fill
  and so counted the dams with a fill and a failed fit twice. It now adds
  the dams without a fill, 503 and 23 on the Saudi Arabian catalog.
- **Construction year in `failed_dams.csv`** is written as an integer, as
  in `eaves_summary.csv`. It was written as a float.
- **DEM error panel** (`eaves.postprocess.panels.s4`). The panel left out
  one dam by its identifier. It leaves out every dam with fewer than 10
  valid realizations.
- **Arrows of the check plots** (`eaves.pipeline.terrain`). The arrows on
  the snapped river reach pointed upstream. They point downstream.
- **Numbers of the report text** (`eaves.postprocess.report`). The report
  quoted the median exponent of the trusted dams as the regional exponent
  and carried fixed values for the floors of the uncertainty band and for
  the spread of the alternative anchors. It reads the exponent assigned
  to the regionalized dams, the floors and the spreads from the tables of
  the run.
- **A second pass of the report step keeps the summary as written**
  (`eaves.postprocess.report`). The sediment columns of an earlier pass
  are cut as text. The table was rewritten before, which turned the
  construction years into floats.

## [1.2.1] - 2026-06-15

### Changed

- **Dam name corrected**: `id_020023` Qununa -> Qanuna across the catalog,
  caches, and released CSVs (label only, no recomputation, and the Arabic name
  is unchanged).
- **README slimmed** to overview, quickstart, and links, with a
  `documentation/` folder (method, structure, outputs, data dependencies,
  usage) and direct links to the released curves. Em-dashes and stray
  semicolons removed across the README, the docs, CHANGELOG, CITATION, the
  data dictionary, and the generated report.

### Added

- `latitude` / `longitude` columns in `failed_dams.csv`, completing the
  paper's data-availability promise (coordinates for all 526 cataloged
  dams, including the 22 without a recovered footprint).

### Removed

- Output panel PDFs (`region/<region>/output/2_results_plots/*.pdf`) are no
  longer tracked. The PNGs remain. PDFs are regenerated locally and shipped
  with the manuscript.

### Fixed

- **Baish capacity reverted to the spillway-crest value (193.644 MCM).**
  The 1.2.0 change to 198.072 MCM misread the design table, whose header
  states a design storage capacity of 193,644,000 m³ with the spillage top
  level at 327 m a.s.l., and whose 198.072 MCM row is annotated
  "Spillway + 0.50" (327.5 m a.s.l.), a half-meter surcharge above the
  crest rather than storage capacity. The catalog, the snapped-dams cache,
  and the Baish comparison table (327.5 m row removed) are corrected, and
  the fill cap returns to the spillway level (recovered maximum 197.2 MCM,
  a one-bin +1.8% overshoot; refit c = 0.0077, b = 1.506; total catalog
  storage 2,442 -> 2,437 MCM). The released CSVs, validation, uncertainty
  band, panels, and report were regenerated, and the stale
  `ksa_dams_transliterated.csv.bak` snapshot was removed.

## [1.2.0] - 2026-06-11

### Changed

- **Regionalization now trains only on post-SRTM dams.** The training set is
  the trusted fits whose construction year is 2000 or later (200 of 322).
  Pre-2000 and unknown-year dams may sit on an already partially silted
  valley floor, so they ship their own SRTM curves but no longer train the
  recipe, the exponent spread b_σ, the clustering diagnostic, the
  A_cap regression, or the leave-one-out validation. Small
  populations (CI fixtures, data-poor regions) fall back to the full trusted
  set below 15 training dams. Deployed regionalized exponent moves
  1.50 -> 1.56 (median over the capacity-thresholded training subset). LOO
  headline improves to 92%/99% within factor 2/3 (median bias +6%,
  MedAPE 29%, relRMSE 47%). Band terms re-estimated
  (b_σ 0.2657, σ(log A_cap) 0.149,
  σ(log V_cap) 0.142).
- **Catalog-capacity uncertainty term re-estimated without cap censoring.**
  Capped fills pin the SRTM-to-catalog volume ratio near unity, so the term
  is now the spread over the uncapped training fills only
  (0.074 -> 0.142, i.e. the SRTM-derived band floor moves from +19%/-16%
  to a deliberately conservative +39%/-28%).
- **Baish capacity sourced from the design documentation.** `id_120000`
  now carries the design-table storage at the maximum water level
  (198.072 MCM), the primary source for this dam, in place of the
  national-catalog spillway-level value (193.644 MCM), so the fill cap
  reflects the full design envelope. Recovered maximum 201.3 MCM (one-bin overshoot, +1.6%).
  Total catalog storage 2,437 -> 2,442 MCM.

### Added

- **`pre_srtm` uncertainty flag** (6th flag): marks dams built before the
  February 2000 SRTM acquisition, whose curves describe the as-of-2000
  (possibly partially silted) surface. 178 dams flagged on the Saudi domain.
- **`in_training` column** in `validation/goodness_of_fit.csv`.
- **`documentation/` folder** (method, structure, outputs, data
  dependencies, usage). `README.md` slimmed to overview, quickstart, and
  links.
- **Open-axes panel style**: top/right spines removed across p3 (b, c),
  p4, p5, and s1-s5 (s2 panel b keeps its right spine for the twin bar
  axis).
- Central `trusted_mask` / `training_mask` helpers in
  `postprocess/reliability.py`, replacing five duplicated gate definitions.

### Fixed

- Log-log anchor residual factor was rendered as `10**rms` on natural-log
  residuals in `report.md` (a factor of ~3.4 instead of the correct ~1.7).
- `acap_regression_diagnostics` now evaluates on the training population.
- `domain_characterization.csv` log-log anchor stats (`loglog_alpha`,
  `loglog_resid_rms`) are now in log10 units, matching the stated error
  convention (previously natural log, and the report rendered the residual
  factor with the wrong base).
- `failed_dams.csv` gains a `construction_year` column so the pre-2000
  status of footprint-less dams is recoverable.

## [1.1.0] - 2026-06-10

### Fixed

- **Clamped exponents now re-solve c through the SRTM full-pool anchor.**
  The released b is clamped to [1.1, 2.0]. Previously the raw c was
  kept, so the 39 clamped SRTM-derived curves missed their own full-pool
  volume by factors of 0.004–11. c is now re-solved so that
  V(A_DEM) = V_SRTM exactly for every clamped dam
  (`regionalization.py`; `eaves_params.csv` updated for the 39 dams, all
  other rows bit-identical).
- **Sediment budget no longer double-counts delivery.** The
  `sed_yield_t_ha_yr` input is _delivered_ yield. Dash et al. (2025,
  Eqs. 2–4) already multiply RUSLE gross erosion by the Boyce (1974)
  delivery ratio at the source, so the additional Vanoni (1975) SDR was
  removed from the budget. `predicted_silt_fraction` and `sediment_risk`
  recomputed (median predicted loss 13.7% → 47.5%; fully-silted count
  44 → 149). Verified at Baish (budget now within ~1.6× of the 2025 sonar
  loss, previously ~10× under) and nationally (implied 32% capacity loss
  matches the figure published with the same yields). `--sediment-sdr`
  remains available as a constant factor for gross-erosion inputs.
- **Panel S3 SRTM band formula.** The SRTM-derived uncertainty tier now
  includes the catalog-capacity term (σ(log V_cap)),
  matching `validation/v_uncertainty.csv`. It was previously drawn from
  b_σ alone and appeared to vanish at the anchor.

### Changed

- Report and data-dictionary text: the catalog-capacity cap on the flood
  fill is disclosed explicitly, the SRTM uncertainty tier is described as
  floored by the catalog-capacity term rather than vanishing at the anchor,
  and the software-versions table was dropped from `report.md`.

## [1.0.1] - 2026-06-01

### Changed

- **Missing construction years are no longer fabricated as 2001.** Dams with
  no catalogue year now carry `construction_year = <NA>` (nullable `Int32`,
  blank in `eaves_summary.csv`) instead of a sentinel 2001. The flat-water
  detector now runs for unknown-year dams as well as pre-2000 dams, so the
  SRTM surface itself decides full vs partial, removing the circular
  assumption that an absent year implied a post-2000, bare-valley capture.
- **Domain characterization keeps unknown-year dams visible.** A
  `n_year_unknown` count and a "Year unknown" row in the era breakdown retain
  them in the population. Only age-dependent statistics (era assignment,
  sediment budget) exclude them, since computing those without a build year
  would require fabricating one.

### Notes

- EAV parameters (c, b) are unchanged by this edit (verified bit-identical
  across all 526 KSA dams). The flat-water check returned "bare valley" for
  every missing-year SRTM dam, so each kept `curve_type = full` and the same
  fit path.

### Added

- **`test_curves_helpers.py`**: locks construction-year parsing, including a
  guard that a missing year never returns the old 2001 sentinel.
- **`test_uncertainty.py`**: unit coverage for the uncertainty module
  (`compute_b_sigma`, anchor back-solve, V-band algebra) backing panel S3.
- Extracted `curves._parse_construction_year()` as a directly testable helper
  (pipeline output verified unchanged).

## [1.0.0] - 2026-05-18

First tagged release. Production-ready EAV curve assignment for
SRTM-derived reservoir bathymetry. Outputs are now consumed by
downstream simulation.

### Added

- **Multi-feature LR anchor** for A_cap on log-space
  morphometry (`capacity_mcm`, `dam_height_m`, `spillway_height_m`,
  `valley_ratio`, `channel_slope`, `mean_catchment_slope`,
  `upstream_area_km2`). Trained on the regional trusted set, applied to
  every regionalized dam via closed-form back-solve
  c = V_cap / A_cap<sup>b</sup>. LOO accuracy on trusted
  dams: 89% within 2×, median absolute error 28%, median bias +7%.
- **`eaves.postprocess.uncertainty` module** and CLI. Propagates the
  LOO-derived b_σ to a per-dam V band at half / quarter / tenth
  pool, and writes `validation/v_uncertainty.csv`.
- **Supplementary panel S1**: K-means clustering diagnostic on b
  (silhouette + LOO σ(Δb)). Backs the report's argument
  for using the global-median b.
- **Supplementary panel S2**: capacity-threshold sweep for the
  reliability cut.
- **Supplementary panel S3**: V uncertainty propagation: Baish worked
  example with ±b_σ fan band, plus the universal
  σ(log₁₀ V) curve.
- **Software-version block** in `report.md` (numpy, scipy, pandas,
  sklearn, rasterio, geopandas, matplotlib, pyproj, shapely, Python)
  for reproducibility.
- **`run_all.sh`** orchestrator: 5-stage pipeline → validation →
  uncertainty → panels → report. Every panel emits both PNG (300 dpi)
  and vector PDF.
- **Unit tests** for s1/s2 helpers (`_silhouette_curve`,
  `_loo_cluster_sigma`, `_baseline_sigma`, `_chosen_threshold`), 19
  tests, ~2 s.

### Changed

- **`eaves_params.csv` schema** stabilized on 6 lean columns
  (`dam_id`, `dam_name`, `capacity_mcm`, `c`, `b`, `source`).
  Per-dam confidence metrics moved to `validation/v_uncertainty.csv`.
- **Source label** for regionalized rows renamed
  `regi_derived` → `regi_multi` to reflect the multi-feature anchor.
- **Regression goldens** refreshed after the `upstream_area_km2`
  enrichment fix, with 52 fast tests + 1 slow regression test passing.
- **Uniform typography** across every panel: 10 pt body, 12 pt panel
  labels, sentence case, US English.
- **Markdown table separators** in `report.md` use spaced form
  (`| --- |`) for compatibility with strict renderers.

### Fixed

- **`failed_dams.csv` enrichment**: placement-failure rows now carry
  `capacity_mcm`, `dam_height_m`, `spillway_height_m`, and
  `upstream_area_km2` from the catalogue and sedimentation yield CSV,
  so the regionalization recipe can reach them. This pulled 20 of 21
  dams out of the log–log fallback into the multi-feature LR branch.
- **Saturated SRTM fits** (b pinned at the 1.10 / 2.00 clip
  boundaries) now correctly demoted to the regional median by the
  tightened quality gates.

### Notes

- One dam (`id_120014`, Shahdan) remains on the log–log fallback
  branch due to `valley_ratio = NaN` from failed topography extraction
  in a narrow steep wadi.
- Bathymetric ground truth in this region is limited to Baish
  (`id_120000`). Broader campaigns would be needed to tighten the
  sediment-loss budget beyond the first-order estimate currently
  reported.

[1.3.2]: https://github.com/hyex-research/EAVES/releases/tag/v1.3.2
[1.3.1]: https://github.com/hyex-research/EAVES/releases/tag/v1.3.1
[1.3.0]: https://github.com/hyex-research/EAVES/releases/tag/v1.3.0
[1.2.1]: https://github.com/hyex-research/EAVES/releases/tag/v1.2.1
[1.2.0]: https://github.com/hyex-research/EAVES/releases/tag/v1.2.0
[1.1.0]: https://github.com/hyex-research/EAVES/releases/tag/v1.1.0
[1.0.1]: https://github.com/hyex-research/EAVES/releases/tag/v1.0.1
[1.0.0]: https://github.com/hyex-research/EAVES/releases/tag/v1.0.0
