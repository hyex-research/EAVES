# Outputs

Everything a run writes under `region/<country>/output/`. Column-level definitions, units, and controlled vocabularies for every released file live in the `DATA_DICTIONARY.md` shipped next to the CSVs.

## CSV files (`output/1_results_csv/`)

| File | Description |
| ---- | ----------- |
| `eaves_params.csv` | The headline product. Lean per-dam parameter table: six columns (`dam_id`, `dam_name`, `capacity_mcm`, `c`, `b`, `source`) with no NaN cells. `source` is `srtm_derived` (DEM-fit) or `regi_multi` (multi-feature LR anchor). Sorted by `dam_id`. The 1-sigma uncertainty on `b` is a region-level scalar stored in `validation/v_uncertainty.csv` and `domain_characterization.csv`, not duplicated per row. |
| `eaves_summary.csv` | One row per successfully processed dam: fitted `c`, `b`, `r_squared`, footprint area, quality grade, placement method, reliability flags (`uncertainty_flags`, `uncertainty_score`), `upstream_area_km2`, and, when `sedimentation_dir` is provided, `sed_yield_t_ha_yr` (delivered yield), `owe_mm_year`, plus the derived `predicted_silt_fraction` and `sediment_risk`. Sorted by `dam_id`. |
| `failed_dams.csv` | Dams failing wall placement, fill acceptance, or the power-law fit, with failure reason, catalog attributes (including `construction_year`), and the topographic features attached at failure time so each row is self-contained for regionalization. Sorted by `dam_id`. |
| `threshold_analysis.csv` | Capacity-threshold sweep behind the reliability cut. |
| `domain_characterization.csv` | Key/value table of the domain statistics surfaced in `report.md`. |
| `validation/regionalization_loo.csv` | Per-dam LOO residuals of every regionalization recipe, evaluated on the training dams. |
| `validation/dem_vs_sat_area.csv` | Per-dam DEM full-pool area versus satellite-P95 area (diagnostic only). |
| `validation/b_clustering_diagnostic.csv` | Silhouette and LOO sigma(delta b) over k for the raw-morphometry feature set, written by the s1 panel. Backs supplementary figure S1 and the global-median choice for `b`. |
| `validation/v_uncertainty.csv` | Per-dam V uncertainty band at half, quarter, and tenth pool (log10 units and +%/-% bands), combining the geometric `b_sigma` term, the catalog-capacity term, and, for regionalized dams, the predicted-area term. Written by `eaves.postprocess.uncertainty`. Backs supplementary figure S3. |
| `validation/goodness_of_fit.csv` | Deployed-direction fractional volume residuals per fit, with `is_trusted` and `in_training` membership columns. |
| `validation/acap_regression_diagnostics.csv` | Collinearity (VIF, condition number) and incremental LOO skill of the seven anchor features (long-form table). |
| `validation/sensitivity_sweep.csv` | Trusted-set size, grade counts, and median trusted `b` as each swept placement constant is perturbed by 20-30%. Written only by the opt-in `--sensitivity` step (see [usage.md](usage.md)). |
| `validation/dem_error_montecarlo.csv` | Per-dam spread of recovered volume and `b` across SRTM vertical-error realizations. Written only by the opt-in `--dem-mc` step (see [usage.md](usage.md)). |
| `eav_tables/{dam_id}_eav.csv` | Per-dam tabulated (z, A, V) on half-integer-snapped 0.5 m elevation bins. |
| `DATA_DICTIONARY.md` | Definitions, units, and controlled vocabularies for every released column. |

## Panel figures (`output/2_results_plots/`, written by the panels step)

Every panel is emitted as both a 300-dpi PNG (embedded in `report.md`) and a vector PDF with the same stem (for journal submission).

| File | Description |
| ---- | ----------- |
| `p1_domain_flowchart.png` | Domain map (a) + pipeline flowchart (b) |
| `p2_placement.png` | Three worked placement examples illustrating the six-stage cascade |
| `p3_baish_example.png` | Worked example for the bathymetry-cross-referenced reservoir (Baish) + the trusted-set exponent distribution |
| `p4_comparison.png` | Cross-reference against sonar bathymetry (Baish) and GRDL (3 reference dams). Methodologically distinct datasets, not validation in the strict sense |
| `p5_regionalization_validation.png` | LOO validation of the shipped regionalization recipe on the training dams (the formal internal validation) |
| `s1_b_clustering_silhouette.png` | Supplementary: K-means clustering diagnostic for `b` on the training set. Justifies the global-median choice |
| `s2_threshold_analysis.png` | Supplementary: capacity-threshold sweep behind the reliability cut |
| `s3_uncertainty_band.png` | Supplementary: the per-dam V uncertainty band. (a) Worked example on Baish; (b) the two band tiers versus normalized area, with the catalog-capacity floor and the typical operational fill level marked |
| `s4_dem_error.png` | Supplementary: SRTM vertical-error Monte-Carlo volume spread by size class |
| `s5_sensitivity.png` | Supplementary: placement-constant sensitivity sweep |

Pipeline runs without the panels step produce no files in `2_results_plots/`; only per-dam flood maps under `0_check_dams/` are written by the workers themselves.

## Flood QC maps (`output/0_check_dams/`)

One PNG per dam showing the DEM, flood footprint, river network overlay, a red triangle at the dam location, and a darkorange line indicating the chosen dam-wall orientation and length. After regionalization each plot is renamed to reflect the parameter source: `{dam_id}_srtm.png` (direct SRTM fit) or `{dam_id}_regi.png` (multi-feature LR anchor).

## Report (`output/report.md`)

A prose Markdown report regenerated on every `run_all.sh` invocation: domain characterization, methods summary, validation, uncertainty, and the embedded panel figures. Every number in it is recomputed from the released CSVs at generation time.
