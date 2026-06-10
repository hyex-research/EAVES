# EAVES KSA release — data dictionary

Schema for every CSV under `region/ksa/output/1_results_csv/`. Each dam is
keyed by `dam_id` (string, e.g. `id_010000`), which is consistent across all
files.

## Conventions

- **Units.** `eav_tables/*.csv` store volume in cubic metres (`volume_m3`) and
  area in square metres (`area_m2`). `eaves_params.csv`, `eaves_summary.csv`,
  and the `validation/` summaries store volume in million cubic metres (MCM,
  `*_mcm`). The conversion is `1 MCM = 1e6 m^3`. Watch this 10^6 factor when
  joining `eav_tables` against the MCM tables. The power-law coefficient `c`
  is fit in SI units, so `V = c·A^b` takes area in m^2 and returns volume in
  m^3 (e.g. Baish: `c=0.00767`, `b=1.506`, `A=8.13e6 m^2` -> `1.96e8 m^3`,
  i.e. 196 MCM). Divide by 1e6 to obtain MCM.
- **Missing values.** Numeric blanks are empty cells (`NaN` on read).
  `construction_year` is a nullable integer; absent years are left blank (NOT
  imputed to a sentinel year). `uncertainty_flags` uses the literal string `-`
  to mean "no flags".
- **dtype** notation: `str`, `int`, `Int (nullable)`, `float`, `bool`.
- **Source provenance.** Each dam is either `srtm_derived` (curve fitted to
  flooded SRTM topography) or `regi_multi` (regionalized: `b` set to the
  regional median, `c` back-solved from catalog capacity via the multi-feature
  anchor). See `source` below.
- **Error reporting.** Volume errors are multiplicative: computed in base-10
  log-ratio space, stored as `*_log10` columns (and as signed decimal fractions,
  e.g. `0.29 = +29%`). Prose and tables report them relatively — a percentage
  below 100%, a multiplicative factor at or above 100% (`% = 10^σ − 1`,
  `factor = 10^σ`). Raw log10 is an internal computation form only.

## Catalog-derived fields in the release

The following columns are passed through from the proprietary Saudi dam
catalog (the catalog itself is not redistributed; these per-dam attributes
are). A reuser receives exactly these catalog-derived fields, at the
precision listed. See the "Catalog accessibility" section at the end for the
full statement.

| Field | Files | Precision as released |
| --- | --- | --- |
| `lat`, `lon` | `eaves_summary.csv` | Catalog value passed through verbatim (decimal degrees, WGS84). Most rows carry 6 decimal places (~0.1 m); a minority carry 2–8. No fixed rounding is applied. |
| `capacity_mcm` | `eaves_params.csv`, `eaves_summary.csv`, `failed_dams.csv`, `validation/*` | Design capacity, MCM, full catalog precision (up to 6 decimals). |
| `dam_height_m` | `eaves_summary.csv`, `failed_dams.csv` | Metres, full catalog precision (up to 2 decimals). |
| `spillway_height_m` | `eaves_summary.csv`, `failed_dams.csv` | Metres, full catalog precision (up to 3 decimals). |
| `dam_length_m` | `eaves_summary.csv`, `failed_dams.csv` | Metres, full catalog precision (up to 2 decimals). |
| `construction_year` | `eaves_summary.csv` | Year (stored as integral-valued float; parse as nullable Int64); blank when the catalog has no year (21 dams). |

---

## `eaves_params.csv` — lean per-dam EAV coefficients (526 rows)

| Column | Definition | Unit | dtype | Missing |
| --- | --- | --- | --- | --- |
| `dam_id` | Persistent dam identifier | — | str | never |
| `dam_name` | Latin-transliterated dam name | — | str | may be empty |
| `capacity_mcm` | Catalog design capacity | MCM | float | never |
| `c` | Power-law coefficient in `V = c·A^b` (A in m^2 -> V in m^3) | — | float | never |
| `b` | Power-law exponent in `V = c·A^b`, clamped to the physically plausible interval [1.1, 2.0] (raw least-squares fit in `eaves_summary.csv`) | — | float | never |
| `c` (clamped dams) | For the 39 dams whose `b` was clamped, `c` is re-solved through the recovered SRTM full-pool anchor (V_srtm_max at the footprint area), so it differs from the raw `c` in `eaves_summary.csv` | — | float | never |
| `source` | Provenance | — | str | never |

`source` controlled vocabulary: `srtm_derived` (322), `regi_multi` (204).

---

## `eaves_summary.csv` — full per-dam diagnostics (504 rows)

The 504 dams that produced a curve (`526 − 22` regionalized-only without a DEM
footprint; the 24 placement failures live in `failed_dams.csv`, of which 2
were recovered into this summary).

| Column | Definition | Unit | dtype | Missing |
| --- | --- | --- | --- | --- |
| `dam_id` | Persistent dam identifier | — | str | never |
| `dam_name` | Latin-transliterated dam name | — | str | may be empty |
| `construction_year` | Catalog construction year | year | float (integral-valued; parse as nullable Int64) | blank for 21 dams |
| `dam_height_m` | Catalog dam height | m | float | catalog-derived |
| `spillway_height_m` | Catalog spillway height (fill depth used) | m | float | catalog-derived |
| `dam_length_m` | Catalog crest length | m | float | catalog-derived |
| `capacity_mcm` | Catalog design capacity | MCM | float | never |
| `curve_type` | Whether SRTM saw a bare valley or standing water | — | str | never |
| `srtm_water_level_m` | Detected flat-water surface elevation (partial curves only) | m | float | blank unless `curve_type=partial` |
| `coverage_fraction` | Fraction of the vertical valley range above the detected water surface (1.0 for full curves) | — | float | never |
| `z_min` | Minimum SRTM elevation in the flooded footprint | m | float | never |
| `z_max` | Maximum SRTM elevation in the flooded footprint | m | float | never |
| `footprint_area_km2` | Flooded footprint area at spillway level | km^2 | float | never |
| `c` | Power-law coefficient `V = c·A^b` | — | float | blank for the 2 grade-F fits |
| `b` | Power-law exponent | — | float | blank for the 2 grade-F fits |
| `r_squared` | R^2 of the log–log power-law fit | — | float | blank for the 2 grade-F fits |
| `n_pixels` | Active (flooded) SRTM pixels in the footprint | count | int | never |
| `void_fraction` | Fraction of footprint pixels that are SRTM voids | — | float | never |
| `capped` | Integrated volume reached the catalog-capacity cap and was truncated there (the catalog values are spillway/gross capacities; the cap bounds the SRTM fill) | — | bool | never |
| `placement_upstream_shift_m` | Distance the dam wall was shifted upstream during placement | m | float | never |
| `placement_method` | Which placement stage produced the wall | — | str | never |
| `valley_width_m` | Estimated valley width at the wall | m | float | may be NaN |
| `valley_ratio` | Valley width / depth aspect ratio | — | float | may be NaN |
| `channel_slope` | Local channel slope at the wall | m/m | float | may be NaN |
| `mean_catchment_slope` | Mean slope of the upstream catchment | m/m | float | may be NaN |
| `upstream_area_km2` | Upstream contributing area (MERIT Hydro) | km^2 | float | may be NaN |
| `lat` | Catalog latitude (WGS84) | deg | float | catalog-derived |
| `lon` | Catalog longitude (WGS84) | deg | float | catalog-derived |
| `srtm_max_vol_mcm` | Maximum volume of the SRTM-derived curve at spillway level | MCM | float | never |
| `vol_ratio` | `srtm_max_vol_mcm / capacity_mcm` | — | float | never |
| `z_range` | `z_max − z_min` | m | float | never |
| `z_range_ratio` | `z_range / spillway_height_m` | — | float | NaN if spillway 0 |
| `quality` | Per-dam quality grade | — | str | never |
| `uncertainty_flags` | `;`-joined active reliability flags, or `-` if none | — | str | `-` when none |
| `uncertainty_score` | Number of active uncertainty flags (0–5 by construction; 0–3 realized on this domain) | count | int | never |
| `sed_yield_t_ha_yr` | Delivered sediment yield at the reservoir inlet (Dash et al. 2025: RUSLE gross erosion x area-dependent delivery ratio, applied at the source) | t ha^-1 yr^-1 | float | may be blank |
| `owe_mm_year` | Open-water evaporation (external input) | mm yr^-1 | float | blank for 67 dams |
| `predicted_silt_fraction` | First-order predicted fraction of design capacity lost to sediment by the reference year 2026 (capped at 1.0; computed from the delivered yield with no additional delivery ratio) | fraction | float | blank when catchment-yield inputs are missing |
| `sediment_risk` | Categorical sediment-loss risk derived from `predicted_silt_fraction` | — | str | `unknown` when inputs are missing |

Controlled vocabularies:

- `curve_type`: `full` (bare-valley capture), `partial` (standing water in the
  Feb-2000 SRTM footprint; fit restricted to elevations above
  `srtm_water_level_m`).
- `quality`: `A`, `B`, `C`, `D`, `F` (decreasing reliability; `A`/`B` are the
  trusted grades, `F` are unusable fits).
- `placement_method`: `stage_1_fast_path`, `stage_2_upstream_walk`,
  `stage_3_quality_recovery`, `stage_4_river_retry`,
  `stage_5_relaxed_alignment`, `stage_6_fallback` (the cascade of dam-wall
  placement strategies, in order of preference).
- `uncertainty_flags` atomic tokens (combine with `;`):
  - `sub_pixel` — footprint smaller than 30 active pixels (geometry undersampled).
  - `narrow_valley` — valley width below 3 pixels (cross-section undersampled).
  - `height_noise` — spillway height < 5 m, comparable to SRTM vertical noise.
  - `flat_terrain`, `tall_and_narrow` — defined by construction but not triggered on the Saudi domain (so absent from the released tables here).
  - `-` — no flags active.
- `capped`: `True` / `False`.
- `sediment_risk`: `low`, `moderate`, `high`, `severe`, `fully_silted`, `unknown` (increasing predicted capacity loss; `unknown` = missing catchment-yield inputs). Counts on the Saudi domain: 64 / 89 / 97 / 84 / 149 / 21.

---

## `eav_tables/<dam_id>_eav.csv` — hypsometry tables (504 files)

One file per dam in `eaves_summary.csv`. Cumulative area and volume as a
function of elevation, in 0.5 m steps from `z_min` to spillway level.

| Column | Definition | Unit | dtype | Missing |
| --- | --- | --- | --- | --- |
| `elevation_m` | Water-surface elevation | m | float | never |
| `area_m2` | Flooded surface area at this elevation | **m^2** | float | never |
| `volume_m3` | Cumulative impounded volume below this elevation | **m^3** | float | never |

Note the units are m^2 / m^3 here, NOT MCM. `volume_m3 = 0` at the bottom row.

---

## `failed_dams.csv` — dams with no usable SRTM curve (24 rows)

| Column | Definition | Unit | dtype | Missing |
| --- | --- | --- | --- | --- |
| `dam_id` | Persistent dam identifier | — | str | never |
| `dam_name` | Latin-transliterated dam name | — | str | may be empty |
| `reason` | Failure category | — | str | never |
| `detail` | Free-text failure description | — | str | never |
| `capacity_mcm` | Catalog design capacity | MCM | float | catalog-derived |
| `dam_height_m` | Catalog dam height | m | float | catalog-derived |
| `spillway_height_m` | Catalog spillway height | m | float | catalog-derived |
| `dam_length_m` | Catalog crest length | m | float | catalog-derived |
| `upstream_area_km2` | Upstream contributing area | km^2 | float | may be NaN |
| `valley_width_m` | Estimated valley width | m | float | may be NaN |
| `valley_ratio` | Valley aspect ratio | — | float | may be NaN |
| `channel_slope` | Local channel slope | m/m | float | may be NaN |
| `mean_catchment_slope` | Mean catchment slope | m/m | float | may be NaN |

`reason` controlled vocabulary: `placement_failed` (13), `bad_fill_auto` (9),
`fit_failed` (2). These dams carry catalog and topographic attributes so the
regionalization recipe can still reach them.

---

## `threshold_analysis.csv` — reliability vs capacity sweep (39 rows)

| Column | Definition | Unit | dtype |
| --- | --- | --- | --- |
| `threshold_mcm` | Capacity cut-off | MCM | float |
| `n_above` | Dams with capacity at or above the threshold | count | int |
| `n_reliable` | Of those, dams meeting the trusted/grade criteria | count | int |
| `frac_reliable` | `n_reliable / n_above` | — | float |

---

## `domain_characterization.csv` — domain-level summary statistics (long form)

A two-column `statistic,value` table of population summaries (dam counts by
source/era, capacity percentiles, the regional `b` distribution, LOO anchor
skill, sediment-budget summaries, and the `b`-clustering diagnostic). Values
are strings/numbers; the key names are self-describing. Volume statistics are
in MCM (`*_mcm`); dimensionless skill metrics are in log10 units.

Selected keys: `n_dams_with_params=526`, `n_dams_summary=504`,
`n_dams_failed_pipeline=24`, `n_params_source_srtm_derived=322`,
`n_params_source_regi_multi=204`, `b_median=1.5019…`, `b_sigma=0.2645…`,
`b_cluster_best_gain_pct=14.0…`,
`loo_multi_anchor_within_2x_frac=0.8944…` / `_within_3x_frac=0.9845…`
(stored as decimal fractions).

---

## `validation/b_clustering_diagnostic.csv`

K-means clustering diagnostic on `b` (Supp panel S1).

| Column | Definition | Unit | dtype |
| --- | --- | --- | --- |
| `feature_set` | Feature set fed to clustering | — | str |
| `k` | Number of clusters | count | int |
| `silhouette` | Silhouette score | — | float |
| `loo_sigma_delta_b` | LOO σ of Δb with clustering | dimensionless | float |
| `loo_sigma_baseline` | LOO σ of Δb with the global-median baseline | — | float |
| `loo_relative_gain_pct` | Relative reduction in σ from clustering | % | float |
| `n_trusted` | Trusted dams used | count | int |

---

## `validation/dem_vs_sat_area.csv` — DEM footprint vs satellite area

| Column | Definition | Unit | dtype | Missing |
| --- | --- | --- | --- | --- |
| `dam_id` | Persistent dam identifier | — | str | never |
| `dam_name` | Latin-transliterated dam name | — | str | may be empty |
| `capacity_mcm` | Catalog design capacity | MCM | float | catalog-derived |
| `A_DEM_km2` | SRTM-derived design footprint area | km^2 | float | never |
| `A_sat_P95_km2` | 95th-percentile observed satellite water area | km^2 | float | blank when no obs |
| `n_sat_obs` | Number of satellite observations | count | int | never |
| `quality` | Per-dam quality grade (see summary) | — | str | never |
| `sat_over_dem` | `A_sat_P95_km2 / A_DEM_km2` | — | float | blank when no obs |
| `log10_ratio` | log10 of `sat_over_dem` | log10 units | float | blank when no obs |
| `flag` | Comparison flag | — | str | empty when neither applies |

`flag` controlled vocabulary: `sat_much_smaller` (197), `no_sat` (40), empty (85).
`no_sat` means zero or no observed water area: 34 of the 40 have satellite
observations but a zero 95th-percentile extent (`A_sat_P95_km2 = 0.0`), the
other 6 have no usable record (blank columns).

---

## `validation/regionalization_loo.csv` — leave-one-out reconstruction skill

Per-dam leave-one-out comparison of three anchors (current satellite-P95,
log–log primary, multi-feature LR) against the SRTM-derived reference, at
100% / 50% / 10% pool. Columns follow the pattern
`<anchor>_<quantity>` where `<anchor> ∈ {current, alt, multi}`.

| Column group | Definition | Unit |
| --- | --- | --- |
| `dam_id`, `capacity_mcm`, `A_DEM_km2`, `A_sat_P95_km2`, `n_sat_obs` | dam keys and inputs (catalog/SRTM/satellite) | mixed (MCM, km^2, count) |
| `c_srtm`, `b_srtm` | SRTM-derived reference coefficients | — |
| `b_reg`, `delta_b` | regional-median b and its deviation from `b_srtm` | — |
| `current_source` / `alt_source` / `multi_source` | which anchor variant produced the row | — |
| `*_A_cap_km2` | anchor footprint area | km^2 |
| `*_c`, `*_log10_c_ratio` | anchor coefficient and its log10 ratio vs reference | — / log10 units |
| `*_V_at_{100,050,010}pct_m3` | anchor volume at that pool fraction | **m^3** |
| `*_log10_V_ratio_at_{100,050,010}pct` | log10 volume ratio vs the SRTM reference | log10 units |
| `V_srtm_at_{100,050,010}pct_m3` | SRTM-reference volume at that pool fraction | **m^3** |

Source vocabularies: `current_source ∈ {current_sat_p95 (282),
current_sat_fallback (40)}`; `alt_source = alt_loglog_primary`;
`multi_source = multi_lr_primary`. Volumes in this file are in m^3.

---

## `validation/v_uncertainty.csv` — per-dam volume uncertainty band

Propagated `b_sigma` band at half / quarter / tenth pool (Supp panel S3).

| Column | Definition | Unit | dtype | Missing |
| --- | --- | --- | --- | --- |
| `dam_id` | Persistent dam identifier | — | str | never |
| `source` | `srtm_derived` or `regi_multi` | — | str | never |
| `capacity_mcm` | Catalog design capacity | MCM | float | catalog-derived |
| `b` | Power-law exponent | — | float | never |
| `b_sigma` | Regional `b` spread used for the band | — | float | never |
| `A_cap_km2` | Footprint area at full pool | km^2 | float | never |
| `sigma_log_acap` | LOO error of the predicted `log10 A_cap` (regionalized anchor term, 0 for `srtm_derived`) | log10 units | float | never |
| `sigma_log_vcap` | Catalog-capacity error term | log10 units | float | never |
| `sigma_acap_term` | `b · sigma_log_acap`, the area-anchor term as it enters the volume band | log10 units | float | never |
| `V_sigma_bspread_{half,quarter,tenth}_pool` | Geometric `b_sigma`-only component of the band | log10 units | float | never |
| `V_pred_{half,quarter,tenth}_pool_mcm` | Predicted volume at that pool fraction | MCM | float | never |
| `V_sigma_log10_{half,quarter,tenth}_pool` | 1σ band width in log10 | log10 units | float | never |
| `V_frac_up_{...}_pool` / `V_frac_down_{...}_pool` | +1σ / −1σ as decimal fractions (0.29 = +29%, 1.32 = +132%), reported in the paper above 100% as the multiplicative factor 1 + value (1.32 → a factor of 2.3) | fraction | float | never |

`source` vocabulary: `srtm_derived` (322), `regi_multi` (204).

---

## `validation/goodness_of_fit.csv` — non-mechanical fit quality (504 rows)

Fractional volume residual of the power-law fit in the deployed area-to-volume direction, reported alongside `r_squared` (which is partly mechanical because `V` is the integral of `A`).

| Column | Definition | Unit | dtype | Missing |
| --- | --- | --- | --- | --- |
| `dam_id` | Persistent dam identifier | — | str | never |
| `source` | `srtm_derived` or `regi_multi` | — | str | never |
| `quality` | Letter grade A–F | — | str | never |
| `r_squared` | Power-law fit R^2 (partly mechanical) | — | float | never |
| `is_trusted` | In the trusted set | — | bool | never |
| `n_fit_bins` | Number of elevation bins in the fit | count | int | never |
| `max_frac_resid` | Maximum fractional volume residual across bins | fraction | float | never |
| `rms_frac_resid` | RMS fractional volume residual across bins | fraction | float | never |

---

## `validation/acap_regression_diagnostics.csv` — A_cap regression collinearity and skill

Variance-inflation factors and incremental leave-one-out skill for the seven-feature `log A_cap` anchor regression.

| Column | Definition | Unit | dtype | Missing |
| --- | --- | --- | --- | --- |
| `diagnostic` | Row type (`vif`, `condition_number`, `incremental_loo`, `incremental_loo_no_capacity`) | — | str | never |
| `feature` | Feature name or cumulative feature set | — | str | blank for summary rows |
| `n_features` | Number of features (incremental-LOO rows) | count | int | blank for VIF rows |
| `value` | VIF / condition-number / LOO-RMS value | mixed | float | never |
| `metric` | Metric label | — | str | never |
| `delta_loo_rms_log10` | Change in LOO RMS when the feature is added | log10 units | float | blank for VIF rows |

---

## `validation/dem_error_montecarlo.csv` — SRTM vertical-error propagation (sampled dams)

Per-dam Monte-Carlo of how SRTM vertical noise (LE90 ≈ 6 m, σ ≈ 3.6 m, correlated over ~2 pixels) propagates into recovered volume. One row per sampled dam; written by the opt-in `--dem-mc` validation step. Released `c`/`b` are unchanged — this characterizes uncertainty only.

| Column | Definition | Unit | dtype | Missing |
| --- | --- | --- | --- | --- |
| `dam_id` | Persistent dam identifier | — | str | never |
| `capacity_mcm` | Catalog design capacity | MCM | float | catalog-derived |
| `released_b`, `released_max_vol_mcm` | Released (unperturbed) exponent and max volume | —, MCM | float | never |
| `ref_b`, `ref_max_vol_mcm` | Re-fit on the unperturbed surface (reproduces released) | —, MCM | float | never |
| `n_realizations`, `n_ok`, `n_fail` | Noise realizations attempted / succeeded / failed | count | int | never |
| `ref_n_pixels` | Footprint pixel count | count | int | never |
| `ref_curve_type` | `full` or `partial` | — | str | never |
| `sigma_logV_realizations` | 1σ spread of log10 volume across realizations | log10 units | float | never |
| `vol_frac_std`, `vol_frac_abs_p50`, `vol_frac_abs_p84` | Std, P50, P84 of the absolute fractional volume deviation | fraction | float | never |
| `vol_ratio_p16`, `vol_ratio_p84` | P16/P84 of perturbed-over-reference volume ratio | — | float | never |
| `b_mean_realizations`, `b_std_realizations` | Mean and std of fitted `b` across realizations | — | float | never |

---

## `validation/sensitivity_sweep.csv` — placement/acceptance constant sensitivity

One row per (constant, perturbation) cell: effect of perturbing each tuned constant by ±20–30% on the trusted set and median exponent. Written by the opt-in `--sensitivity` validation step.

| Column | Definition | Unit | dtype | Missing |
| --- | --- | --- | --- | --- |
| `constant` | Perturbed constant, or `baseline` | — | str | never |
| `perturbation_frac` | Fractional perturbation applied | fraction | float | never |
| `value` | Resulting constant value | mixed | float | blank for baseline |
| `n_sample`, `n_success` | Dams sampled / successfully processed | count | int | never |
| `n_trusted`, `frac_trusted` | Trusted-set count and fraction | count, fraction | int/float | never |
| `median_b_trusted` | Median exponent over the trusted set | — | float | never |
| `grade_A` … `grade_F` | Count per quality grade | count | int | never |

---

## `input/ksa_dams/baish_bathymetry/baysh_area_elev_vol.csv` — Baish design and sonar bathymetry (cross-reference input)

Elevation-area-volume table for Baish (`id_120000`), shipped in the repository as the bathymetry cross-reference. The `*_design` columns are the original design curve (floor 270 m a.s.l.). The `*_integrated_dem` columns are the present-day curve from the February 2025 sonar survey, with a sediment-raised floor near 282 m a.s.l. (about 12 m above the design floor). `capacity_loss_%` is the resulting loss at each level.

| Column | Definition | Unit | dtype | Missing |
| --- | --- | --- | --- | --- |
| `water_level_m` | Water level above the design floor | m | float | never |
| `elevation_m` | Absolute elevation | m a.s.l. | float | never |
| `area_m2_design`, `volume_m3_design` | Original design area and volume | m^2, m^3 | float | never |
| `area_m2_integrated_dem`, `volume_m3_integrated_dem` | Present-day (2025 sonar) area and volume | m^2, m^3 | float | never |
| `capacity_loss_%` | Capacity loss, integrated vs design | % | float | never |

---

## Catalog accessibility (release contents)

The primary Saudi dam catalog is not redistributed as a standalone product.
However, this release reproduces, per dam, the following catalog-derived
attributes so that each `dam_id` can be tied to a real reservoir and reused:

- **Coordinates** `lat`, `lon` (WGS84 decimal degrees), in `eaves_summary.csv`,
  passed through at the catalog's native precision (most rows 6 decimal places,
  a minority 2–8; no fixed rounding applied).
- **Design capacity** `capacity_mcm`, in `eaves_params.csv`,
  `eaves_summary.csv`, `failed_dams.csv`, and the `validation/` files.
- **Dam height** `dam_height_m`, **spillway height** `spillway_height_m`, and
  **crest length** `dam_length_m`, in `eaves_summary.csv` and `failed_dams.csv`
  (metres, native catalog precision).
- **Construction year** `construction_year`, in `eaves_summary.csv` (blank,
  not imputed, for the 21 dams without a catalog year).

No other catalog fields are released. A reuser therefore receives the full
per-dam geolocation and core morphometry needed to map `dam_id` to a physical
reservoir, but not the catalog as a redistributable table.
