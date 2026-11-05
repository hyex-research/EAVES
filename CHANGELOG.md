# Changelog

All notable changes to EAVES are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
The project adheres to [Semantic Versioning](https://semver.org/).

## [1.4.0] - 2026-11-04

### Added

- **Level-wise and two-segment residual statistics** in
  `validation/goodness_of_fit.csv` (`eaves.postprocess.validation`). Every
  curve gains the absolute fractional residual at full pool, its medians
  over four bands of the full-pool area, its departure at the typical
  satellite extent of the domain and the root-mean-square residual of the
  best two-segment fit in log space, over all fitted levels and over the
  levels holding at least a tenth of the maximum volume. The report states
  the trusted-set medians in its SRTM-derived curves section and
  `domain_characterization.csv` carries them under `fit_*`. The earlier
  columns are unchanged. Tests in `test/test_goodness_of_fit.py`.
- **The report states the leave-one-out shares at half and tenth pool,
  the sediment budget at the survey date against the surveyed loss, and
  the median band widths by curve source** (`eaves.postprocess.report`).
  The optional settings key `bathymetry_survey_date` (`YYYY-MM`) gives the
  date of the sonar survey, and a share short of 100 % prints with one
  decimal.

- **The full-pool area regression diagnostics gain a drop-one sweep**
  (`acap_regression_diagnostics` in `eaves.postprocess.regionalization`).
  One row per feature gives the leave-one-out RMS of log10 A_cap of the
  regression without that feature and the change from the full model, on
  the sign convention of the incremental rows. The rows are released in
  `validation/acap_regression_diagnostics.csv`.

- **Reservoir geometry diagram.** The method documentation illustrates the constant-width wedge and V-shaped valley, with their area-depth and area-volume exponents. The image and its drawing script are included in `documentation/img/geometry/`.
- **Agent-ready layer** (`eaves.agent.info`, `eaves.agent.mcp_server`,
  `eaves.cli`). `eaves info <settings>` prints the resolved settings, the
  layout of the output tree and the defaults of `eaves.config` for the
  keys the file leaves out as JSON, and runs nothing. `eaves mcp` serves
  read-only tools over the Model Context Protocol: the catalog of the
  five steps, the resolved configuration, which outputs of a run exist
  with the headline counts of its tables, the key tables and figures,
  the domain characterization and the results of single dams. The server
  needs the optional `mcp` extra. `AGENTS.md` is the operational brief
  for coding agents. The pipeline keeps its command and every flag, and
  `python -m eaves` and `run_eaves.py` exit with the code of the command.
- **JSON twin of the domain characterization**
  (`eaves.postprocess.report`). The report step writes
  `domain_characterization.json` beside `domain_characterization.csv`,
  the same statistics in the same order with typed values.
- **Panel p6 for the GRDL comparison** (`eaves.postprocess.panels.p6`,
  `eaves.postprocess.report`). The comparison with GRDL has a panel of
  its own, p6 (`p6_grdl_comparison`), a grid 187 mm wide of the
  area-volume (a) and depth-area (b) curves of GRDL and EAVES with one
  row per reference reservoir, each row with its own area ticks. The
  report quotes the mean absolute volume difference of EAVES from each
  GRDL curve at equal area.
- **Principal components in the clustering diagnostic**
  (`eaves.postprocess.panels.s1`, `eaves.postprocess.report`). Panel s1
  draws three panels of one height in one row 187 mm wide, where panel b
  shows the training dams in the plane of the first two principal
  components of the clustering features, colored by `b` and marked by
  the clusters at the best `k` of panel c.
  `validation/b_clustering_diagnostic.csv` carries the leave-one-out R²
  of the per-cluster median (`loo_r2`), the variance shares of the first
  two principal components (`pc1_var_share`, `pc2_var_share`) and the
  Spearman correlation of `b` with the first (`pc1_spearman_b`), and
  `domain_characterization.csv` repeats the last three as
  `b_cluster_pc1_var_share`, `b_cluster_pc2_var_share` and
  `b_cluster_pc1_spearman_b`, with the `k` of the silhouette peak
  (`b_cluster_silhouette_max_k`) and the leave-one-out R² at the best `k`
  (`b_cluster_best_loo_r2`).
- **Rank correlation of the exponent in the domain characterization**
  (`eaves.postprocess.report`). `domain_characterization.csv` records the
  strongest rank correlation of `b` with a single morphometric feature on
  the regression basis with its feature, the threshold and the size of
  that basis (`b_feature_rho_max`, `b_feature_rho_max_feature`,
  `reliability_threshold_mcm`, `n_regression_basis`). The same statistic
  on the clustering basis is recorded as `b_feature_rho_max_cluster` with
  its feature and `n_cluster_basis`.
- **Tests.** `test/test_agent_info.py`, `test/test_mcp.py` and
  `test/test_cli.py` cover the agent view on a synthetic output tree,
  the server, and the parser with the read-only commands.

### Changed

- **Zenodo identifiers.** The citation file and the README carry the concept
  DOIs of the software (10.5281/zenodo.20731019) and of the dataset
  (10.5281/zenodo.20728128), which resolve to the latest deposited version.
- **The fill ends at the spillway elevation or at the catalog capacity**
  (`eaves.pipeline.curves`). The area is counted at levels 0.5 m apart
  from the lowest represented elevation, and the spillway elevation
  itself is the last level. When the volume at the spillway exceeds the
  catalog capacity, the last level moves to the elevation where the
  integrated volume equals the capacity, found by bisection inside the
  step that crosses it, with the area inside that step running linearly
  between the bounding levels as the trapezoid rule assumes, so every
  capped fill ends exactly at its capacity. A regular level within a
  centimeter of the spillway or of the capped level gives way to it
  (`LEVEL_MERGE_M` in `eaves.config`), so no two rows of a table share
  an elevation. Before, the levels ran to the first 0.5 m step at or
  above the spillway and the cap acted on those steps, so a capped fill
  ended at the first step whose volume reached the capacity, and a fill
  whose volume crossed the capacity inside the last step kept the volume
  of that step. Every EAV table and `z_max`, `z_range`, `vol_ratio` and
  `capped` in the summary follow.
- **Figure 1 draws every dam at one marker size and adds an inset
  of southwestern Saudi Arabia** (`eaves.postprocess.panels.p1`). The
  map encodes the parameter source by color, marks the dams whose
  placement, fill or fit fails with crosses, carries one key, and draws
  the regionalized dams above the SRTM-derived ones. The inset in the
  southeast corner zooms on the window between Jeddah and Jizan, which
  holds about half of the catalog. A translucent veil covers
  everything outside the country. The catalog capacity is shown by
  Figure 4 and the catalog tables.
- **Figure 4 evaluates the regionalization at three fill levels**
  (`eaves.postprocess.panels.p4`). The top row compares predicted and
  SRTM-derived reference volumes at full, half and tenth pool with
  identical axes, panel d sets the error distribution of each level
  beside the median regionalized uncertainty band half-width of the same
  level, read from `validation/v_uncertainty.csv`, and panel e draws the
  binned median error against catalog capacity for the three levels.
  The last capacity bin includes the largest dam.
- **Figure 5 names the Baish survey curve "Survey", draws the
  SRTM power-law fit in dark red and marks the top of dead storage**
  (`eaves.postprocess.panels.p5`). Panel b now carries a dashed line at
  the lowest level of the design and survey tables, below which only the
  SRTM-derived curve continues. The figure draws the Baish area-volume (a)
  and elevation-area (b) curves and the volume-ratio distribution (c) in
  one row, and panel a carries only the power-law fit to the SRTM-derived
  area-volume pairs. The three reference lines of Figure 3c are drawn
  heavier.
- **The released exponent is bounded below at 1, with no upper bound**
  (`eaves.postprocess.regionalization`, `B_LOWER_BOUND` in
  `eaves.config`). The bound keeps the modeled mean depth (V/A) constant
  or increasing with surface area, so a fitted `b` below 1 is set to 1
  with `c` recalculated to preserve the recovered full-pool area and
  volume. In contrast, a surface area that grows less than in proportion
  to depth gives `b` above 2, which the released parameters now keep.
  Before, `b` was clipped to [1.1, 2.0]. The summary keeps the
  unconstrained fit, as before. Panel p3 marks the lower bound of the
  released exponent.
- **The river direction is read on the reach part nearest the dam**
  (`eaves.preprocess`, `eaves.pipeline.terrain`). The preprocessing
  records that part as `closest_segment_id`, and the direction is the
  chord extending 500 m along the channel on either side of the point of
  that part nearest the dam, truncated at the part ends. Before, the
  chord was read on the part attached to the snapped node, centered on
  its vertex nearest the dam, and that part can be a neighbor of the
  nearest one. A cached domain without the new column is refused, so a
  rerun needs `--rebuild-domain` once.
- **The snap distance is measured on the ground** (`eaves.preprocess`).
  The distance from a dam to the reach parts is computed in the UTM
  zone of the dam, and the preprocessing records it as
  `snap_distance_m`. Before, it was measured on the Web Mercator plane,
  where the snap radius of 1 km covers 0.85 to 0.96 km on the ground
  across Saudi Arabia.
- **The Saudi Arabian catalog on the revised method.** The flood fill
  covers 501 dams in place of 503, with 320 SRTM-derived and 206
  regionalized curves in place of 319 and 207. The grades read A 300,
  B 86, C 34, D 78 and F 3 in place of 289, 101, 31, 79 and 3. The 296
  capped fills end at their capacity. The training set holds 221 dams in
  place of 216, the regional exponent reads 1.5065 in place of 1.5291
  and its spread 0.26 in place of 0.28. The reference of the
  leave-one-out test, the SRTM-derived power-law curve at fractions of
  the recovered full-pool area, follows the exact cap, so the share
  within a factor of two at full pool reads 88% in place of 93%, with a
  median bias of +18% in place of +7%, and the shares at half and tenth
  pool read 91% and 76% in place of 95% and 72%. The DEM-error Monte
  Carlo sample keeps 35 dams and reads class spreads of +60%, +36% and
  +17% in place of +75%, +55% and +19%.
- **Panel numbering follows the manuscript** (`eaves.postprocess.panels`,
  `eaves.postprocess.report`). The panel modules, their `make_*`
  functions and the PNG and PDF files they write carry the figure numbers
  of the manuscript, and so do the figure IDs of
  `python -m eaves.postprocess.panels --figures`. Figure 4 is the
  leave-one-out validation and Figure 5 the Baish comparison, while the
  supplementary figures S2, S3 and S4 are the volume uncertainty band, the
  DEM-error Monte Carlo and the capacity-threshold sweep. The report
  embeds the main figures in this order and gathers the supplementary
  figures in a section of their own. Five modules change, old name to new
  name, each with its output.
  - `p4.py` (`p4_comparison`) to `p5.py` (`p5_comparison`)
  - `p5.py` (`p5_regionalization_validation`) to `p4.py`
    (`p4_regionalization_validation`)
  - `s2.py` (`s2_threshold_analysis`) to `s4.py` (`s4_threshold_analysis`)
  - `s3.py` (`s3_uncertainty_band`) to `s2.py` (`s2_uncertainty_band`)
  - `s4.py` (`s4_dem_error`) to `s3.py` (`s3_dem_error`)
- **One layout for every panel** (`eaves.postprocess.panels`). Every
  panel is now drawn 187 mm wide with 10 pt text and 12 pt bold panel
  letters, without panel titles and with its keys inside the panels,
  where p2 alone keeps its shared key below the maps. Consequently, all
  figures print at one type size. The keys are drawn without frames, the
  letters of a row sit on one line and the axes end at the data, so
  panel s4 shows every fit. Every canvas holds its text inside it, so no
  label overhangs the canvas and widens the PDF.
- **Packaging and repository.** `pyproject.toml` holds the pytest
  configuration with the `slow` marker in place of `pytest.ini`, the ruff
  rule set, the license expression with its license files, and the extras
  `test`, `dev` (with `ruff>=0.12`) and `mcp` (with `mcp>=1.3`). Its
  dependency list is empty, since the runtime dependencies come from
  `environment.yml`. The continuous integration installs the package without its
  dependencies, adds pytest and `mcp`, and runs the fast tier.
- **One source label for regionalized dams**
  (`eaves.postprocess.regionalization`, `eaves.cli`,
  `eaves.postprocess.uncertainty`). Every regionalized dam carries
  `regi_multi`, also when the regression on `b` passes its leave-one-out
  test. The `regr_derived` label, which the regionalization always
  replaced with `regi_multi` before writing `eaves_params.csv`, is
  removed together with the `regr` suffix of the check plots and the
  test of the uncertainty band that matched it. The outputs do not
  change.
- **One definition of the trusted set**
  (`eaves.postprocess.reliability`, `eaves.postprocess.regionalization`,
  `eaves.postprocess.validation`, `eaves.postprocess.report`,
  `eaves.postprocess.sensitivity`, `eaves.postprocess.dem_error`,
  `eaves.postprocess.panels.p3`). The regionalization, the validation,
  the report, the sensitivity sweep, the DEM-error Monte Carlo and panel
  p3 select the trusted set through `trusted_mask` of
  `eaves.postprocess.reliability` in place of six copies of its gates.
  The selected dams do not change.
- **The DEM-error Monte Carlo draws its sample by the capacity rule
  alone** (`eaves.postprocess.dem_error`). The candidate pool of `--dem-mc`
  is every trusted dam with a fill, and the log-capacity quantile bins
  pick the sample from it. Once every worker has finished, the table is
  rewritten with its rows in dam order, so repeated runs give the same
  file and panel s3 the same strip of points.
- **Panel s4 selects its cut through the regionalization rule**
  (`eaves.postprocess.panels.s4`, `eaves.postprocess.regionalization`).
  The panel calls `choose_reliability_threshold` in place of a copy of
  the rule, and the panel and the regionalization both fall back to
  `FALLBACK_RELIABILITY_THRESHOLD_MCM`, 5 MCM, when no tested threshold
  meets the rule. The tests of the rule move to
  `test/test_regionalization.py`. The panel does not change.
- **One dam-row stand-in** (`eaves.pipeline.curves`,
  `eaves.pipeline.workers`, `eaves.postprocess.sensitivity`,
  `eaves.postprocess.dem_error`, `eaves.postprocess.panels.p2`,
  `eaves.postprocess.panels.p3`). `DamRow`, the dam dict with its
  geometry in the form `process_dam` reads, sits beside `process_dam` in
  `eaves.pipeline.curves`, and the workers, the two opt-in diagnostics
  and panels p2 and p3 import it in place of their own copies.
- **The environment file pins the versions that produced the outputs**
  (`environment.yml`, `pyproject.toml`, `README.md`). The file pins
  Python 3.14, geopandas 1.1.3, shapely 2.1.2 and rasterio 1.5.0, the
  versions of the environment that wrote the Saudi outputs and the golden
  hashes.
- **The report names the example reservoir from the settings**
  (`eaves.postprocess.report`). The narrative takes the
  bathymetry-cross-referenced reservoir from `bathymetry_dam_id` and its
  name and predicted silt fraction from the summary, prints the
  cross-reference paragraph for the checks the settings configure, and
  counts the GRDL curves it compares. The Saudi report changes in its
  narrative only, and every table is unchanged.
- **The test flag of `run_all.sh` runs the regression test and stops at
  a failure** (`run_all.sh`, `documentation/usage.md`). `RUN_TESTS=1`
  runs the slow tier after the report. The hashes change only through
  the one-liner of `test/README.md`.
- **The catalog cleaning script is `clean_catalog.py`**
  (`region/ksa/input/ksa_dams/`, `eaves.preprocess`), the spelling of
  the rest of the repository.
- **Documentation.** The README, the pages under `documentation/`, the
  test README and the data dictionary describe the released code and data,
  and the README links the data dictionary and `AGENTS.md`.
- **The wording follows the manuscript.** The documentation, the prose
  of the report and the docstrings, comments and labels of the code use
  the terms and descriptions of the manuscript. The method page
  describes the flat-water screen and the partial curves, the report
  states what the volume band excludes and lists the resolution and
  single-exponent limits, and the data dependencies name the GRDL
  version and its archive. The outputs change in their wording only.
- **Supplementary panels s2 and s3** (`eaves.postprocess.panels.s2`,
  `eaves.postprocess.panels.s3`, `eaves.postprocess.report`). Panel s2
  separates the exponent contribution from the combined parameterization
  bands, names the marker at the median satellite-to-DEM area ratio an
  illustrative area fraction and calls the star the reference point. Panel
  s3 summarizes the variation among dams within each capacity class with
  10th to 90th percentile intervals. The plotted values are unchanged.

### Removed

- **The metadata table and the eleven raw series of the water-extent
  folder** (`region/ksa/input/ksa_dams/water_extent_ts/`). Nothing read them,
  the table carried a superseded identifier scheme and values that differed
  from the catalog, and the filtered series are the released input.
- **The low-spillway substitute of the flood fill** (`eaves.pipeline.curves`).
  The fill reads the cataloged spillway height, and a zero value is the
  only one replaced, by 0.75 times the dam height. On the Saudi domain
  the Fihan dam (`id_060010`) keeps its regionalized curve, and its row of
  `failed_dams.csv` records that no flood fill was accepted.
- **Placement overrides** (`eaves.utils`, `eaves.config`,
  `eaves.pipeline.curves`, `eaves.pipeline.workers`,
  `eaves.pipeline.placement`). The loader of a per-dam override table
  (`_load_placement_overrides`, `_get_placement_override`), its readers
  `_ov_float`, `_ov_bool`, `_ov_int` and `_ov_preferred_crest_angles_deg`,
  its cache and every branch it fed are removed, together with
  `_snap_cross_channel_barrier_px`, which only those branches called. No
  settings key names the table, so none of these branches ran and the
  outputs do not change.
- **Parameters that no call passes** (`eaves.pipeline.placement`). The
  `max_shift_px` parameter of `search_terrain_wall_extended_upstream` and
  `_upstream_sample_distances_m` and the `walk_step_m` and
  `downstream_walk` parameters of `_iter_upstream_positions_walked` are
  removed. The upstream walk reads `UPSTREAM_MAX_SHIFT_PX` and
  `UPSTREAM_WALK_STEP_M` and walks up the valley.
- **Arguments and values that nothing reads** (`eaves.pipeline.terrain`,
  `eaves.pipeline.curves`, `eaves.pipeline.workers`,
  `eaves.postprocess.validation`, `eaves.postprocess.sensitivity`,
  `eaves.postprocess.dem_error`, `eaves.postprocess.panels.p2`,
  `eaves.postprocess.panels.p4`). The `dem_shape` argument of
  `_flood_river_overlay_from_segment` and the `domain_dir` argument of
  `sensitivity_sweep` are removed, together with the spillway and wall
  elevations that `process_dam` set before the placement and set again
  before any read, the `reliable` column of the leave-one-out frame, the
  labels of the coordinate pairs that the worker and panel p2 try, the
  `c`, `r_squared` and `srtm_max_vol_mcm` fields of the single runs of
  the DEM-error and sensitivity steps, and five accuracy statistics that
  panel p4 computes and never draws.

### Fixed

- **A dam has at most one check plot** (`eaves.cli`). The rename of the
  flood plot by source now removes the plot left under the previous
  suffix, and a dam whose fill fails loses the plot of an earlier run as
  well, so `0_check_dams/` holds one plot per dam with a fill and none
  for the others.
- **Report** (`eaves.postprocess.report`). The volume error of a
  one-sigma mismatch in `b` at half and tenth pool is computed from the
  spread of `b`, every citation carries a link, and the file table lists
  the JSON twin of the domain characterization and the check maps. The
  strongest rank correlation of `b` with a single morphometric feature
  is computed on the regression basis, the training dams at or above the
  minimum training capacity with every feature present, and the
  clustering paragraph quotes the same statistic on the clustering
  basis, every training dam with the six clustering features. The
  section on the exponent describes the constant-width wedge with `b` at
  2 and the V-shaped valley with `b` at 1.5, and states that the assumed
  area-depth relation permits any `b` above 1. The report numbers its
  figures in the order in which they appear and writes the panel b
  sentence of the Figure S1 caption from
  `validation/b_clustering_diagnostic.csv`. The paragraph on the
  regression branch says that regionalized dams keep the `regi_multi`
  source label.
- **Panels** (`eaves.postprocess.panels`). Panel p5 labels its shaded
  bands by their volume-ratio ranges, [0.5, 2.0] and [0.3, 5.0], the
  windows of grades A and B, and counts the fills inside each range.
  Panel p4 annotates the median and the P16 to P84 range in log10 of the
  volume ratio, the units of its axis. Panel s2 places the typical-fill
  marker on the SRTM-derived curve, which carries the catalog-capacity
  term. Panel p3 prints the capacity to two decimals and `c` and `b` at
  the precision of `eaves_params.csv`, four significant digits and four
  decimals, in panel b and for the Baish entry of panel c, labels R² of
  panel b as computed on untransformed volumes, and adds the
  root-mean-square fractional residual of the example dam from
  `validation/goodness_of_fit.csv`. Panel p3 also leaves headroom above
  the curve of panel b for its annotation and labels the median of panel
  c as the trusted-set median with its count. Panel p5 labels the ratio
  axis V_SRTM/V_cap and extends that axis below the smallest ratio. Its
  panel c centers one bin on a ratio of 1, where the capped fills lie,
  and draws its reference lines under the bars. Panel s2 labels its
  tiers as the upper bound of the band and prints the Baish exponent to
  four decimals. Panel p1 names the failed dams of its legend as
  placement, fill or fit failures and words the boxes of its flowchart
  as the method description does, with MERIT-Basins as the river
  network. Panel p2 names the snapped river node in its legend. Panel p3
  labels the axes of its map in grid cells. Panel p5 draws the bars of
  its histogram without edges, so a bin that holds one dam shows. Panel
  p4 labels the reference volume as SRTM-derived. Panel s5 shades 0.03
  on either side of the baseline median, the band that the median
  exponent of the Saudi sweep does not leave. The key entries of panels
  p2, s1 and s2 start in sentence case.
- **The void guard of the flood fill sees enclosed gaps**
  (`eaves.pipeline.curves`). The fill never enters a missing cell, so a gap
  inside a basin left a hole in the footprint that the count over the
  footprint could not see. A gap that terrain encloses now takes the
  highest elevation of its rim before the placement, so it floods only at
  a level that floods every cell around it, enters the fill at that level,
  and counts against the threshold. The missing margin of the projected
  window stays missing. No input of the Saudi domain has a gap, so no
  output changes. Tests in `test/test_void_guard.py`.

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
  that catalog type alone. Six dams with a confirmed wall (Al-Is, Nasifat
  Aban Al-Ahmar, Fihan, Sharaqib, Tahallul, Zalawam) join the catalog,
  which holds 526 dams. The SRTM footprint and the curve of a dam are
  read at its coordinate, so every output is regenerated at the
  corrected coordinates and for the corrected dam set.
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
  catalog capacity. `placement_upstream_shift_m` is positive upstream and
  negative downstream. On the Saudi Arabian catalog the fill of 7 dams
  changes, 5 of them toward the catalog capacity, and 5 dams stay at
  stage 4.
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
  ([Lin et al. 2019](https://doi.org/10.1029/2019WR025287)), which is
  built on MERIT Hydro
  ([Yamazaki et al. 2019](https://doi.org/10.1029/2019WR024873)).
- **Documentation follows one style** across the Markdown documents, the
  generated report, the code comments and the docstrings.
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
- **DEM error panel** (`eaves.postprocess.panels.s4`). The panel leaves
  out every dam with fewer than 10 valid realizations.
- **Arrows of the check plots** (`eaves.pipeline.terrain`). The arrows on
  the snapped river reach pointed upstream. They point downstream.
- **Numbers of the report text** (`eaves.postprocess.report`). The report
  reads the exponent assigned to the regionalized dams, the floors of the
  uncertainty band and the spreads of the alternative anchors from the
  tables of the run.
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
  usage) and direct links to the released curves.

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
  The header of the design table states a design storage capacity of
  193,644,000 m³ with the spillage top level at 327 m a.s.l., and its
  198.072 MCM row, annotated "Spillway + 0.50" (327.5 m a.s.l.), is a
  half-meter surcharge above the crest rather than storage capacity. The
  catalog, the snapped-dams cache, and the Baish comparison table
  (327.5 m row removed) are corrected, and
  the fill cap returns to the spillway level (recovered maximum 197.2 MCM,
  a one-bin +1.8% overshoot, refit c = 0.0077 and b = 1.506, total catalog
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

- `report.md` computes the log-log anchor residual factor as `10**rms` on
  log10 residuals.
- `acap_regression_diagnostics` now evaluates on the training population.
- `domain_characterization.csv` log-log anchor stats (`loglog_alpha`,
  `loglog_resid_rms`) are now in log10 units, matching the stated error
  convention.
- `failed_dams.csv` gains a `construction_year` column so the pre-2000
  status of footprint-less dams is recoverable.

## [1.1.0] - 2026-06-10

### Fixed

- **Clamped exponents now re-solve c through the SRTM full-pool anchor.**
  The released b is clamped to [1.1, 2.0], and c is re-solved so that
  V(A_DEM) = V_SRTM exactly for every clamped dam
  (`regionalization.py`, with `eaves_params.csv` updated for the 39 clamped
  SRTM-derived dams, all other rows bit-identical).
- **Sediment budget no longer double-counts delivery.** The
  `sed_yield_t_ha_yr` input is _delivered_ yield.
  [Dash et al. (2025)](https://doi.org/10.1016/j.jenvman.2025.127199)
  already multiply RUSLE gross erosion by an area-dependent delivery
  ratio at the source (their Eqs. 2 to 4), so the additional
  [Vanoni (1975)](https://doi.org/10.1061/9780784408230) SDR was removed
  from the budget. `predicted_silt_fraction` and `sediment_risk`
  recomputed (median predicted loss 13.7% → 47.5%, fully-silted count
  44 → 149). Verified at Baish (budget now within ~1.6× of the 2025 sonar
  loss) and nationally (implied 32% capacity loss matches the figure that
  [Dash et al. (2025)](https://doi.org/10.1016/j.jenvman.2025.127199)
  publish with the same yields). `--sediment-sdr`
  remains available as a constant factor for gross-erosion inputs.
- **Panel S3 SRTM band formula.** The SRTM-derived uncertainty tier now
  includes the catalog-capacity term (σ(log V_cap)),
  matching `validation/v_uncertainty.csv`. It was previously drawn from
  b_σ alone and appeared to vanish at the anchor.

### Changed

- **Report and data-dictionary text.** The catalog-capacity cap on the flood
  fill is disclosed explicitly, the SRTM uncertainty tier is described as
  floored by the catalog-capacity term rather than vanishing at the anchor,
  and the software-versions table was dropped from `report.md`.

## [1.0.1] - 2026-06-01

### Changed

- **Dams without a catalog year carry an empty construction year**,
  `construction_year = <NA>` (nullable `Int32`, blank in
  `eaves_summary.csv`). The flat-water detector now runs for unknown-year
  dams as well as pre-2000 dams, so the SRTM surface itself decides full
  vs partial.
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
  guard that a missing year stays missing.
- **`test_uncertainty.py`**: unit coverage for the uncertainty module
  (`compute_b_sigma`, anchor back-solve, V-band algebra) backing panel S3.
- Extracted `curves._parse_construction_year()` as a directly testable helper
  (pipeline output verified unchanged).

## [1.0.0] - 2026-05-18

First tagged release, with EAV curve assignment for
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
- **Supplementary panel S3**: V uncertainty propagation, a Baish worked
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
  `upstream_area_km2` from the catalog and sedimentation yield CSV,
  so the regionalization recipe can reach them. This pulled 20 of 21
  dams out of the log-log fallback into the multi-feature LR branch.
- **Saturated SRTM fits** (b pinned at the 1.10 / 2.00 clip
  boundaries) now correctly demoted to the regional median by the
  tightened quality gates.

### Notes

- One dam (`id_120014`, Shahdan) remains on the log-log fallback
  branch due to `valley_ratio = NaN` from failed topography extraction
  in a narrow steep wadi.
- Bathymetric ground truth in this region is limited to Baish
  (`id_120000`). Broader campaigns would be needed to tighten the
  sediment-loss budget beyond the first-order estimate currently
  reported.

[Unreleased]: https://github.com/hyex-research/EAVES/compare/v1.4.0...HEAD
[1.4.0]: https://github.com/hyex-research/EAVES/releases/tag/v1.4.0
[1.3.2]: https://github.com/hyex-research/EAVES/releases/tag/v1.3.2
[1.3.1]: https://github.com/hyex-research/EAVES/releases/tag/v1.3.1
[1.3.0]: https://github.com/hyex-research/EAVES/releases/tag/v1.3.0
[1.2.1]: https://github.com/hyex-research/EAVES/releases/tag/v1.2.1
[1.2.0]: https://github.com/hyex-research/EAVES/releases/tag/v1.2.0
[1.1.0]: https://github.com/hyex-research/EAVES/releases/tag/v1.1.0
[1.0.1]: https://github.com/hyex-research/EAVES/releases/tag/v1.0.1
[1.0.0]: https://github.com/hyex-research/EAVES/releases/tag/v1.0.0
