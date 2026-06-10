# Changelog

All notable changes to EAVES are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
project adheres to [Semantic Versioning](https://semver.org/).

## [1.1.0] — 2026-06-10

### Fixed

- **Clamped exponents now re-solve $c$ through the SRTM full-pool anchor.**
  The released $b$ is clamped to $[1.1, 2.0]$; previously the raw $c$ was
  kept, so the 39 clamped SRTM-derived curves missed their own full-pool
  volume by factors of 0.004–11. $c$ is now re-solved so that
  $V(A_\mathrm{DEM}) = V_\mathrm{SRTM}$ exactly for every clamped dam
  (`regionalization.py`; `eaves_params.csv` updated for the 39 dams, all
  other rows bit-identical).
- **Sediment budget no longer double-counts delivery.** The
  `sed_yield_t_ha_yr` input is *delivered* yield — Dash et al. (2025,
  Eqs. 2–4) already multiply RUSLE gross erosion by the Boyce (1974)
  delivery ratio at the source — so the additional Vanoni (1975) SDR was
  removed from the budget. `predicted_silt_fraction` and `sediment_risk`
  recomputed (median predicted loss 13.7% → 47.5%; fully-silted count
  44 → 149). Verified at Baish (budget now within ~1.6× of the 2025 sonar
  loss, previously ~10× under) and nationally (implied 32% capacity loss
  matches the figure published with the same yields). `--sediment-sdr`
  remains available as a constant factor for gross-erosion inputs.
- **Panel S3 SRTM band formula.** The SRTM-derived uncertainty tier now
  includes the catalog-capacity term ($\sigma_{\log V_\mathrm{cap}}$),
  matching `validation/v_uncertainty.csv`; it was previously drawn from
  $b_\sigma$ alone and appeared to vanish at the anchor.

### Changed

- Report and data-dictionary text: the catalog-capacity cap on the flood
  fill is disclosed explicitly, the SRTM uncertainty tier is described as
  floored by the catalog-capacity term rather than vanishing at the anchor,
  and the software-versions table was dropped from `report.md`.

## [1.0.1] — 2026-06-01

### Changed

- **Missing construction years are no longer fabricated as 2001.** Dams with
  no catalogue year now carry `construction_year = <NA>` (nullable `Int32`,
  blank in `eaves_summary.csv`) instead of a sentinel 2001. The flat-water
  detector now runs for unknown-year dams as well as pre-2000 dams, so the
  SRTM surface itself decides full vs partial — removing the circular
  assumption that an absent year implied a post-2000, bare-valley capture.
- **Domain characterization keeps unknown-year dams visible.** A
  `n_year_unknown` count and a "Year unknown" row in the era breakdown retain
  them in the population; only age-dependent statistics (era assignment,
  sediment budget) exclude them, since computing those without a build year
  would require fabricating one.

### Notes

- EAV parameters $(c, b)$ are unchanged by this edit (verified bit-identical
  across all 526 KSA dams): the flat-water check returned "bare valley" for
  every missing-year SRTM dam, so each kept `curve_type = full` and the same
  fit path.

### Added

- **`test_curves_helpers.py`** — locks construction-year parsing, including a
  guard that a missing year never returns the old 2001 sentinel.
- **`test_uncertainty.py`** — unit coverage for the uncertainty module
  (`compute_b_sigma`, anchor back-solve, V-band algebra) backing panel S3.
- Extracted `curves._parse_construction_year()` as a directly testable helper
  (pipeline output verified unchanged).

## [1.0.0] — 2026-05-18

First tagged release. Production-ready EAV curve assignment for
SRTM-derived reservoir bathymetry; outputs are now consumed by
downstream simulation (RUSH).

### Added

- **Multi-feature LR anchor** for $A_\mathrm{cap}$ on log-space
  morphometry (`capacity_mcm`, `dam_height_m`, `spillway_height_m`,
  `valley_ratio`, `channel_slope`, `mean_catchment_slope`,
  `upstream_area_km2`). Trained on the regional trusted set, applied to
  every regionalized dam via closed-form back-solve
  $c = V_\mathrm{cap} / A_\mathrm{cap}^b$. LOO accuracy on trusted
  dams: 89% within $2\times$, median absolute error 28%, median bias +7%.
- **`eaves.postprocess.uncertainty` module** and CLI. Propagates the
  LOO-derived $b_\sigma$ to a per-dam V band at half / quarter / tenth
  pool; writes `validation/v_uncertainty.csv`.
- **Supplementary panel S1** — K-means clustering diagnostic on $b$
  (silhouette + LOO $\sigma(\Delta b)$). Backs the report's argument
  for using the global-median $b$.
- **Supplementary panel S2** — capacity-threshold sweep for the
  reliability cut.
- **Supplementary panel S3** — V uncertainty propagation: Baish worked
  example with $\pm b_\sigma$ fan band, plus the universal
  $\sigma(\log_{10} V)$ curve.
- **Software-version block** in `report.md` (numpy, scipy, pandas,
  sklearn, rasterio, geopandas, matplotlib, pyproj, shapely, Python)
  for reproducibility.
- **`run_all.sh`** orchestrator: 5-stage pipeline → validation →
  uncertainty → panels → report. Every panel emits both PNG (300 dpi)
  and vector PDF.
- **Unit tests** for s1/s2 helpers (`_silhouette_curve`,
  `_loo_cluster_sigma`, `_baseline_sigma`, `_chosen_threshold`) — 19
  tests, ~2 s.

### Changed

- **`eaves_params.csv` schema** stabilised on 6 lean columns
  (`dam_id`, `dam_name`, `capacity_mcm`, `c`, `b`, `source`).
  Per-dam confidence metrics moved to `validation/v_uncertainty.csv`.
- **Source label** for regionalized rows renamed
  `regi_derived` → `regi_multi` to reflect the multi-feature anchor.
- **Regression goldens** refreshed after the `upstream_area_km2`
  enrichment fix; 52 fast tests + 1 slow regression test passing.
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
- **Saturated SRTM fits** ($b$ pinned at the 1.10 / 2.00 clip
  boundaries) now correctly demoted to the regional median by the
  tightened quality gates.

### Notes

- One dam (`id_120014`, Shahdan) remains on the log–log fallback
  branch due to `valley_ratio = NaN` from failed topography extraction
  in a narrow steep wadi.
- Bathymetric ground truth in this region is limited to Baish
  (`id_120000`); broader campaigns would be needed to tighten the
  sediment-loss budget beyond the first-order estimate currently
  reported.

[1.1.0]: https://github.com/hyex-research/EAVES/releases/tag/v1.1.0
[1.0.1]: https://github.com/hyex-research/EAVES/releases/tag/v1.0.1
[1.0.0]: https://github.com/hyex-research/EAVES/releases/tag/v1.0.0
