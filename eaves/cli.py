"""Command-line interface, exposed as ``eaves`` and ``python -m eaves``.

* ``eaves --settings <settings.json>`` -- run the pipeline: preprocessing (river clip + dam snap), the per-dam worker pool, the summary/params/failure CSVs and regionalization
* ``eaves info <settings.json>``       -- print the resolved configuration and output layout as JSON (read-only)
* ``eaves mcp``                        -- serve read-only tools over the Model Context Protocol

``--only`` narrows the run to listed dams, ``--panels`` adds the publication
panels, ``--plot-only`` and ``--panels-only`` re-enter from existing outputs,
and ``--rebuild-domain`` rebuilds the preprocessing cache. The validation,
uncertainty, panels and report steps run after the pipeline as
``python -m eaves.postprocess.<step> --settings <settings.json>``, in the
order of ``run_all.sh``.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import sys
import time

import geopandas as gpd
import numpy as np
import pandas as pd
from tqdm import tqdm

import eaves.config as _cfg

from .agent import info as agent_info
from .agent import mcp_server as agent_mcp
from .config import configure
from .pipeline.workers import _init_worker, _worker_indexed
from .postprocess.external_data import add_sedimentation_columns
from .postprocess.panels import make_panels
from .postprocess.regionalization import assign_quality, run_regionalization
from .postprocess.reliability import add_uncertainty_flags, print_flag_tally
from .preprocess import ensure_inputs
from .settings import load_settings
from .utils import dams_with_fill, round_released_columns


def _load_translit_map():
    """Build dam_id (lowercase) -> dam_name (Latin) from the dam catalog CSV."""
    mapping = {}
    if os.path.isfile(_cfg.DAMS_CSV):
        df = pd.read_csv(_cfg.DAMS_CSV)
        for _, row in df.iterrows():
            did = str(row["dam_id"]).strip()
            dname = str(row["dam_name"]).strip()
            mapping[did] = dname
    return mapping


def _load_upstream_area_lookup() -> dict:
    """Build a ``{dam_id: upstream_area_km2}`` map from the catchment table
    (``sedimentation_yield.csv``) once, so every worker can attach the
    column to its failure record without re-reading the CSV.
    """
    sed_dir = getattr(_cfg, "SEDIMENTATION_DIR", None)
    if not sed_dir:
        return {}
    p = os.path.join(sed_dir, "sedimentation_yield.csv")
    if not os.path.isfile(p):
        return {}
    try:
        df = pd.read_csv(p)
    except Exception:
        return {}
    if not {"dam_id", "area_km2"}.issubset(df.columns):
        return {}
    return dict(zip(df["dam_id"].astype(str), df["area_km2"]))


def _build_dam_data_list(gdf_dams, translit_map):
    """Convert GeoDataFrame rows into serializable dicts for workers."""
    upstream_lookup = _load_upstream_area_lookup()
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
        dam_dict["upstream_area_km2"] = upstream_lookup.get(dam_id, np.nan)
        dam_data_list.append(dam_dict)
    return dam_data_list


_UNFILLED_KEYS = (
    "dam_name", "construction_year", "dam_height_m", "spillway_height_m", "dam_length_m", "capacity_mcm",
    "valley_width_m", "valley_ratio", "channel_slope", "mean_catchment_slope", "upstream_area_km2",
)
_SUMMARY_INT_COLUMNS = {"construction_year": "Int32", "n_pixels": "Int64", "uncertainty_score": "Int64"}


def _append_dams_without_fill(summary_df, failures):
    """Add one summary row per failed dam that has no flood fill.

    The row carries the catalog attributes, the coordinates and the
    topographic features of the failure record. The cells of the fill and of
    the fit stay empty, so the summary holds every dam of ``eaves_params.csv``.
    """
    have = set(summary_df["dam_id"]) if "dam_id" in summary_df.columns else set()
    rows = []
    for f in failures:
        dam_id = f.get("dam_id", "")
        if not dam_id or dam_id in have:
            continue
        have.add(dam_id)
        row = {"dam_id": dam_id}
        row.update({key: f.get(key, np.nan) for key in _UNFILLED_KEYS})
        row["lat"] = f.get("latitude", np.nan)
        row["lon"] = f.get("longitude", np.nan)
        rows.append(row)
    if not rows:
        return summary_df
    if len(summary_df.columns) == 0:
        return pd.DataFrame(rows)
    return pd.concat([summary_df, pd.DataFrame(rows)], ignore_index=True)


def _finalize_summary(summary_df):
    """Sort the summary by dam, hold its counts as integers and round it to the released precision.

    The empty cells of a dam without a flood fill turn a plain integer column
    into floats, so the year, the pixel count and the flag count are nullable
    integers. Known values stay integral and unknown ones stay blank.
    """
    summary_df = summary_df.sort_values("dam_id", kind="stable").reset_index(drop=True)
    for column, dtype in _SUMMARY_INT_COLUMNS.items():
        if column in summary_df.columns:
            summary_df[column] = pd.to_numeric(summary_df[column], errors="coerce").round().astype(dtype)
    return round_released_columns(summary_df)


def _run_plots_and_regionalization(summary_df):
    """Run regionalization on the summary of every dam and rename per-dam flood plots by source."""
    run_regionalization(summary_df)
    _rename_flood_plots_by_source()


_SOURCE_SUFFIX = {
    "srtm_derived": "srtm",
    "regi_multi":   "regi",
}


def _rename_flood_plots_by_source():
    """Rename ``{dam_id}_flood.png`` -> ``{dam_id}_{srtm|regi}.png``
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
            # Removes the plot of the dam under any other source suffix
            for other in set(_SOURCE_SUFFIX.values()) - {suffix}:
                stale = os.path.join(_cfg.FLOOD_DIR, f"{dam_id}_{other}.png")
                if os.path.isfile(stale):
                    os.remove(stale)


def build_parser() -> argparse.ArgumentParser:
    """Build the parser of the pipeline flags and the read-only commands, exposed for testing."""
    parser = argparse.ArgumentParser(
        description="Elevation-area-volume curves and flood maps from SRTM, in parallel over dams.",
    )
    parser.add_argument(
        "--only",
        nargs="+",
        metavar="DAM_ID",
        help="Process only these dam_id values (e.g. --only id_020017 id_120000). "
        "Comma-separated also works: --only \"id_020017,id_120000\". "
        "Merges into eaves_summary.csv / failed_dams.csv instead of replacing the full set.",
    )
    parser.add_argument(
        "--plot-only",
        action="store_true",
        help="Skip the per-dam computation, reload the existing tables, rerun the "
        "regionalization and rename the check maps by source.",
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
        help="Force re-run of the preprocessing step (MERIT-Basins clip + reach subdivision + dam snap).",
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
        help="After the run completes, render the main panels p1 to p6 and the "
        "supplementary panels s1 to s5 into <OUTPUT_DIR>/2_results_plots. "
        "Compatible with --plot-only.",
    )
    parser.add_argument(
        "--panels-only",
        action="store_true",
        help="Skip the EAV pipeline entirely and regenerate the panel "
        "figures from the existing EAVES outputs. Implies a settings file "
        "(or prior --output-dir) so the CSV paths are known.",
    )

    sub = parser.add_subparsers(
        dest="command",
        metavar="COMMAND",
        help="Read-only command, info or mcp. Without one the pipeline runs with the flags above.",
    )
    p_info = sub.add_parser(
        "info",
        help="Print the resolved configuration and output layout of a settings file as JSON.",
        description="Load and validate a settings file, then print as JSON the settings file, "
        "the resolved settings, the layout of the output tree and the defaults of eaves.config "
        "for the keys the file leaves out. Read-only, runs nothing.",
    )
    p_info.add_argument("settings", help="Path to the settings JSON file.")
    sub.add_parser(
        "mcp",
        help="Serve read-only EAVES tools over the Model Context Protocol (stdio).",
        description="Start the read-only MCP server over stdio, so LLM agent clients can query "
        "configurations, runs and results as tools (agents_brief, pipeline_steps, "
        "resolved_config, run_status, run_outputs, domain_characterization, dam_results). "
        "Runs nothing, execution stays with the CLI. Requires the optional 'mcp' package "
        "(pip install -e \".[mcp]\").",
    )
    return parser


def cmd_info(args: argparse.Namespace) -> int:
    """Print the resolved configuration and output layout of a settings file as JSON, and return 1 when the file is missing or invalid."""
    settings_path = os.path.abspath(args.settings)
    if not os.path.isfile(settings_path):
        print(f"Error: settings file not found: {settings_path}", file=sys.stderr)
        return 1
    try:
        payload = agent_info.resolved_config(settings_path)
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"Error: invalid settings in {settings_path}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(payload, indent=2, default=str))
    return 0


def cmd_mcp() -> int:
    """Serve the read-only MCP tool set over stdio."""
    return agent_mcp.main()


def main(argv: list[str] | None = None):
    """Run the pipeline from the command line, or a read-only command and return its exit code."""
    args = build_parser().parse_args(argv)
    if args.command == "info":
        return cmd_info(args)
    if args.command == "mcp":
        return cmd_mcp()

    t0 = time.time()

    try:
        mp.set_start_method("fork", force=True)
    except RuntimeError:
        pass

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
    os.makedirs(_cfg.FLOOD_DIR, exist_ok=True)
    # PLOT_DIR is created lazily by the panels step and is absent without --panels

    # ---- Panels-only run: renders panels from existing outputs and exits ----
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
    if "closest_segment_id" not in gdf_dams.columns:
        raise SystemExit("The cached dam snap lacks the nearest reach part. Run again with --rebuild-domain.")

    # ---- Plot-only run: reloads the existing tables and reruns the regionalization ----
    summary_path = os.path.join(_cfg.CSV_DIR, "eaves_summary.csv")
    fail_path = os.path.join(_cfg.CSV_DIR, "failed_dams.csv")

    if args.plot_only and not args.rerun:
        if not os.path.isfile(summary_path):
            print("[ERROR] --plot-only requested but eaves_summary.csv "
                  "not found. Run without --plot-only first.")
            return

        print("--plot-only: loading existing results...")
        summary_all = pd.read_csv(summary_path)
        summary_df = dams_with_fill(summary_all)
        unfilled_df = summary_all[~summary_all["dam_id"].isin(summary_df["dam_id"])]
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

        failures = []
        if os.path.isfile(fail_path):
            fail_df = pd.read_csv(fail_path)
            failures = fail_df.to_dict("records")

        if len(summary_df) > 0:
            add_uncertainty_flags(summary_df)
        # The dams without a flood fill keep their rows, and a failed dam that has none yet gains one
        summary_all = _append_dams_without_fill(pd.concat([summary_df, unfilled_df], ignore_index=True), failures)
        if len(summary_all) > 0:
            summary_all = add_sedimentation_columns(summary_all, getattr(_cfg, "SEDIMENTATION_DIR", None))
            summary_all = _finalize_summary(summary_all)
            summary_all.to_csv(summary_path, index=False)
            summary_df = dams_with_fill(summary_all)

        print(f"  Loaded {len(summary_df)} succeeded, {len(failures)} failed dams.\n")
        _run_plots_and_regionalization(summary_all)

        if args.panels:
            make_panels()

        elapsed = time.time() - t0
        print("--------------------------------")
        print(f"TOTAL TIME: {time.strftime('%H:%M:%S', time.gmtime(elapsed))}")
        print("--------------------------------")
        return

    # ---- Normal run: computes EAV curves ----
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
            print("No dams to process after --only filter, exiting.")
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

    # Orders the dams by storage capacity, largest first
    indexed_tasks = sorted(
        enumerate(dam_data_list),
        key=lambda task: np.nan_to_num(pd.to_numeric(task[1].get("storage_capacity_m3"), errors="coerce")),
        reverse=True,
    )

    summaries = []
    failures = []
    results = [None] * n_dams

    with mp.Pool(n_workers, initializer=_init_worker, initargs=(gdf_rivers_data,)) as pool:
        for idx, result, failure in tqdm(
            pool.imap_unordered(_worker_indexed, indexed_tasks),
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
                # The raw plot of this run and any plot of an earlier run under a source suffix
                plot_paths = [os.path.join(_cfg.FLOOD_DIR, f"{dam_id}_{sfx}.png") for sfx in ("flood", *_SOURCE_SUFFIX.values())]
                for p in (eav_path, *plot_paths):
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
                "dam_length_m": float(dam_dict.get("dam_length_m") or np.nan),
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
                "upstream_area_km2": dam_dict.get("upstream_area_km2", np.nan),
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
    # A dam without a flood fill gains a row of its own, and the summary holds every dam of eaves_params.csv
    summary_df = _append_dams_without_fill(summary_df, failures)
    if len(summary_df) > 0:
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

    summary_all = _finalize_summary(summary_df)
    summary_all.to_csv(summary_path, index=False)
    # The counts printed below describe the dams with a flood fill
    summary_df = dams_with_fill(summary_all) if "n_pixels" in summary_all.columns else pd.DataFrame()
    print(f"\nSummary saved: {len(summaries)} dams succeeded.")
    if len(summary_df) > 0:
        qcounts = summary_df["quality"].value_counts().sort_index()
        for q, n in qcounts.items():
            print(f"  Quality {q}: {n} dams")
        if "capped" in summary_df.columns:
            n_capped = summary_df["capped"].sum()
            print(f"  Capacity-capped: {n_capped} dams")
        print_flag_tally(summary_df)

    # Records a fit_failed row for every NaN fit, with the summary features attached
    _FEATURE_KEYS = (
        "capacity_mcm", "dam_height_m", "spillway_height_m", "dam_length_m",
        "valley_width_m", "valley_ratio", "channel_slope",
        "mean_catchment_slope", "upstream_area_km2", "construction_year",
    )
    for s in summaries:
        if np.isnan(s.get("b", np.nan)) or np.isnan(s.get("c", np.nan)):
            rec = {
                "dam_id": s["dam_id"],
                "dam_name": s.get("dam_name", ""),
                "reason": "fit_failed",
                "detail": f"Power-law fit returned NaN (n_pixels={s['n_pixels']})",
            }
            for k in _FEATURE_KEYS:
                rec[k] = s.get(k, np.nan)
            rec["latitude"] = s.get("lat", np.nan)
            rec["longitude"] = s.get("lon", np.nan)
            failures.append(rec)

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

    if len(fail_df) > 0:
        fail_df = fail_df.sort_values("dam_id", kind="stable").reset_index(drop=True)
    if "construction_year" in fail_df.columns:
        fail_df["construction_year"] = pd.to_numeric(fail_df["construction_year"], errors="coerce").round().astype("Int32")
    fail_df = round_released_columns(fail_df)
    fail_df.to_csv(fail_path, index=False)
    print(f"Failed/flagged dams: {len(failures)}")

    _run_plots_and_regionalization(summary_all)

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
