# Method

How EAVES reconstructs elevation-area-volume (EAV) curves from SRTM topography. The full scientific treatment, including validation and uncertainty, is in the accompanying Scientific Data manuscript.

## Dam wall placement

The algorithm searches for a terrain-derived dam wall across the valley at or near the cataloged dam coordinates. Six placement stages are attempted in sequence, from fastest to most exhaustive:

| Stage | Strategy | Description |
| ----- | -------- | ----------- |
| 1 | **Fast path** | Try terrain-derived wall angles at the nominal location |
| 2 | **Upstream walk** | Walk upstream along the valley thalweg and retry at each position |
| 3 | **Quality recovery** | Re-search if the initial fill is geometrically suspect (downstream-skewed or too small) |
| 4 | **River-direction retry** | Shift anchor along the river-network flow vector |
| 5 | **Relaxed alignment** | Allow wall orientations that would normally be rejected by the flow-alignment filter |
| 6 | **Fallback** | Multi-direction flood fill without an explicit wall |

## EAV curve construction

Once the footprint is established, elevation bins (0.5 m intervals) are used to compute area at each level, and cumulative trapezoidal integration yields volume. The fill is capped at the catalog capacity, acting at bin resolution: the curve is truncated at the first bin whose cumulative volume reaches the capacity, so capped fills can overshoot by up to one bin. A two-parameter power law ($V = c \cdot A^b$) is fitted via non-linear least squares, and the released exponent is clamped to $[1.1, 2.0]$ with $c$ re-solved through the recovered full-pool anchor.

## Trusted set and training set

Fits passing the reliability gates (quality grades A-B, $R^2 \geq 0.98$, $0.3 \leq V_\mathrm{SRTM}/V_\mathrm{cap} \leq 5.0$, $n_\mathrm{pixels} \geq 50$, $b$ defined) form the **trusted set**. Of these, only dams built in or after 2000 (verifiably postdating the February 2000 SRTM acquisition) form the **training set** that the regionalization, the exponent spread $b_\sigma$, and the leave-one-out validation are computed on. Pre-2000 and unknown-year dams ship their own SRTM curves (flagged `pre_srtm` / `unknown_year`) but do not train the recipe, because their valley floors may already carry sediment. On the Saudi domain: 322 trusted, 200 training.

## Regionalization

Dams that fail the trusted gates receive parameters from a single closed-form recipe:

- **Exponent $b$**: regional median over the capacity-thresholded training subset (or a multivariate regression on `valley_ratio`, `channel_slope`, `mean_catchment_slope`, `dam_height_m` if its leave-one-out $R^2 \geq 0.25$, which rarely holds for arid catchments).
- **Coefficient $c$**: back-solved as $c = V_\mathrm{cap}/A_\mathrm{cap}^{b}$ from catalog capacity and a multi-feature linear regression that predicts $\log A_\mathrm{cap}$ from seven log-space features: `capacity_mcm`, `dam_height_m`, `spillway_height_m`, `valley_ratio`, `channel_slope`, `mean_catchment_slope`, `upstream_area_km2`. Any feature missing for a given dam is imputed with the training-set median so the regression always returns a finite value.

Leave-one-out cross-validation on the training set quantifies the recipe's accuracy. For the Saudi Arabia deployment: 92% of predictions within a factor of 2 and 99% within a factor of 3 of the SRTM-derived reference, median bias +6%, relative RMSE 47%. See `eaves.postprocess.validation` and panel `p5` for the full per-recipe comparison and the rationale for retiring two earlier candidates (a satellite-anchored recipe and a single-feature log-log regression).

## Post-placement QC

Automated quality gates detect displaced flood centroids and negligible fill volumes, flagging problematic dams for regional parameter assignment rather than propagating unreliable fits.

## Limitations

EAVES reconstructs reservoir geometry from the SRTM surface, not a surveyed bathymetric record. Outputs are a best-effort approximation rather than absolute capacity.

- **Valley-geometry approximation, not bathymetry**: curves follow the SRTM valley surface up to the spillway, not a measured reservoir bottom. They are sensitive to DEM noise (vertical LE90 ~6 m) in the same way the underlying terrain is.
- **Synthetic dam wall**: the wall orientation and length come from a terrain-alignment search at or near the catalog coordinates. It is the best-fit crest for that SRTM patch, not necessarily the engineered as-built structure, and small placement shifts can meaningfully change the reconstructed footprint.
- **SRTM snapshot (February 2000)**: dams built after 2000 get a clean pre-impoundment valley. Dams built earlier carry whatever sediment had accumulated by the acquisition date, so their curves describe the as-of-2000 surface. These dams are flagged (`pre_srtm`, or `unknown_year` when the build year is missing) and excluded from regionalization training.
- **Resolution-limited regimes**: sub-pixel reservoirs (`n_pixels < 30`), narrow valleys (`valley_width_m < 3 x pixel_size`), and shallow depressions (`spillway_height_m < 5 m`) produce curves with elevated uncertainty. See the `uncertainty_flags` column in `eaves_summary.csv` for per-dam tagging.

The full quantitative treatment of these limitations is in the accompanying publication.
