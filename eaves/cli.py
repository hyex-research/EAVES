"""Command-line interface. Exposed as ``python -m eaves`` or ``python run_eaves.py``."""

from __future__ import annotations

import argparse
import os
import time
import multiprocessing as mp
from functools import partial

import numpy as np
import pandas as pd
import geopandas as gpd
from tqdm import tqdm

import eaves.config as _cfg
from .config import configure
from .preprocess import ensure_inputs
from .settings import load_settings
from .pipeline.workers import _worker_indexed
from .postprocess.regionalization import assign_quality, run_regionalization
from .postprocess.reliability import add_uncertainty_flags, print_flag_tally
from .postprocess.external_data import add_sedimentation_columns
from .postprocess.panels import make_panels


def _load_translit_map():
    """Build dam_id (lowercase) -> dam_name (Latin) from the dam catalogue CSV."""
    mapping = {}
    if os.path.isfile(_cfg.DAMS_CSV):
        df = pd.read_csv(_cfg.DAMS_CSV)
        for _, row in df.iterrows():
            did = str(row["dam_id"]).strip()
            dname = str(row["dam_name"]).strip()
            mapping[did] = dname
    return mapping


def _build_dam_data_list(gdf_dams, translit_map):
    """Convert GeoDataFrame rows into serialisable dicts for workers."""
    dam_data_list = []
    for idx in range(len(gdf_dams)):
        dam = gdf_dams.iloc[idx]
        dam_lat = pd.to_numeric(dam.get("latitude"), errors="coerce")
        dam_lon = pd.to_numeric(dam.get("longitude"), errors="coerce")
        if not np.isfinite(dam_lat) or not np.isfinite(dam_lon):
            dam_lat = dam.geometry.y
            dam_lon = dam.geometry.x

        dam_dict = {col: dam[col] for col in gdf_dams.columns if col != "geometry"}
        dam_dict["_lat"] = dam_lat
        dam_dict["_lon"] = dam_lon
        dam_dict["_snapped_lat"] = dam.geometry.y
        dam_dict["_snapped_lon"] = dam.geometry.x

        gj_id = str(dam.get("dam_id") or dam.get("id") or "").strip()
        dam_id = gj_id.lower() if gj_id else ""
        dam_dict["dam_id"] = dam_id
        dam_dict["dam_name_latin"] = translit_map.get(dam_id, "")
        dam_data_list.append(dam_dict)
    return dam_data_list


def _run_plots_and_regionalization(summary_df, failures, dam_data_list):
    """Run regionalization and rename per-dam flood plots by source."""
    run_regionalization(summary_df, failures, dam_data_list)
    _rename_flood_plots_by_source()


_SOURCE_SUFFIX = {
    "srtm_derived": "srtm",
    "regr_derived": "regr",
    "regi_derived": "regi",
}


def _rename_flood_plots_by_source():
    """Rename ``{dam_id}_flood.png`` -> ``{dam_id}_{srtm|regr|regi}.png``
    based on the ``source`` column of ``eaves_params.csv``.
    """
    params_path = os.path.join(_cfg.CSV_DIR, "eaves_params.csv")
    if not os.path.isfile(params_path):
        return
    params_df = pd.read_csv(params_path)
    for _, row in params_df.iterrows():
        dam_id = str(row["dam_id"]).strip()
        suffix = _SOURCE_SUFFIX.get(str(row.get("source", "")).strip())
        if not dam_id or suffix is None:
            continue
        src = os.path.join(_cfg.FLOOD_DIR, f"{dam_id}_flood.png")
        dst = os.path.join(_cfg.FLOOD_DIR, f"{dam_id}_{suffix}.png")
        if os.path.isfile(src):
            os.replace(src, dst)


def main():
    t0 = time.time()

    try:
        mp.set_start_method("fork", force=True)
    except RuntimeError:
        pass

    parser = argparse.ArgumentParser(
        description="E\u2013A\u2013V curves and flood maps from SRTM (parallel over dams).",
    )
    parser.add_argument(
        "--only",
        nargs="+",
        metavar="DAM_ID",
        help="Process only these dam_id values (e.g. --only id_20017 id_120000). "
        "Comma-separated also works: --only \"id_20017,id_120000\". "
        "Merges into eaves_summary.csv / failed_dams.csv instead of replacing the full set.",
    )
    parser.add_argument(
        "--plot-only",
        action="store_true",
        help="Skip EAV curve calculation; load existing results from CSV and "
        "regenerate all analysis plots and regionalization only.",
    )
    parser.add_argument(
        "--rerun",
        action="store_true",
        help="Force re-calculation even when --plot-only is also specified.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Override OUTPUT_DIR: root for 0_check_dams/, 1_results_csv/, 2_results_plots/.",
    )
    parser.add_argument(
        "--srtm-dir",
        default=None,
        help="Override SRTM_DIR: folder with unzipped .hgt tiles.",
    )
    parser.add_argument(
        "--rebuild-domain",
        action="store_true",
        help="Force re-run of the preprocessing step (MERIT clip + segment split + dam snap).",
    )
    parser.add_argument(
        "--settings",
        default=None,
        help="Path to a settings JSON file. Loaded BEFORE --output-dir/--srtm-dir "
        "overrides, so CLI flags win on conflict.",
    )
    parser.add_argument(
        "--panels",
        action="store_true",
        help="After the run completes, render the EAVES Data Descriptor "
        "panel figures (1-3) into <OUTPUT_DIR>/2_results_plots. Compatible "
        "with --plot-only.",
    )
    parser.add_argument(
        "--panels-only",
        action="store_true",
        help="Skip the EAV pipeline entirely; just regenerate the panel "
        "figures from the existing EAVES outputs. Implies a settings file "
        "(or prior --output-dir) so the CSV paths are known.",
    )
    args = parser.parse_args()

    if args.settings:
        load_settings(args.settings)
        print(f"[settings] Loaded {args.settings}")

    if args.output_dir or args.srtm_dir:
        configure(
            output_dir=args.output_dir,
            srtm_dir=args.srtm_dir,
        )

    only_ids = None
    if args.only:
        expanded = []
        for chunk in args.only:
            c = str(chunk).strip()
            if not c:
                continue
            if "," in c or ";" in c:
                for part in c.replace(";", ",").split(","):
                    t = part.strip()
                    if t:
                        expanded.append(t)
            else:
                expanded.append(c)
        only_ids = {x for x in expanded if x}

    os.makedirs(_cfg.EAV_DIR, exist_ok=True)
    os.makedirs(_cfg.CSV_DIR, exist_ok=True)
    os.makedirs(_cfg.PLOT_DIR, exist_ok=True)
    os.makedirs(_cfg.FLOOD_DIR, exist_ok=True)

    # ------------------------------------------------------------------
    # --panels-only: short-circuit; skip the pipeline entirely.
    # ------------------------------------------------------------------
    if args.panels_only:
        print("--panels-only: rendering panel figures from existing outputs.")
        make_panels()
        elapsed = time.time() - t0
        print("--------------------------------")
        print(f"TOTAL TIME: {time.strftime('%H:%M:%S', time.gmtime(elapsed))}")
        print("--------------------------------")
        return

    translit_map = _load_translit_map()

    rivers_path, dams_path = ensure_inputs(rebuild=args.rebuild_domain)
    gdf_dams = gpd.read_file(dams_path)

    # ------------------------------------------------------------------
    # --plot-only: reload existing CSVs and skip to plots/regionalization
    # ------------------------------------------------------------------
    summary_path = os.path.join(_cfg.CSV_DIR, "eaves_summary.csv")
    fail_path = os.path.join(_cfg.CSV_DIR, "failed_dams.csv")

    if args.plot_only and not args.rerun:
        if not os.path.isfile(summary_path):
            print("[ERROR] --plot-only requested but eaves_summary.csv "
                  "not found. Run without --plot-only first.")
            return

        print("--plot-only: loading existing results...")
        summary_df = pd.read_csv(summary_path)
        if "quality" not in summary_df.columns and len(summary_df) > 0:
            if "srtm_max_vol_mcm" not in summary_df.columns:
                max_vols = []
                for _, row in summary_df.iterrows():
                    eav_p = os.path.join(_cfg.EAV_DIR, f"{row['dam_id']}_eav.csv")
                    if os.path.exists(eav_p):
                        eav = pd.read_csv(eav_p)
                        max_vols.append(eav["volume_m3"].max() / 1e6)
                    else:
                        max_vols.append(np.nan)
                summary_df["srtm_max_vol_mcm"] = max_vols
            if "vol_ratio" not in summary_df.columns:
                summary_df["vol_ratio"] = (
                    summary_df["srtm_max_vol_mcm"] / summary_df["capacity_mcm"]
                )
            if "z_range" not in summary_df.columns:
                summary_df["z_range"] = summary_df["z_max"] - summary_df["z_min"]
            if "z_range_ratio" not in summary_df.columns:
                summary_df["z_range_ratio"] = (
                    summary_df["z_range"]
                    / summary_df["spillway_height_m"].replace(0, np.nan)
                )
            summary_df["quality"] = summary_df.apply(assign_quality, axis=1)

        if len(summary_df) > 0:
            add_uncertainty_flags(summary_df)
            summary_df = add_sedimentation_columns(summary_df, getattr(_cfg, "SEDIMENTATION_DIR", None))
            summary_df.to_csv(summary_path, index=False)

        failures = []
        if os.path.isfile(fail_path):
            fail_df = pd.read_csv(fail_path)
            failures = fail_df.to_dict("records")

        dam_data_list = _build_dam_data_list(gdf_dams, translit_map)

        print(f"  Loaded {len(summary_df)} succeeded, {len(failures)} failed dams.\n")
        _run_plots_and_regionalization(summary_df, failures, dam_data_list)

        if args.panels:
            make_panels()

        elapsed = time.time() - t0
        print("--------------------------------")
        print(f"TOTAL TIME: {time.strftime('%H:%M:%S', time.gmtime(elapsed))}")
        print("--------------------------------")
        return

    # ------------------------------------------------------------------
    # Normal run: compute EAV curves
    # ------------------------------------------------------------------
    if only_ids is not None:
        id_col = "dam_id" if "dam_id" in gdf_dams.columns else "id"
        id_series = gdf_dams[id_col].astype(str).str.strip().str.lower()
        mask = id_series.isin(only_ids)
        gdf_dams = gdf_dams[mask].copy()
        found = set(id_series[mask].unique())
        missing = sorted(only_ids - found)
        if missing:
            print(f"[WARN] dam_id not found in geojson (skipped): {missing}")
        if len(gdf_dams) == 0:
            print("No dams to process after --only filter; exiting.")
            return

    if os.path.isfile(rivers_path):
        gdf_rivers = gpd.read_file(rivers_path)
    else:
        gdf_rivers = None
        print(f"[WARN] River network not found at {rivers_path}, using DEM gradient only.")

    n_dams = len(gdf_dams)
    if only_ids is not None:
        print(f"Subset run: {n_dams} dam(s) matching --only.\n")
    else:
        print(f"Found {n_dams} dams to process.\n")

    dam_data_list = _build_dam_data_list(gdf_dams, translit_map)

    gdf_rivers_data = None
    if gdf_rivers is not None:
        gdf_rivers_data = gdf_rivers.__geo_interface__["features"]

    n_workers = max(1, mp.cpu_count())
    print(f"Processing {n_dams} dams using {n_workers} workers...")

    indexed_worker = partial(_worker_indexed, gdf_rivers_data=gdf_rivers_data)
    indexed_tasks = list(enumerate(dam_data_list))

    summaries = []
    failures = []
    results = [None] * n_dams

    with mp.Pool(n_workers) as pool:
        for idx, result, failure in tqdm(
            pool.imap_unordered(indexed_worker, indexed_tasks),
            total=n_dams,
            desc=f"Dams ({n_workers} workers)",
            unit="dam",
        ):
            results[idx] = (result, failure)

    for dam_dict, (result, failure) in zip(dam_data_list, results):
        dam_id = dam_dict.get("dam_id", "")
        if failure is not None:
            failure["dam_id"] = dam_id
            failure["dam_name"] = dam_dict.get("dam_name_latin", "")
            failures.append(failure)
            if dam_id:
                eav_path = os.path.join(_cfg.EAV_DIR, f"{dam_id}_eav.csv")
                flood_path = os.path.join(_cfg.FLOOD_DIR, f"{dam_id}_flood.png")
                for p in (eav_path, flood_path):
                    try:
                        os.remove(p)
                    except FileNotFoundError:
                        pass
        elif result is not None:
            summaries.append({
                "dam_id": dam_id,
                "dam_name": dam_dict.get("dam_name_latin", ""),
                "construction_year": result["construction_year"],
                "dam_height_m": result["dam_height_m"],
                "spillway_height_m": result["spillway_height_m"],
                "capacity_mcm": result["capacity_mcm"],
                "curve_type": result["curve_type"],
                "srtm_water_level_m": result["srtm_water_level_m"],
                "coverage_fraction": result["coverage_fraction"],
                "z_min": result["z_min"],
                "z_max": result["z_max"],
                "footprint_area_km2": result["footprint_area_km2"],
                "c": result["c"],
                "b": result["b"],
                "r_squared": result["r_squared"],
                "n_pixels": result["n_pixels"],
                "void_fraction": result["void_fraction"],
                "capped": result["capped"],
                "placement_upstream_shift_m": result.get("placement_upstream_shift_m", np.nan),
                "placement_method": result.get("placement_method", ""),
                "valley_width_m": result.get("valley_width_m", np.nan),
                "valley_ratio": result.get("valley_ratio", np.nan),
                "channel_slope": result.get("channel_slope", np.nan),
                "mean_catchment_slope": result.get("mean_catchment_slope", np.nan),
                "lat": dam_dict["_lat"],
                "lon": dam_dict["_lon"],
            })

    summary_df = pd.DataFrame(summaries)

    if len(summary_df) > 0:
        max_vols = []
        for _, row in summary_df.iterrows():
            eav_path = os.path.join(_cfg.EAV_DIR, f"{row['dam_id']}_eav.csv")
            if os.path.exists(eav_path):
                eav = pd.read_csv(eav_path)
                max_vols.append(eav["volume_m3"].max() / 1e6)
            else:
                max_vols.append(np.nan)
        summary_df["srtm_max_vol_mcm"] = max_vols
        summary_df["vol_ratio"] = summary_df["srtm_max_vol_mcm"] / summary_df["capacity_mcm"]
        summary_df["z_range"] = summary_df["z_max"] - summary_df["z_min"]
        summary_df["z_range_ratio"] = (
            summary_df["z_range"] / summary_df["spillway_height_m"].replace(0, np.nan)
        )
        summary_df["quality"] = summary_df.apply(assign_quality, axis=1)
        add_uncertainty_flags(summary_df)
        summary_df = add_sedimentation_columns(summary_df, getattr(_cfg, "SEDIMENTATION_DIR", None))

    processed_ids = {str(d.get("dam_id", "")).strip() for d in dam_data_list}
    processed_ids.discard("")
    if only_ids is not None and os.path.isfile(summary_path):
        old_sum = pd.read_csv(summary_path)
        old_sum = old_sum[~old_sum["dam_id"].astype(str).str.strip().isin(processed_ids)]
        if len(summary_df) > 0:
            summary_df = pd.concat([old_sum, summary_df], ignore_index=True)
        else:
            summary_df = old_sum

    summary_df.to_csv(summary_path, index=False)
    print(f"\nSummary saved: {len(summaries)} dams succeeded.")
    if len(summary_df) > 0:
        qcounts = summary_df["quality"].value_counts().sort_index()
        for q, n in qcounts.items():
            print(f"  Quality {q}: {n} dams")
        if "capped" in summary_df.columns:
            n_capped = summary_df["capped"].sum()
            print(f"  Capacity-capped: {n_capped} dams")
        print_flag_tally(summary_df)

    for s in summaries:
        if np.isnan(s.get("b", np.nan)) or np.isnan(s.get("c", np.nan)):
            failures.append({
                "dam_id": s["dam_id"],
                "dam_name": s.get("dam_name", ""),
                "reason": "fit_failed",
                "detail": f"Power-law fit returned NaN (n_pixels={s['n_pixels']})",
            })

    if failures:
        fail_df = pd.DataFrame(failures)
    else:
        fail_df = pd.DataFrame(columns=["dam_id", "dam_name", "reason", "detail"])

    if only_ids is not None and os.path.isfile(fail_path):
        old_fail = pd.read_csv(fail_path)
        if len(old_fail) > 0 and "dam_id" in old_fail.columns:
            old_fail = old_fail[
                ~old_fail["dam_id"].astype(str).str.strip().isin(processed_ids)
            ]
        else:
            old_fail = pd.DataFrame(columns=["dam_id", "dam_name", "reason", "detail"])
        if len(fail_df) > 0:
            fail_df = pd.concat([old_fail, fail_df], ignore_index=True)
        else:
            fail_df = old_fail

    fail_df.to_csv(fail_path, index=False)
    print(f"Failed/flagged dams: {len(failures)}")

    _run_plots_and_regionalization(summary_df, failures, dam_data_list)

    if args.panels:
        make_panels()

    for src in _cfg._srtm_cache.values():
        try:
            src.close()
        except Exception:
            pass

    elapsed = time.time() - t0
    print("--------------------------------")
    print(f"TOTAL TIME: {time.strftime('%H:%M:%S', time.gmtime(elapsed))}")
    print("--------------------------------")
