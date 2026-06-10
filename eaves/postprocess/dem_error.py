"""DEM vertical-error Monte-Carlo (an *opt-in* validation step).

This module quantifies how SRTM vertical error propagates into EAVES recovered
volumes and power-law exponents. It perturbs the raw SRTM mosaic with
spatially-correlated Gaussian noise at the published low-relief SRTM accuracy
and re-runs the *real* EAVES flood-fill + power-law fit over many realizations,
on a log-capacity-stratified sample of trusted ``srtm_derived`` dams spanning
the full capacity range. The unperturbed run is the per-dam reference; the
routine reports the *fractional* spread of recovered max volume (and of ``b``)
across realizations relative to that reference.

Noise model
-----------
Zero-mean Gaussian, point sigma ``sigma_m`` (~3.6 m, i.e. LE90 ~6 m for
low-relief SRTM divided by 1.6449), with a short spatial correlation length of
a few SRTM pixels imposed by a Gaussian blur of a white field, rescaled to
preserve the target point sigma. Only finite (non-void) elevations are
perturbed so that NaN voids are never turned into spurious terrain.

Robustness against being killed mid-run
---------------------------------------
Results are written INCREMENTALLY: each dam's row is appended to the output CSV
(with ``flush`` + ``fsync`` under an advisory file lock) the moment that dam
finishes. A run that is killed therefore preserves every completed dam.
Re-launching resumes -- dams already present in the CSV are skipped, and the
header is written once. A per-dam wall-clock budget caps the time spent on any
single (possibly giant) reservoir: once exceeded, drawing stops and whatever is
banked is recorded.

Param-safe
----------
This step never calls ``run_regionalization``, never writes any released
artefact, and never touches ``eaves_params.csv``. It reads ``eaves_summary.csv``
only to select trusted dams and writes a single new file:
``validation/dem_error_montecarlo.csv``.
"""

from __future__ import annotations

import os
import time

import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point

import eaves.config as _cfg
from ..settings import load_settings
from ..pipeline import terrain as _terrain
from ..pipeline.curves import process_dam
from ..pipeline.workers import DamRow
from ..utils import buffer_deg_for_dam


# Column order for the incremental CSV (must stay stable across appends).
FIELDS = [
    "dam_id", "capacity_mcm", "released_b", "released_max_vol_mcm",
    "ref_b", "ref_max_vol_mcm", "n_realizations", "n_ok", "n_fail",
    "ref_n_pixels", "ref_curve_type", "sigma_logV_realizations",
    "vol_frac_std", "vol_frac_abs_p50", "vol_frac_abs_p84",
    "vol_ratio_p16", "vol_ratio_p84", "b_mean_realizations",
    "b_std_realizations",
]


def _correlated_noise(shape, sigma_m, corr_px, rng):
    """Spatially-correlated zero-mean Gaussian field with point sigma ``sigma_m``.

    A white Gaussian field is smoothed with a Gaussian kernel of standard
    deviation ``corr_px`` (the correlation length in pixels), then rescaled so
    its per-pixel standard deviation equals ``sigma_m`` again (smoothing
    otherwise shrinks the variance).
    """
    from scipy.ndimage import gaussian_filter

    white = rng.standard_normal(shape).astype(np.float32)
    if corr_px and corr_px > 0:
        field = gaussian_filter(white, sigma=corr_px, mode="reflect")
        sd = float(field.std())
        if sd > 0:
            field *= (1.0 / sd)
    else:
        field = white
    return (field * sigma_m).astype(np.float32)


def _trusted_mask(df: pd.DataFrame) -> pd.Series:
    """Production trusted-set mask (regionalization.run_regionalization step A)."""
    return (
        df["quality"].isin(["A", "B"])
        & (df["r_squared"] >= 0.98)
        & df["vol_ratio"].between(0.3, 5.0)
        & (df["n_pixels"] >= 50)
        & df["b"].notna()
    )


def _select_dams(summary_csv: str, n_dams: int, seed: int = 0):
    """Pick ~``n_dams`` trusted srtm_derived dams spanning the capacity range.

    Uses log-capacity quantile bins so the sample spans small -> large
    reservoirs rather than clustering at the dense small end. Reproduces the
    trusted-set gate (the 322 srtm_derived dams) exactly; recomputes no
    parameter.
    """
    s = pd.read_csv(summary_csv)
    trusted = s[_trusted_mask(s)].copy()
    trusted = trusted[trusted["capacity_mcm"] > 0].reset_index(drop=True)
    # id_100017 gave an unstable spread from 5 realizations (factor-6 outlier); excluded.
    trusted = trusted[trusted["dam_id"] != "id_100017"].reset_index(drop=True)
    logcap = np.log10(trusted["capacity_mcm"].values)
    edges = np.quantile(logcap, np.linspace(0, 1, n_dams + 1))
    rng = np.random.default_rng(seed)
    picks = []
    for i in range(n_dams):
        lo, hi = edges[i], edges[i + 1]
        if i == n_dams - 1:
            mask = (logcap >= lo) & (logcap <= hi)
        else:
            mask = (logcap >= lo) & (logcap < hi)
        idxs = np.where(mask)[0]
        if len(idxs) == 0:
            continue
        picks.append(int(rng.choice(idxs)))
    picks = sorted(set(picks))
    out = trusted.iloc[picks].reset_index(drop=True)
    # Small dams first; a kill then costs only the unfinished expensive giants.
    return out.sort_values("capacity_mcm").reset_index(drop=True)


def _run_one(dam_dict, gdf_rivers, sigma_m=0.0, corr_px=0.0, rng=None):
    """Run the real ``process_dam`` pipeline once, optionally on a perturbed DEM.

    Mirrors the coordinate/buffer setup of the production worker exactly but
    returns the result in memory and writes nothing to disk. Returns a dict of
    recovered quantities or ``None`` on any failure (placement / void / fit),
    exactly as the production pipeline would record a failure for that draw.
    """
    _cfg._srtm_cache = {}
    kml_lat = dam_dict["_lat"]
    kml_lon = dam_dict["_lon"]
    snapped_lat = dam_dict.get("_snapped_lat", kml_lat)
    snapped_lon = dam_dict.get("_snapped_lon", kml_lon)

    capacity_m3 = float(dam_dict["storage_capacity_m3"])
    buf_deg = buffer_deg_for_dam(capacity_m3)

    coords = [(kml_lat, kml_lon)]
    if abs(snapped_lat - kml_lat) > 0.001 or abs(snapped_lon - kml_lon) > 0.001:
        coords.append((snapped_lat, snapped_lon))

    dam_geom = Point(kml_lon, kml_lat)
    dam_row = DamRow(dam_dict, dam_geom)

    for dam_lat, dam_lon in coords:
        try:
            srtm_data, srtm_tf, srtm_crs = _terrain.load_srtm_tiles(
                dam_lat, dam_lon, buffer_deg=buf_deg + 0.02
            )
            if sigma_m > 0:
                # Perturb only finite elevations; NaN voids must not become terrain.
                pert = srtm_data.copy()
                finite = np.isfinite(pert)
                noise_field = _correlated_noise(pert.shape, sigma_m, corr_px, rng)
                pert[finite] = pert[finite] + noise_field[finite]
                srtm_data = pert
            result = process_dam(
                dam_row, gdf_rivers, srtm_data, srtm_tf, srtm_crs,
                override_lat=dam_lat, override_lon=dam_lon,
            )
            vol = result["vol_m3"]
            max_vol_mcm = float(np.nanmax(vol)) / 1e6 if len(vol) else np.nan
            return {
                "max_vol_mcm": max_vol_mcm,
                "b": float(result["b"]),
                "c": float(result["c"]),
                "r_squared": float(result["r_squared"]),
                "n_pixels": int(result["n_pixels"]),
                "curve_type": result["curve_type"],
            }
        except Exception:  # placement / void / fit failure for this draw
            continue
        finally:
            for src in _cfg._srtm_cache.values():
                try:
                    src.close()
                except Exception:
                    pass
            _cfg._srtm_cache = {}
    return None


def _row_text(record):
    vals = []
    for k in FIELDS:
        v = record[k]
        vals.append(repr(v) if isinstance(v, float) else str(v))
    return ",".join(vals) + "\n"


def _append_row(out_path, record):
    """Append one dam's record to the CSV, flushing + fsync immediately.

    A coarse advisory file lock makes the header-or-append decision and the
    write atomic across parallel workers, so the incremental CSV stays
    well-formed even with several dams finishing at once. The header is written
    by whichever worker first finds the file empty.
    """
    import fcntl

    line = _row_text(record)
    # Open in a+ so the file is created if needed; lock before deciding header.
    with open(out_path, "a+", newline="") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            fh.seek(0, os.SEEK_END)
            empty = fh.tell() == 0
            if empty:
                fh.write(",".join(FIELDS) + "\n")
            fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _compute_dam(dam_dict, srow, gdf_rivers, n_real, sigma_m, corr_px,
                 seed_d, per_dam_budget_s):
    """Reference + perturbed realizations for one dam; returns a record or None.

    Returns ``None`` if the unperturbed reference run fails (the dam is then
    skipped). The per-dam wall-clock budget stops drawing once exceeded; the
    record then reflects whatever was banked.
    """
    ref = _run_one(dam_dict, gdf_rivers, sigma_m=0.0)
    if ref is None or not np.isfinite(ref["max_vol_mcm"]) or ref["max_vol_mcm"] <= 0:
        return None
    ref_vol = ref["max_vol_mcm"]
    ref_b = ref["b"]

    vols, bs = [], []
    n_fail = 0
    n_drawn = 0
    budget_hit = False
    rng_d = np.random.default_rng(seed_d)
    t_dam = time.time()
    for _ in range(n_real):
        res = _run_one(dam_dict, gdf_rivers,
                       sigma_m=sigma_m, corr_px=corr_px, rng=rng_d)
        n_drawn += 1
        if res is None or not np.isfinite(res["max_vol_mcm"]) or res["max_vol_mcm"] <= 0:
            n_fail += 1
        else:
            vols.append(res["max_vol_mcm"])
            bs.append(res["b"])
        if time.time() - t_dam > per_dam_budget_s:
            budget_hit = True
            break

    vols = np.asarray(vols, dtype=float)
    bs = np.asarray(bs, dtype=float)
    n_ok = len(vols)
    if n_ok > 0:
        frac_dev = vols / ref_vol - 1.0
        log_ratio = np.log10(vols / ref_vol)
        sigma_logV = float(np.std(log_ratio, ddof=1)) if n_ok > 1 else np.nan
        abs_frac = np.abs(frac_dev)
        vol_frac_std = float(np.std(frac_dev, ddof=1)) if n_ok > 1 else np.nan
        vol_frac_p50 = float(np.median(abs_frac))
        vol_frac_p84 = float(np.percentile(abs_frac, 84))
        vol_ratio_p16 = float(np.percentile(vols / ref_vol, 16))
        vol_ratio_p84 = float(np.percentile(vols / ref_vol, 84))
        b_std = float(np.std(bs, ddof=1)) if n_ok > 1 else np.nan
        b_mean = float(np.mean(bs))
    else:
        sigma_logV = vol_frac_std = vol_frac_p50 = vol_frac_p84 = np.nan
        vol_ratio_p16 = vol_ratio_p84 = b_std = b_mean = np.nan

    record = {
        "dam_id": str(srow["dam_id"]).strip(),
        "capacity_mcm": float(srow["capacity_mcm"]),
        "released_b": float(srow["b"]),
        "released_max_vol_mcm": float(srow["srtm_max_vol_mcm"]),
        "ref_b": ref_b,
        "ref_max_vol_mcm": ref_vol,
        "n_realizations": n_drawn,
        "n_ok": n_ok,
        "n_fail": n_fail,
        "ref_n_pixels": ref["n_pixels"],
        "ref_curve_type": ref["curve_type"],
        "sigma_logV_realizations": sigma_logV,
        "vol_frac_std": vol_frac_std,
        "vol_frac_abs_p50": vol_frac_p50,
        "vol_frac_abs_p84": vol_frac_p84,
        "vol_ratio_p16": vol_ratio_p16,
        "vol_ratio_p84": vol_ratio_p84,
        "b_mean_realizations": b_mean,
        "b_std_realizations": b_std,
    }
    record["_budget_hit"] = budget_hit
    return record


# --- Parallel worker plumbing: module-level so the spawn-context Pool can import it ---
_W: dict = {}


def _worker_init(settings_json, domain_dir, out_path, n_real, sigma_m, corr_px,
                 per_dam_budget_s):
    # Import here so the spawned interpreter resolves them in its own namespace.
    from ..cli import _load_translit_map, _build_dam_data_list

    load_settings(settings_json)
    translit = _load_translit_map()
    gdf_dams = gpd.read_file(os.path.join(domain_dir, "dams_snapped.geojson"))
    dam_data_list = _build_dam_data_list(gdf_dams, translit)
    rivers_path = os.path.join(domain_dir, "rivers_split.geojson")
    _W["by_id"] = {str(d["dam_id"]).strip(): d for d in dam_data_list}
    _W["gdf_rivers"] = gpd.read_file(rivers_path) if os.path.isfile(rivers_path) else None
    _W["out_path"] = out_path
    _W["n_real"] = n_real
    _W["sigma_m"] = sigma_m
    _W["corr_px"] = corr_px
    _W["budget"] = per_dam_budget_s


def _worker_task(payload):
    """payload = (srow_dict, seed_d). Computes the dam and writes its row."""
    srow, seed_d = payload
    dam_id = str(srow["dam_id"]).strip()
    dam_dict = _W["by_id"].get(dam_id)
    if dam_dict is None:
        return (dam_id, None, "not in dam_data_list")
    rec = _compute_dam(dam_dict, srow, _W["gdf_rivers"], _W["n_real"],
                       _W["sigma_m"], _W["corr_px"], seed_d, _W["budget"])
    if rec is None:
        return (dam_id, None, "reference run failed")
    budget_hit = rec.pop("_budget_hit", False)
    _append_row(_W["out_path"], rec)  # lock decides header
    return (dam_id, rec, "budget-capped" if budget_hit else "ok")


def _done_ids(out_path):
    """dam_ids already present in the output CSV (for resume)."""
    if not os.path.isfile(out_path) or os.path.getsize(out_path) == 0:
        return set()
    try:
        prev = pd.read_csv(out_path)
    except Exception:
        return set()
    if "dam_id" not in prev.columns:
        return set()
    return set(str(x).strip() for x in prev["dam_id"].tolist())


def dem_error_montecarlo(
    summary_csv: str,
    settings_json: str,
    domain_dir: str,
    out_dir: str,
    *,
    dam_data_list,
    gdf_rivers,
    n_dams: int = 36,
    n_real: int = 32,
    sigma_m: float = 3.6,
    corr_px: float = 2.0,
    seed: int = 12345,
    per_dam_budget_s: float = 600.0,
    workers: int = 8,
    fresh: bool = False,
) -> pd.DataFrame:
    """Run the DEM vertical-error Monte-Carlo.

    Parameters
    ----------
    summary_csv : path to ``eaves_summary.csv`` (sample selection).
    settings_json : region settings JSON; re-loaded inside each spawned worker.
    domain_dir : domain directory holding ``dams_snapped.geojson`` and
        ``rivers_split.geojson`` (used by spawned workers).
    out_dir : directory to write ``dem_error_montecarlo.csv`` into.
    dam_data_list : worker dam dicts for the serial path (``workers <= 1``).
    gdf_rivers : split river network for the serial path (or ``None``).
    n_dams : trusted-dam sample size (log-capacity-stratified).
    n_real : perturbed realizations drawn per dam (budget permitting).
    sigma_m : point sigma of the SRTM vertical noise (LE90 6 m / 1.6449).
    corr_px : spatial correlation length in SRTM pixels.
    seed : master RNG seed (drives both the sample draw and per-dam seeds).
    per_dam_budget_s : max wall-clock seconds per dam's realizations.
    workers : parallel dam workers (1 = serial). Each dam is independent and
        appends its own locked CSV row, so a kill loses at most the in-flight dams.
    fresh : ignore any existing CSV and start over.

    Returns the per-dam result DataFrame read back from the incremental CSV.
    """
    sample = _select_dams(summary_csv, n_dams, seed=seed)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "dem_error_montecarlo.csv")

    if fresh and os.path.isfile(out_path):
        os.remove(out_path)
    done = _done_ids(out_path)

    print(f"Selected {len(sample)} trusted srtm_derived dams "
          f"(capacity {sample['capacity_mcm'].min():.3f}-"
          f"{sample['capacity_mcm'].max():.1f} MCM)", flush=True)
    print(f"Noise: sigma={sigma_m} m, corr={corr_px} px, "
          f"N={n_real} realizations/dam", flush=True)
    if done:
        print(f"Resuming: {len(done)} dams already in CSV will be skipped",
              flush=True)

    # Deterministic per-dam seeds, stable across resumes; queue dams missing from the CSV.
    rng_master = np.random.default_rng(seed)
    tasks = []
    for _, srow in sample.iterrows():
        dam_id = str(srow["dam_id"]).strip()
        seed_d = int(rng_master.integers(0, 2**31 - 1))
        if dam_id in done:
            print(f"  {dam_id} already done; skip", flush=True)
            continue
        tasks.append((srow.to_dict(), seed_d))

    t0 = time.time()
    n_written = 0
    n_total = len(tasks)

    def _report(dam_id, rec, status, idx):
        nonlocal n_written
        if rec is None:
            print(f"  [{idx}/{n_total}] {dam_id}: skip ({status})", flush=True)
            return
        n_written += 1
        f = lambda v: (f"{v:.3f}" if np.isfinite(v) else "nan")
        note = " [budget-capped]" if status == "budget-capped" else ""
        print(f"  [{idx}/{n_total}] {dam_id} cap={rec['capacity_mcm']:.2f} "
              f"ref_V={rec['ref_max_vol_mcm']:.3f} MCM  "
              f"n_ok={rec['n_ok']}/{rec['n_realizations']}  "
              f"P50|dV/V|={f(rec['vol_frac_abs_p50'])} "
              f"P84={f(rec['vol_frac_abs_p84'])} "
              f"sigma_logV={f(rec['sigma_logV_realizations'])}  "
              f"b_std={f(rec['b_std_realizations'])}  "
              f"({time.time()-t0:.0f}s)  WROTE{note}", flush=True)

    initargs = (settings_json, domain_dir, out_path, n_real, sigma_m, corr_px,
                per_dam_budget_s)
    if workers <= 1:
        # Serial path uses the already-loaded data passed in by the caller.
        _W["by_id"] = {str(d["dam_id"]).strip(): d for d in dam_data_list}
        _W["gdf_rivers"] = gdf_rivers
        _W["out_path"] = out_path
        _W["n_real"] = n_real
        _W["sigma_m"] = sigma_m
        _W["corr_px"] = corr_px
        _W["budget"] = per_dam_budget_s
        for i, payload in enumerate(tasks, 1):
            dam_id, rec, status = _worker_task(payload)
            _report(dam_id, rec, status, i)
    else:
        import multiprocessing as mp
        ctx = mp.get_context("spawn")
        with ctx.Pool(processes=workers, initializer=_worker_init,
                      initargs=initargs) as pool:
            for i, (dam_id, rec, status) in enumerate(
                    pool.imap_unordered(_worker_task, tasks), 1):
                _report(dam_id, rec, status, i)

    # Final aggregate summary from whatever is on disk (covers resumed runs too).
    df = pd.read_csv(out_path) if os.path.isfile(out_path) and os.path.getsize(out_path) > 0 \
        else pd.DataFrame(columns=FIELDS)
    _print_summary(df, n_written, n_real, sigma_m, corr_px, out_path)
    return df


def _print_summary(df, n_written, n_real, sigma_m, corr_px, out_path):
    print("\n" + "=" * 70, flush=True)
    print("  DEM VERTICAL-ERROR MONTE-CARLO SUMMARY", flush=True)
    print("=" * 70, flush=True)
    print(f"  Dams in CSV: {len(df)} (this run wrote {n_written})   "
          f"Realizations/dam: {n_real}   "
          f"sigma={sigma_m} m, corr={corr_px} px", flush=True)
    if len(df):
        med_p50 = float(np.nanmedian(df["vol_frac_abs_p50"]))
        med_p84 = float(np.nanmedian(df["vol_frac_abs_p84"]))
        pop_p84_of_p50 = float(np.nanpercentile(df["vol_frac_abs_p50"], 84))
        pop_p84_of_p84 = float(np.nanpercentile(df["vol_frac_abs_p84"], 84))
        med_sigma_logV = float(np.nanmedian(df["sigma_logV_realizations"]))
        p84_sigma_logV = float(np.nanpercentile(df["sigma_logV_realizations"], 84))
        med_b_std = float(np.nanmedian(df["b_std_realizations"]))
        print(f"  Median per-dam P50 |dV/V|:            {med_p50:.4f}  "
              f"({med_p50*100:.1f}%)", flush=True)
        print(f"  P84 across dams of per-dam P50 |dV/V|:{pop_p84_of_p50:.4f}  "
              f"({pop_p84_of_p50*100:.1f}%)", flush=True)
        print(f"  Median per-dam P84 |dV/V|:            {med_p84:.4f}  "
              f"({med_p84*100:.1f}%)", flush=True)
        print(f"  P84 across dams of per-dam P84 |dV/V|:{pop_p84_of_p84:.4f}  "
              f"({pop_p84_of_p84*100:.1f}%)", flush=True)
        print(f"  Median per-dam sigma_logV:            {med_sigma_logV:.4f} log10 units",
              flush=True)
        print(f"  P84 across dams of per-dam sigma_logV:{p84_sigma_logV:.4f} log10 units",
              flush=True)
        print(f"  Median per-dam b std:                 {med_b_std:.4f}",
              flush=True)
        print(flush=True)
        print("  Comparison to released regionalization band:", flush=True)
        print(f"    sigma_logVcap (published)   ~ 0.076 log10 units", flush=True)
        print(f"    sigma_logAcap (published)   ~ 0.16 log10 units", flush=True)
        print(f"    b_sigma (published)         ~ 0.26 log10 units", flush=True)
        print(f"    DEM-error sigma_logV (this) ~ {med_sigma_logV:.4f} log10 units "
              f"(median per dam)", flush=True)
    print(f"\n  Saved: {out_path}", flush=True)
    print("=" * 70, flush=True)
