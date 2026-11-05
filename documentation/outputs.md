# Outputs

A run writes its outputs to the `output_dir` of the settings file, `region/<country>/output/` for a region. The [`DATA_DICTIONARY.md`](../region/ksa/output/1_results_csv/DATA_DICTIONARY.md) beside the released tables defines every column with its unit and controlled vocabulary.

## CSV files (`output/1_results_csv/`)

| File | Description |
| --- | --- |
| `eaves_params.csv` | Per-dam parameter table with six columns (`dam_id`, `dam_name`, `capacity_mcm`, `c`, `b`, `source`) and no empty cells, sorted by `dam_id`. `source` is `srtm_derived` (fit to the DEM) or `regi_multi` (regionalized, with the regional-median `b`, or the `b` of the regression on morphometric features when that regression passes its leave-one-out test, and the multi-feature regression anchor). The 1σ uncertainty of `b` is a regional value, stored in `validation/v_uncertainty.csv` and `domain_characterization.csv`. |
| `eaves_summary.csv` | One row per dam of `eaves_params.csv`: fitted `c`, `b`, `r_squared`, footprint area, quality grade, placement method, uncertainty flags (`uncertainty_flags`, `uncertainty_score`), `upstream_area_km2`, and, when `sedimentation_dir` is provided, `sed_yield_t_ha_yr` (delivered yield), `owe_mm_year`, and the `predicted_silt_fraction` and `sediment_risk` that the report step adds. A dam without a flood fill keeps its catalog attributes, coordinates, topographic features and external attributes, and its fill and fit cells are empty. Sorted by `dam_id`. |
| `failed_dams.csv` | Dams failing wall placement, fill acceptance, or the power-law fit, with failure reason, catalog attributes (including `construction_year`), and the topographic features attached at failure time. Every dam of this table also has a row in `eaves_summary.csv`. Sorted by `dam_id`. |
| `threshold_analysis.csv` | Capacity-threshold sweep behind the training cut of the regional exponent. |
| `domain_characterization.csv` | Key/value table of the domain statistics surfaced in `report.md`. |
| `domain_characterization.json` | The same statistics as `domain_characterization.csv` with typed values, written beside it by the report step for machine reading. |
| `validation/regionalization_loo.csv` | Per-dam LOO residuals of the three regionalization anchors (the selected multi-feature regression, the capacity-only regression and the satellite 95th-percentile extent) at full, half and tenth pool, evaluated on the training dams. |
| `validation/dem_vs_sat_area.csv` | Per-dam SRTM-derived full-pool area against the 95th-percentile satellite-observed water area (diagnostic only). |
| `validation/b_clustering_diagnostic.csv` | Silhouette, LOO σ(Δb) and LOO R² of the per-cluster median over k for the six morphometric features of the clustering (valley-width ratio, channel slope, mean catchment slope, dam height, spillway height and dam length), with the variance shares of the first two principal components of the features and the Spearman correlation of `b` with the first, written by the s1 panel. Backs supplementary figure S1. |
| `validation/v_uncertainty.csv` | Per-dam V uncertainty band at half, quarter, and tenth pool (log10 units and +%/-% bands), combining the geometric `b_sigma` term, the catalog-capacity term, and, for regionalized dams, the predicted-area term. Written by `eaves.postprocess.uncertainty`. Backs supplementary figure S2. |
| `validation/goodness_of_fit.csv` | Per-fit maximum and root-mean-square of the absolute fractional volume residual over the fitted levels, its medians by fill level, its departure at the typical satellite extent and the residual of the two-segment alternative, with `is_trusted` and `in_training` membership columns. |
| `validation/acap_regression_diagnostics.csv` | Collinearity (VIF, condition number), incremental and drop-one LOO skill of the seven anchor features (long-form table). |
| `validation/sensitivity_sweep.csv` | Trusted-set size, grade counts, and median trusted `b` as each of the five swept constants (the two placement-scoring constants, the void-fraction threshold of the flood-fill acceptance and the two constants of the drainage rule) is perturbed by ±20-30%. Written only by the opt-in `--sensitivity` step (see [usage.md](usage.md)). |
| `validation/dem_error_montecarlo.csv` | Per-dam spread of recovered volume and `b` across SRTM vertical-error realizations. Written only by the opt-in `--dem-mc` step (see [usage.md](usage.md)). |
| `eav_tables/{dam_id}_eav.csv` | Per-dam tabulated (z, A, V) at levels 0.5 m apart from the floor of the fill, with the last level at the spillway elevation or, for capped fills, at the elevation where the volume reaches the catalog capacity, and the depth above the bottom of the fill beside the elevation. |

Every table is written at a fixed precision. A floating-point value is rounded to four significant digits and never fewer than two decimals and written in its shortest form, so an elevation rounded to 666.50 reads `666.5`, an area in an EAV table `861.55` and a channel slope `0.0001338`. `capacity_mcm`, the exponent `b` and the columns named after it keep four decimals, and the coordinates and dam dimensions (`dam_height_m`, `spillway_height_m`, `dam_length_m`) are written as they come from the catalog.

## Panel figures (`output/2_results_plots/`, written by the panels step)

Every panel is emitted as both a 300-dpi PNG and a vector PDF with the same stem. `report.md` embeds the PNGs of the main panels and of the supplementary panels s1 and s2.

| File | Description |
| --- | --- |
| `p1_domain_flowchart.png` | Domain map (a) + pipeline flowchart (b) |
| `p2_placement.png` | Examples of the six-stage dam-wall placement procedure, one each from stages 1, 4 and 6 |
| `p3_baish_example.png` | EAVES outputs at Baish and the distribution of the unconstrained exponents over the trusted dams |
| `p4_regionalization_validation.png` | Leave-one-out evaluation of the regionalization procedure on the training dams at full, half and tenth pool |
| `p5_comparison.png` | Baish comparison and domain-wide volume ratio, (a) area-volume and (b) elevation-area curves from SRTM, the 2025 sonar survey and the design table, and (c) the distribution of maximum SRTM-derived volume divided by catalog capacity. SRTM shows the valley in 2000 and the survey the reservoir in 2025, so the comparison alone cannot separate reconstruction error from changes in reservoir geometry |
| `p6_grdl_comparison.png` | Comparison of SRTM-derived and GRDL reservoir curves at Baish, Hali and Rabigh, (a) area-volume and (b) depth-area curves, one row per dam. Both products use SRTM and GRDL is itself a reconstruction, so the comparison assesses consistency rather than accuracy against measured bathymetry |
| `s1_b_clustering_silhouette.png` | Supplementary: K-means clustering diagnostic for `b` on the training set, (a) the silhouette over k, (b) the training dams in the plane of the first two principal components, colored by `b`, where they form one continuous cloud along which `b` changes gradually, and (c) the LOO σ(Δb) over k |
| `s2_uncertainty_band.png` | Supplementary: parameterization uncertainty in volume, (a) the exponent contribution at Baish and (b) the combined bands versus normalized area, with the regionalized floor and an illustrative fraction set to the median satellite-to-DEM area ratio |
| `s3_dem_error.png` | Supplementary: SRTM vertical-error Monte Carlo volume spread by capacity class, with class medians and 10th to 90th percentile intervals across dams |
| `s4_threshold_analysis.png` | Supplementary: capacity-threshold sweep behind the training cut of the regional exponent |
| `s5_sensitivity.png` | Supplementary: sensitivity of the trusted set to the placement and acceptance constants |

Pipeline runs without the panels step produce no files in `2_results_plots/`. Only the per-dam flood maps under `0_check_dams/` are written, by the workers themselves.

## Flood QC maps (`output/0_check_dams/`)

One PNG per dam with a flood fill, showing the DEM, flood footprint, the snapped river reach in cyan with gold arrows pointing downstream, a red triangle at the dam location, and a dark orange line indicating the chosen dam-wall orientation and length. After regionalization each plot is renamed to reflect the parameter source: `{dam_id}_srtm.png` (direct SRTM fit) or `{dam_id}_regi.png` (regionalized parameters with the multi-feature regression anchor).

## Report (`output/report.md`)

A prose Markdown report written by the report step: domain characterization, methods summary, validation, uncertainty, and the embedded panel figures. Every number in it is recomputed from the released CSVs at generation time.
