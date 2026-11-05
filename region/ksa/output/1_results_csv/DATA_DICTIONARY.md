# EAVES KSA release: data dictionary

Schema for every CSV under `region/ksa/output/1_results_csv/` and for the
Baish bathymetry table under `region/ksa/input/ksa_dams/baish_bathymetry/`.
Each dam is keyed by `dam_id` (string, e.g. `id_010000`), which is consistent
across all files.

## Conventions

- **Units.** `eav_tables/*.csv` store volume in cubic meters (`volume_m3`) and
  area in square meters (`area_m2`). `eaves_params.csv`, `eaves_summary.csv`,
  and the `validation/` summaries store volume in million cubic meters (MCM,
  `*_mcm`). The conversion is 1 MCM = 10⁶ m³. Watch this 10⁶ factor when
  joining `eav_tables` against the MCM tables. The power-law coefficient `c`
  is fit in SI units, so V = c · A<sup>b</sup> takes area in m² and returns
  volume in m³ (for Baish, `c` = 0.00768 and `b` = 1.5061 turn A = 8.037 × 10⁶ m² into
  V = 1.928 × 10⁸ m³, or 192.8 MCM). Divide by 10⁶ to obtain MCM.
- **Precision.** A floating-point value is rounded to four significant
  digits and never fewer than two decimals and written in its shortest form,
  so values of 100 and above carry at most two decimals (an elevation rounded
  to 666.50 reads `666.5`, an area of `861.55` m²) and smaller values at most
  four significant digits (a channel slope of `0.0001338`).
  `capacity_mcm`, the exponent `b` and the columns named after it (`b_srtm`,
  `b_reg`, `released_b`, `ref_b`, `pc1_spearman_b`, the `b_*` statistics) keep four decimals.
  The coordinates (`lat`, `lon`,
  `latitude`, `longitude`) and the dam dimensions (`dam_height_m`,
  `spillway_height_m`, `dam_length_m`) are written as they come from the
  catalog, apart from the substituted spillway height of the 28 dams cataloged
  with a zero value. Integer, text and boolean columns carry no rounding.
- **Missing values.** Numeric blanks are empty cells (`NaN` on read).
  `construction_year` is a nullable integer.
  Absent years are left blank, never imputed. `uncertainty_flags` uses the literal string `-`
  to mean "no flags".
- **dtype** notation: `str`, `int`, `Int (nullable)`, `float`, `bool`.
- **Source provenance.** Each dam is either `srtm_derived` (curve fitted to
  flooded SRTM topography) or `regi_multi` (regionalized: `b` set to the
  regional median over the training dams at or above the minimum training
  capacity, selected by the capacity-threshold analysis of
  `threshold_analysis.csv` (84 dams of at least 1 MCM with complete
  morphometric features, median 1.5065), `c` back-solved from catalog capacity
  via the multi-feature anchor). See `source` below.
- **Error reporting.** Volume errors are multiplicative. They are computed in
  base-10 log-ratio space and stored as `*_log10` columns (and as signed decimal
  fractions, e.g. `0.29 = +29%`). Prose and tables report them mostly as
  relative values, a percentage below 100% and a multiplicative factor at or
  above 100% (% = 10<sup>σ</sup> − 1, factor = 10<sup>σ</sup>), and some
  figures and tables also give the log10 value itself.

## Catalog-derived fields in the release

The following columns of the released tables are passed through from the
Saudi dam catalog, whose cleaned and transliterated form ships with the code
under `region/ksa/input/ksa_dams/`. The released tables carry exactly these
catalog-derived fields, at the precision listed.

| Field | Files | Content and precision as released |
| --- | --- | --- |
| `lat`, `lon` (`latitude`, `longitude` in `failed_dams.csv`) | `eaves_summary.csv`, `failed_dams.csv` | Coordinates, catalog value passed through verbatim (decimal degrees, WGS84). Most rows carry 6 decimal places (~0.1 m). A minority carry 1 to 8. No fixed rounding is applied. |
| `capacity_mcm` | `eaves_params.csv`, `eaves_summary.csv`, `failed_dams.csv`, `validation/*` | Design capacity, MCM, rounded to 4 decimals. |
| `dam_height_m` | `eaves_summary.csv`, `failed_dams.csv` | Dam height, meters, full catalog precision (up to 2 decimals). |
| `spillway_height_m` | `eaves_summary.csv`, `failed_dams.csv` | Spillway height, meters, full catalog precision (up to 2 decimals). For the 28 dams cataloged with a zero spillway height, none of which is in `failed_dams.csv`, `eaves_summary.csv` carries 0.75 times the dam height (up to 3 decimals), the median ratio across the other 498 dams. |
| `dam_length_m` | `eaves_summary.csv`, `failed_dams.csv` | Dam length, meters, full catalog precision (up to 2 decimals). |
| `construction_year` | `eaves_summary.csv`, `failed_dams.csv` | Construction year, written as an integer (parse as nullable Int64). For 20 dams the year is the one in which satellite imagery shows the finished dam. Blank, not imputed, when the catalog has no year, which holds for one dam of `eaves_summary.csv` (`id_030038`, whose construction date relative to the SRTM acquisition is unknown) and none of `failed_dams.csv`. |

For Baish (`id_120000`), the capacity comes from the design documentation of the dam, 193.644 MCM at the spillway crest at 327.0 m a.s.l. (`baish_bathymetry/baish_area_elev_vol.csv`).

---

## `eaves_params.csv`: lean per-dam EAV coefficients (526 rows)

| Column | Definition | Unit | dtype | Missing |
| --- | --- | --- | --- | --- |
| `dam_id` | Persistent dam identifier | - | str | never |
| `dam_name` | Latin-transliterated dam name | - | str | may be empty |
| `capacity_mcm` | Catalog design capacity, rounded to 4 decimals | MCM | float | never |
| `c` | Power-law coefficient in V = c · A<sup>b</sup> (A in m², V in m³), rounded to 4 significant digits | - | float | never |
| `b` | Power-law exponent in V = c · A<sup>b</sup>, with a lower bound of 1 on the released value (the unconstrained least-squares fit is in `eaves_summary.csv`), rounded to 4 decimals | - | float | never |
| `c` (bounded dams) | For the dams whose fitted `b` falls below the bound, `b` is set to 1 and `c` is recalculated to preserve the recovered full-pool area and volume (`srtm_max_vol_mcm` at `footprint_area_km2`), so these adjusted coefficients differ from the unconstrained `c` in `eaves_summary.csv` | - | float | never |
| `source` | Provenance | - | str | never |

`source` controlled vocabulary: `srtm_derived` (320), `regi_multi` (206).

---

## `eaves_summary.csv`: full per-dam diagnostics (526 rows)

One row per dam of `eaves_params.csv`. Of the 526 dams, 501 have a flood fill
and 25 have none. A dam without a flood fill keeps its catalog attributes,
coordinates, topographic features and external attributes, and the cells of
its fill and of its fit are empty. `n_pixels` is empty for these 25 rows only,
so a filled `n_pixels` selects the 501 dams with a fill. The 28 dams with
unsuccessful SRTM processing are listed in `failed_dams.csv`: the 25 dams
without a fill and 3 dams with a fill whose power-law fit failed.

| Column | Definition | Unit | dtype | Missing |
| --- | --- | --- | --- | --- |
| `dam_id` | Persistent dam identifier | - | str | never |
| `dam_name` | Latin-transliterated dam name | - | str | may be empty |
| `construction_year` | Catalog construction year | year | Int (nullable) | blank for 1 dam |
| `dam_height_m` | Catalog dam height | m | float | catalog-derived |
| `spillway_height_m` | Catalog spillway height (fill depth used), 0.75 times the dam height for the 28 dams cataloged with a zero value | m | float | catalog-derived |
| `dam_length_m` | Catalog dam length | m | float | catalog-derived |
| `capacity_mcm` | Catalog design capacity, rounded to 4 decimals | MCM | float | never |
| `curve_type` | Whether SRTM saw a bare valley or standing water | - | str | blank without a fill |
| `srtm_water_level_m` | Detected flat-water surface elevation (partial curves only) | m | float | blank unless `curve_type=partial` |
| `coverage_fraction` | Share of the represented elevation range above the detected water surface, (z_max − srtm_water_level_m) / (z_max − z_min) clipped to [0, 1], 1.0 for full curves | - | float | blank without a fill |
| `z_min` | Minimum SRTM elevation in the flooded footprint | m | float | blank without a fill |
| `z_max` | Elevation of the last level of the fill, the spillway elevation or, for capped fills, the elevation where the volume reaches the catalog capacity | m | float | blank without a fill |
| `footprint_area_km2` | Flooded footprint area at the last level of the fill, the spillway elevation or, for a capped fill, the capped level, where the area is interpolated between the bounding levels | km² | float | blank without a fill |
| `c` | Power-law coefficient in V = c · A<sup>b</sup>, rounded to 4 significant digits | - | float | blank for the 3 grade-F fits and without a fill |
| `b` | Power-law exponent, rounded to 4 decimals | - | float | blank for the 3 grade-F fits and without a fill |
| `r_squared` | R² of the power-law fit on untransformed areas and volumes | - | float | blank for the 3 grade-F fits and without a fill |
| `n_pixels` | Active (flooded) SRTM grid cells in the footprint | count | Int (nullable) | blank without a fill |
| `void_fraction` | Share of the footprint cells that are DEM gaps enclosed by terrain, each given the highest elevation of its rim before the placement | - | float | blank without a fill |
| `capped` | Integrated volume reached the catalog capacity below the spillway, so the fill ends at the elevation where it equals the capacity (the catalog values are spillway/gross capacities, and the cap bounds the SRTM fill) | - | bool | blank without a fill |
| `placement_upstream_shift_m` | Distance the dam wall was shifted upstream during placement, negative when stage 4 moves it downstream | m | float | blank for the 3 `stage_6_fallback` dams and without a fill |
| `placement_method` | Which placement stage produced the wall | - | str | blank without a fill |
| `valley_width_m` | Estimated valley width at the wall | m | float | may be NaN |
| `valley_ratio` | Valley-width ratio, the valley width over the spillway height | - | float | may be NaN |
| `channel_slope` | Local channel slope at the wall | m/m | float | may be NaN |
| `mean_catchment_slope` | Mean slope of the upstream catchment | m/m | float | may be NaN |
| `upstream_area_km2` | Upstream catchment area, from the catchment table of [Dash et al. (2025)](https://doi.org/10.1016/j.jenvman.2025.127199) | km² | float | may be NaN |
| `lat` | Catalog latitude (WGS84) | deg | float | catalog-derived |
| `lon` | Catalog longitude (WGS84) | deg | float | catalog-derived |
| `srtm_max_vol_mcm` | Volume of the SRTM-derived curve at its last level, the spillway elevation or the catalog capacity for a capped fill | MCM | float | blank without a fill |
| `vol_ratio` | `srtm_max_vol_mcm / capacity_mcm`, which is 1 for capped fills, since the fill ends where the volume equals the capacity | - | float | blank without a fill |
| `z_range` | `z_max − z_min` | m | float | blank without a fill |
| `z_range_ratio` | `z_range / spillway_height_m` | - | float | blank without a fill |
| `quality` | Per-dam quality grade | - | str | blank without a fill |
| `uncertainty_flags` | `;`-joined active uncertainty flags, or `-` if none | - | str | `-` when none, blank without a fill |
| `uncertainty_score` | Number of active uncertainty flags (0 to 7 by construction, 0 to 3 realized on this domain) | count | Int (nullable) | blank without a fill |
| `sed_yield_t_ha_yr` | Delivered sediment yield at the reservoir inlet ([Dash et al. (2025)](https://doi.org/10.1016/j.jenvman.2025.127199), RUSLE gross erosion × area-dependent delivery ratio, applied at the source) | t ha⁻¹ yr⁻¹ | float | may be blank |
| `owe_mm_year` | Open-water evaporation (external input) | mm yr⁻¹ | float | blank for 70 dams |
| `predicted_silt_fraction` | First-order predicted fraction of design capacity lost to sediment by the reference year 2026 (capped at 1.0, computed from the delivered yield with no additional delivery ratio) | fraction | float | blank when the construction year or the catchment-yield inputs are missing (1 dam, the undated `id_030038`) |
| `sediment_risk` | Categorical sediment-loss risk derived from `predicted_silt_fraction` | - | str | `unknown` in the same case |

Controlled vocabularies:

- `curve_type`: `full` (bare-valley capture), `partial` (standing water in the
  February 2000 SRTM footprint, fit restricted to elevations above
  `srtm_water_level_m`).
- `quality`: `A`, `B`, `C`, `D`, `F` (decreasing reliability). The trusted set
  (`is_trusted` in `validation/goodness_of_fit.csv`) takes grades `A` and `B`
  with R² ≥ 0.98 and at least 50 active grid cells (`n_pixels`), so it is
  stricter than the two grades alone. `F` marks a failed power-law fit (`b`
  undefined).
- `placement_method`: `stage_1_fast_path`, `stage_2_upstream_walk`,
  `stage_3_quality_recovery`, `stage_4_river_retry`,
  `stage_5_relaxed_alignment`, `stage_6_fallback` (the six stages of the
  automated dam-wall placement procedure, tried in sequence, with the synthetic
  wall of `stage_6_fallback` as the final fallback).
- `uncertainty_flags` atomic tokens (combine with `;`):
  - `sub_pixel`: footprint contains fewer than 30 active grid cells (geometry undersampled).
  - `narrow_valley`: valley width is less than three grid-cell widths (cross-section undersampled).
  - `height_noise`: spillway height is below 5 m (comparable to the SRTM vertical error).
  - `pre_srtm`: recorded construction year before 2000, ahead of the February 2000 SRTM acquisition. An SRTM-derived curve of such a dam describes the valley as it stood in 2000, which may already hold sediment deposited since construction, whereas a regionalized curve is anchored to the design capacity. These dams do not enter regionalization training.
  - `unknown_year`: no catalog construction year, so the pre- or post-acquisition status cannot be verified. These dams do not enter regionalization training either.
  - `flat_terrain`, `tall_narrow`: defined by construction but not raised for any Saudi reservoir (so absent from the released tables here).
  - `-`: no flags active.
- `capped`: `True` / `False`.
- `sediment_risk`: `low`, `moderate`, `high`, `severe`, `fully_silted`, `unknown` (increasing predicted capacity loss, `unknown` when the construction year or the catchment-yield inputs are missing). Counts on the Saudi domain: 80 / 102 / 102 / 89 / 152 / 1. The one `unknown` dam is the dam without a construction year.

---

## `eav_tables/<dam_id>_eav.csv`: elevation, depth, area and volume tables (501 files)

One file per dam with a flood fill. Cumulative area and volume as a
function of elevation, at levels 0.5 m apart from `z_min` with the spillway elevation or the capped level as the last row, with
the depth above the bottom of the fill beside the elevation.

| Column | Definition | Unit | dtype | Missing |
| --- | --- | --- | --- | --- |
| `elevation_m` | Water-surface elevation | m a.s.l. | float | never |
| `depth_m` | Water depth above the bottom of the fill, `elevation_m` minus the elevation of the first row | m | float | never |
| `area_m2` | Flooded surface area at this elevation | **m²** | float | never |
| `volume_m3` | Cumulative impounded volume below this elevation | **m³** | float | never |

The units are m² and m³ here, not MCM. `depth_m` and `volume_m3` are 0 at the bottom row.

---

## `failed_dams.csv`: dams with unsuccessful SRTM processing (28 rows)

| Column | Definition | Unit | dtype | Missing |
| --- | --- | --- | --- | --- |
| `dam_id` | Persistent dam identifier | - | str | never |
| `dam_name` | Latin-transliterated dam name | - | str | may be empty |
| `reason` | Failure category | - | str | never |
| `detail` | Free-text failure description | - | str | never |
| `capacity_mcm` | Catalog design capacity, rounded to 4 decimals | MCM | float | catalog-derived |
| `dam_height_m` | Catalog dam height | m | float | catalog-derived |
| `spillway_height_m` | Catalog spillway height | m | float | catalog-derived |
| `dam_length_m` | Catalog dam length | m | float | catalog-derived |
| `upstream_area_km2` | Upstream catchment area | km² | float | may be NaN |
| `construction_year` | Catalog construction year | year | Int (nullable) | blank when unknown |
| `latitude` | Catalog dam latitude (WGS84) | deg | float | never |
| `longitude` | Catalog dam longitude (WGS84) | deg | float | never |
| `valley_width_m` | Estimated valley width | m | float | may be NaN |
| `valley_ratio` | Valley-width ratio | - | float | may be NaN |
| `channel_slope` | Local channel slope | m/m | float | may be NaN |
| `mean_catchment_slope` | Mean catchment slope | m/m | float | may be NaN |

`reason` controlled vocabulary: `placement_failed` (15), `bad_fill_auto` (10),
`fit_failed` (3). These dams carry catalog and topographic attributes. Every
dam of this file also has a row in `eaves_summary.csv`, and the regionalization
reads its features from that row.

---

## `threshold_analysis.csv`: capacity-threshold analysis behind the training cut of the regional exponent (39 rows)

| Column | Definition | Unit | dtype |
| --- | --- | --- | --- |
| `threshold_mcm` | Capacity cut-off | MCM | float |
| `n_above` | Dams with capacity at or above the threshold, over the 501 dams with a flood fill (not the 526-dam catalog) | count | int |
| `n_reliable` | Of those, dams passing the trusted-set criteria | count | int |
| `frac_reliable` | `n_reliable / n_above` | - | float |

---

## `domain_characterization.csv`: domain-level summary statistics (long form)

A two-column `statistic,value` table of population summaries (dam counts by
source/era, capacity percentiles, the regional `b` distribution, LOO anchor
skill, sediment-budget summaries, and the `b`-clustering diagnostic). Values
are strings/numbers. The key names are self-describing. Volume statistics are
in MCM (`*_mcm`). Dimensionless skill metrics are in log10 units. The capacity,
construction-year, dam-height and sediment statistics cover all 526 dams, and
the statistics of the fill and of the fit cover the 501 dams with a flood fill.
`domain_characterization.json` beside the table holds the same statistics in
the same order, each value typed as a number or a string, an empty value as
null.

Selected keys: `n_dams_with_params=526`, `n_dams_summary=501` (the dams with
a flood fill), `n_dams_failed_pipeline=28`, `n_params_source_srtm_derived=320`,
`n_params_source_regi_multi=206`, `n_training=221`, `b_median=1.4772` (trusted,
descriptive), `b_sigma_training=0.256` (the band's b-spread, training set),
`b_cluster_best_gain_pct=13.75` (at `b_cluster_best_k=3`, with
`b_cluster_best_loo_r2=0.0853`), `b_cluster_silhouette_max_k=2`,
`loo_multi_anchor_within_2x_frac=0.8778` / `_within_3x_frac=0.9955`
(stored as decimal fractions). The LOO rows cover the 221 training dams.
The two feature bases of the exponent diagnostics are recorded with the
strongest rank correlation of `b` with a single feature on each:
`reliability_threshold_mcm`, `n_regression_basis`, `b_feature_rho_max` and
`b_feature_rho_max_feature` for the regression basis, and `n_cluster_basis`,
`b_feature_rho_max_cluster` and `b_feature_rho_max_cluster_feature` for the
clustering basis. `b_cluster_pc1_var_share=0.5997`,
`b_cluster_pc2_var_share=0.1613` and `b_cluster_pc1_spearman_b=-0.4071`
repeat the `pc1_var_share`, `pc2_var_share` and `pc1_spearman_b` columns of
`validation/b_clustering_diagnostic.csv`, the variance shares of the first
two principal components of the clustering features and the Spearman
correlation of `b` with the first.

---

## `validation/b_clustering_diagnostic.csv`

K-means clustering diagnostic on `b` (supplementary panel S1). The features
are the logarithms of `valley_ratio`, `channel_slope`, `mean_catchment_slope`,
`dam_height_m`, `spillway_height_m` and `dam_length_m`, each standardized over
the training dams, and the principal components are those of the same
standardized features.

| Column | Definition | Unit | dtype |
| --- | --- | --- | --- |
| `feature_set` | Feature set fed to clustering | - | str |
| `k` | Number of clusters | count | int |
| `silhouette` | Silhouette score | - | float |
| `loo_sigma_delta_b` | LOO σ of Δb with clustering | - | float |
| `loo_sigma_baseline` | LOO σ of Δb with the global-median baseline | - | float |
| `loo_relative_gain_pct` | Relative reduction in σ from clustering | % | float |
| `loo_r2` | LOO R² of the per-cluster median of `b` at `k`, 1 minus the mean squared LOO error over the variance of `b` | - | float |
| `n_trusted` | Training dams used (the trusted dams built in or after 2000) | count | int |
| `pc1_var_share` | Variance share of the first principal component of the features, the same on every row | fraction | float |
| `pc2_var_share` | Variance share of the second principal component of the features, the same on every row | fraction | float |
| `pc1_spearman_b` | Spearman correlation of `b` with the first principal component, the same on every row | - | float |

---

## `validation/dem_vs_sat_area.csv`: SRTM-derived full-pool area vs satellite-observed water area

| Column | Definition | Unit | dtype | Missing |
| --- | --- | --- | --- | --- |
| `dam_id` | Persistent dam identifier | - | str | never |
| `dam_name` | Latin-transliterated dam name | - | str | may be empty |
| `capacity_mcm` | Catalog design capacity | MCM | float | catalog-derived |
| `A_DEM_km2` | SRTM-derived full-pool area | km² | float | never |
| `A_sat_P95_km2` | 95th-percentile satellite-observed water area | km² | float | blank with 5 or fewer observations |
| `n_sat_obs` | Number of satellite observations | count | int | never |
| `quality` | Per-dam quality grade (see summary) | - | str | never |
| `sat_over_dem` | `A_sat_P95_km2 / A_DEM_km2` | - | float | blank when `flag=no_sat` |
| `log10_ratio` | log10 of `sat_over_dem` | log10 units | float | blank when `flag=no_sat` |
| `flag` | Comparison flag | - | str | empty when no flag applies |

`flag` controlled vocabulary: `sat_much_smaller` (188), `sat_much_larger` (0),
`no_sat` (38), empty (94).
`no_sat` means zero or no observed water area. Of the 38, 31 have satellite
observations but a zero 95th-percentile extent (`A_sat_P95_km2 = 0.0`), and the
other 7 have no usable record (blank columns).

---

## `validation/regionalization_loo.csv`: leave-one-out reconstruction skill

Per-dam leave-one-out comparison of three anchors (satellite 95th-percentile
extent, capacity-only regression and the selected multi-feature regression)
against the SRTM-derived reference at full, half and tenth pool (100%, 50% and
10% of the recovered full-pool area). Columns follow the pattern
`<anchor>_<quantity>` where `<anchor> ∈ {current, alt, multi}`.

| Column group | Definition | Unit |
| --- | --- | --- |
| `dam_id`, `capacity_mcm`, `A_DEM_km2`, `A_sat_P95_km2`, `n_sat_obs` | dam keys and inputs (catalog/SRTM/satellite) | mixed (MCM, km², count) |
| `c_srtm`, `b_srtm` | SRTM-derived reference coefficients | - |
| `b_reg`, `delta_b` | regional-median b and its deviation from `b_srtm` | - |
| `current_source` / `alt_source` / `multi_source` | which anchor variant produced the row | - |
| `*_A_cap_km2` | full-pool area A_cap of the anchor, at which the catalog capacity is placed | km² |
| `*_c`, `*_log10_c_ratio` | anchor coefficient and its log10 ratio vs reference | - / log10 units |
| `*_V_at_{100,050,010}pct_m3` | anchor volume at that pool fraction | **m³** |
| `*_log10_V_ratio_at_{100,050,010}pct` | log10 volume ratio vs the SRTM reference | log10 units |
| `V_srtm_at_{100,050,010}pct_m3` | SRTM-reference volume at that pool fraction | **m³** |

Source vocabularies: `current_source ∈ {current_sat_p95 (195),
current_sat_fallback (26)}` (over the 221 training-dam rows), `alt_source = alt_loglog_primary`,
`multi_source = multi_lr_primary`. Volumes in this file are in m³.

---

## `validation/v_uncertainty.csv`: per-dam volume uncertainty band

Combined per-dam volume uncertainty band at half, quarter and tenth pool (supplementary panel S2), from the exponent spread `b_sigma`, the catalog-capacity term and, for regionalized curves, the term of the predicted full-pool area.

| Column | Definition | Unit | dtype | Missing |
| --- | --- | --- | --- | --- |
| `dam_id` | Persistent dam identifier | - | str | never |
| `source` | `srtm_derived` or `regi_multi` | - | str | never |
| `capacity_mcm` | Catalog design capacity | MCM | float | catalog-derived |
| `b` | Power-law exponent | - | float | never |
| `b_sigma` | Regional `b` spread used for the band (P16 to P84 half-width over the training set) | - | float | never |
| `A_cap_km2` | Reference area at which the curve reaches the catalog capacity (V_cap = c · A_cap<sup>b</sup>), the predicted full-pool area for regionalized curves | km² | float | never |
| `sigma_log_acap` | LOO error of the predicted `log10 A_cap` (regionalized anchor term, 0 for `srtm_derived`) | log10 units | float | never |
| `sigma_log_vcap` | Catalog-capacity error term (P16 to P84 half-width of log10(V_SRTM/V_cap) over the uncapped training fills, conservative since the subset also carries genuine sub-grid-cell shortfall) | log10 units | float | never |
| `sigma_acap_term` | `b · sigma_log_acap`, the area-anchor term as it enters the volume band | log10 units | float | never |
| `V_sigma_bspread_{half,quarter,tenth}_pool` | Geometric `b_sigma`-only component of the band | log10 units | float | never |
| `V_pred_{half,quarter,tenth}_pool_mcm` | Predicted volume at that pool fraction | MCM | float | never |
| `V_sigma_log10_{half,quarter,tenth}_pool` | 1σ band half-width in log10 | log10 units | float | never |
| `V_frac_up_{...}_pool` / `V_frac_down_{...}_pool` | +1σ / −1σ as decimal fractions (0.29 = +29%, 1.32 = +132%), reported above 100% as the multiplicative factor 1 + value (1.32 gives a factor of 2.3) | fraction | float | never |

`source` vocabulary: `srtm_derived` (320), `regi_multi` (206).

---

## `validation/goodness_of_fit.csv`: fractional volume residuals (501 rows)

Absolute fractional volume residual of the released power-law curve, |c · A<sup>b</sup> − V| / V, at each fitted level, reported alongside `r_squared`. The table also gives the medians of that residual by fill level, its departure at the typical satellite extent and the residual of a two-segment fit, the statistics behind the internal-consistency figures of the report. The fit and its R² emphasize the upper levels, where most storage lies, whereas each level counts equally in the residual, which makes it sensitive to large relative differences at low volumes.

| Column | Definition | Unit | dtype | Missing |
| --- | --- | --- | --- | --- |
| `dam_id` | Persistent dam identifier | - | str | never |
| `source` | `srtm_derived` or `regi_multi` | - | str | never |
| `quality` | Letter grade A to F | - | str | never |
| `r_squared` | Power-law fit R² on untransformed areas and volumes, as in `eaves_summary.csv` | - | float | blank for the 3 grade-F fits |
| `is_trusted` | In the trusted set | - | bool | never |
| `in_training` | In the regionalization training set (trusted and built in or after 2000) | - | bool | never |
| `n_fit_bins` | Number of elevation levels in the fit | count | int | never |
| `max_frac_resid` | Maximum absolute fractional volume residual across the fitted levels | fraction | float | blank when `n_fit_bins=0` (1 dam) |
| `rms_frac_resid` | Root-mean-square of the absolute fractional volume residual across the fitted levels | fraction | float | blank when `n_fit_bins=0` (1 dam) |
| `abs_frac_resid_full_pool` | Absolute fractional volume residual at the top fitted level | fraction | float | blank when `n_fit_bins=0` (1 dam) |
| `median_abs_frac_resid_upper_half` | Median absolute fractional volume residual over the fitted levels whose area is at least half of the top fitted area | fraction | float | blank when `n_fit_bins=0` (1 dam) |
| `median_abs_frac_resid_quarter_to_half` | Median absolute fractional volume residual over the fitted levels whose area is a quarter to a half of the top fitted area | fraction | float | blank when no fitted level has such an area (6 dams, the dam without a curve included) |
| `median_abs_frac_resid_tenth_to_quarter` | Median absolute fractional volume residual over the fitted levels whose area is a tenth to a quarter of the top fitted area | fraction | float | blank when no fitted level has such an area (23 dams, the dam without a curve included) |
| `median_abs_frac_resid_below_tenth` | Median absolute fractional volume residual over the fitted levels whose area is below a tenth of the top fitted area | fraction | float | blank when no fitted level has such an area (54 dams, the dam without a curve included) |
| `abs_frac_dev_typical_extent` | Departure of the power law from the EAV table, \|c · a<sup>b</sup> / V(a) − 1\|, at the area a that is the typical satellite extent of the domain (the median of `sat_over_dem` in `validation/dem_vs_sat_area.csv`, 0.2052 here) times the top fitted area, with V(a) interpolated in the table | fraction | float | blank for 3 dams |
| `rms_frac_resid_upper_volume` | Root-mean-square of the absolute fractional volume residual over the fitted levels holding at least a tenth of the maximum fitted volume | fraction | float | blank when `n_fit_bins=0` (1 dam) |
| `rms_frac_resid_two_segment` | Root-mean-square fractional residual of the best two-segment straight-line fit in log space (the break chosen by the log-space sum of squares, at least three levels per segment), the alternative to the single power law | fraction | float | blank with fewer than 6 fitted levels (10 dams, the dam without a curve included) |
| `rms_frac_resid_two_segment_upper_volume` | The same for the two-segment fit over the levels holding at least a tenth of the maximum fitted volume | fraction | float | blank with fewer than 6 fitted levels (10 dams, the dam without a curve included) |

---

## `validation/acap_regression_diagnostics.csv`: A_cap regression collinearity and skill

Variance-inflation factors, incremental leave-one-out skill and drop-one leave-one-out skill for the seven-feature `log A_cap` anchor regression.

| Column | Definition | Unit | dtype | Missing |
| --- | --- | --- | --- | --- |
| `diagnostic` | Row type (`vif`, `condition_number`, `incremental_loo`, `incremental_loo_no_capacity`, `drop_one_loo`) | - | str | never |
| `feature` | Feature name, the feature added (incremental rows) or removed (drop-one rows) | - | str | never |
| `n_features` | Number of features in the regression of the row (incremental and drop-one rows) | count | int | blank for VIF rows |
| `value` | VIF / condition-number / LOO-RMS value | mixed | float | never |
| `metric` | Metric label | - | str | never |
| `delta_loo_rms_log10` | Reduction of the LOO RMS attributed to the feature, the model without it minus the model with it, so positive when the feature lowers the error | log10 units | float | blank for VIF and condition-number rows and for the first row of each incremental sequence |

---

## `validation/dem_error_montecarlo.csv`: SRTM vertical-error propagation (sampled dams)

Per-dam Monte Carlo simulation of how SRTM vertical error (90% linear error, LE90, of about 6 m after [Rodríguez et al. (2006)](https://doi.org/10.14358/PERS.72.3.249), σ ≈ 3.6 m, spatially correlated over about 2 grid cells) propagates into recovered volume. One row per sampled dam, written by the opt-in `--dem-mc` validation step. Released `c`/`b` are unchanged, so this characterizes uncertainty only.

| Column | Definition | Unit | dtype | Missing |
| --- | --- | --- | --- | --- |
| `dam_id` | Persistent dam identifier | - | str | never |
| `capacity_mcm` | Catalog design capacity | MCM | float | catalog-derived |
| `released_b`, `released_max_vol_mcm` | Released (unperturbed) exponent and max volume | -, MCM | float | never |
| `ref_b`, `ref_max_vol_mcm` | Re-fit on the unperturbed surface (reproduces released) | -, MCM | float | never |
| `n_realizations`, `n_ok`, `n_fail` | Noise realizations attempted / succeeded / failed | count | int | never |
| `ref_n_pixels` | Footprint grid-cell count | count | int | never |
| `ref_curve_type` | `full` or `partial` | - | str | never |
| `sigma_logV_realizations` | 1σ spread of log10 volume across realizations | log10 units | float | never |
| `vol_frac_std`, `vol_frac_abs_p50`, `vol_frac_abs_p84` | Std, P50, P84 of the absolute fractional volume deviation | fraction | float | never |
| `vol_ratio_p16`, `vol_ratio_p84` | P16/P84 of perturbed-over-reference volume ratio | - | float | never |
| `b_mean_realizations`, `b_std_realizations` | Mean and std of fitted `b` across realizations | - | float | never |

---

## `validation/sensitivity_sweep.csv`: placement/acceptance constant sensitivity (26 rows)

One row per (constant, perturbation) cell. Each of the five swept constants is perturbed by ±20% and ±30% over a sample of 54 trusted dams, and each row gives the trusted set and the median exponent of that cell. The 26 rows are the shared baseline row and five rows per constant, the four perturbations and a copy of the baseline at perturbation 0. Written by the opt-in `--sensitivity` validation step.

| Column | Definition | Unit | dtype | Missing |
| --- | --- | --- | --- | --- |
| `constant` | Perturbed constant, or `baseline` | - | str | never |
| `perturbation_frac` | Fractional perturbation applied | fraction | float | never |
| `value` | Resulting constant value | mixed (m for `DRAIN_WALL_TOLERANCE_M`, dimensionless otherwise) | float | blank for baseline |
| `n_sample`, `n_success` | Dams sampled / successfully processed | count | int | never |
| `n_trusted`, `frac_trusted` | Trusted-set count and fraction | count, fraction | int/float | never |
| `median_b_trusted` | Median exponent over the trusted set | - | float | never |
| `grade_A` … `grade_F` | Count per quality grade | count | int | never |

`constant` controlled vocabulary: `baseline` (1), `ALIGN_WEIGHT` (5),
`MAX_CREST_FLOW_DOT` (5), `VOID_THRESHOLD` (5), `DRAIN_WALL_TOLERANCE_M` (5),
`DRAIN_MAX_OUTLET_POSITION` (5). The first two are the placement-scoring
constants, the alignment weight and the maximum crest-flow dot product (the
largest accepted alignment of the wall with the flow direction). The other
three are flood-fill acceptance constants, namely the internal void-fraction
threshold (the void fraction at which a fill is rejected) and the two constants
of the drainage rule. The drainage wall tolerance is the distance past the half
wall within which a pool outlet counts as next to the wall, and the maximum
outlet position is the largest accepted position of the outlets along the
capacity-level pool.

---

## `baish_bathymetry/baish_area_elev_vol.csv`: Baish design and sonar bathymetry (cross-reference input)

Elevation-area-volume table for Baish (`id_120000`), shipped in the repository as the bathymetry cross-reference. The `*_design` columns are the design curve, tabulated from the top of dead storage at 270 m a.s.l. The `*_integrated_dem` columns are the curve of the February 2025 sonar survey, which describes the reservoir in 2025, is tabulated from the same level and holds no area below 282 m a.s.l. `capacity_loss_%` is the resulting loss at each level.

| Column | Definition | Unit | dtype | Missing |
| --- | --- | --- | --- | --- |
| `water_level_m` | Water level above the top of dead storage (270 m a.s.l.) | m | float | never |
| `elevation_m` | Absolute elevation | m a.s.l. | float | never |
| `area_m2_design`, `volume_m3_design` | Original design area and volume | m², m³ | float | never |
| `area_m2_integrated_dem`, `volume_m3_integrated_dem` | Present-day (2025 sonar) area and volume | m², m³ | float | never |
| `capacity_loss_%` | Capacity loss, integrated vs design | % | float | never |
