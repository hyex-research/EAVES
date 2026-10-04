# Data dependencies

EAVES runs standalone. All preprocessing (country clip, segment split, dam snap) happens inside the package. Preprocessing drops zero-length MERIT reaches, keeps every reach that touches the country together with every reach that drains into it, and retains the part of that network within 0.3° of a dam. A reach longer than `max_seg_len_m` is cut into equal parts along the channel, and each part carries an equal share of the reach length and unit-catchment area. The settings file points to the external rasters and shapefiles. Licensed or bulky data is not redistributed.

## Included in this repository

- 15-dam example fixture (`test/fixture/`): dams CSV subset, water-extent time series, sedimentation and evaporation inputs, preprocessing cache, and SRTM GL1 elevation clipped to the windows of the 15 dams (public domain data from NASA and USGS)
- GRDL reference EAV curves per region (`region/<country>/input/grdl/`, user-provided)

## External (referenced by path in the settings file)

| Dataset | Source | Purpose |
| ------- | ------ | ------- |
| **SRTM GL1 v003** (1 arc-second, ~30 m) | [NASA/USGS SRTMGL1](https://lpdaac.usgs.gov/products/srtmgl1v003/), tiles mirrored at [ESA STEP](https://step.esa.int/auxdata/dem/SRTMGL1/) | Valley topography, acquired February 2000 |
| **MERIT-Basins v0.7** (pfaf_level_1), the vector reaches and unit catchments of MERIT Hydro | [Lin et al. 2019](https://doi.org/10.1029/2019WR025287), built on MERIT Hydro, [Yamazaki et al. 2019](https://hydro.iis.u-tokyo.ac.jp/~yamadai/MERIT_Hydro/) | River network + basins (clipped during preprocessing to the country and the reaches that drain into it) |
| **Natural Earth admin boundaries** (10 m, lakes-cut) | [naturalearthdata.com](https://www.naturalearthdata.com/downloads/10m-cultural-vectors/) | Country polygon for clipping MERIT |
| **Dam catalog** (e.g. `<country>_dams.csv`) | User-provided | Dam locations, attributes, capacities |
| **Filtered satellite water extent** | User-provided | Empirical area estimates for the regionalization diagnostics |
| **GRDL reference curves** (optional) | [Hao et al. 2024](https://doi.org/10.1029/2023WR035781) | Deep-learning global area-storage-depth reference set used in the cross-reference panel (`p4_comparison.png`). Methodologically distinct from EAVES, not direct validation |
| **Sonar bathymetry** (optional) | Field survey | Cross-reference anchor for one or more reservoirs. Measures the current operational reservoir floor, distinct from the topography EAVES integrates |
| **Sedimentation and evaporation** (optional, KSA-specific) | [Dash et al. 2025](https://doi.org/10.1016/j.jenvman.2025.127199) | Per-dam delivered sediment yield (t/ha/yr), upstream catchment area (km²), and open-water evaporation (mm/yr), merged into `eaves_summary.csv` when `sedimentation_dir` is set |

## Note on SRTM data

EAVES uses `.hgt` tiles from the Shuttle Radar Topography Mission Global 1 arc-second dataset (SRTMGL1 v003), acquired in February 2000. Tiles can be downloaded from [USGS EarthExplorer](https://earthexplorer.usgs.gov/) or the [ESA STEP mirror](https://step.esa.int/auxdata/dem/SRTMGL1/). The Saudi dam catalog used in this study is not publicly available in raw form. The per-dam attributes EAVES consumes are included in the open data release.
