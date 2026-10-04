"""Placement/acceptance constant sensitivity sweep (an *opt-in* validation step).

This module quantifies how robust the released EAVES parameters are to the
exact values of five placement/acceptance constants, the three most influential
hand-tuned ones and the two calibrated constants of the drainage rule. Each
constant is perturbed one at a time by a small set of fractional offsets
(``+/-20%`` and ``+/-30%`` by default), the *real* EAVES flood-fill is re-run
over a trusted-dam sample at each setting, and the routine reports how the
trusted-set size, the A-F grade distribution and the median trusted-set
power-law exponent ``b`` move. The goal is to demonstrate that the released
catalogue is insensitive to the precise value of these constants.

Constants swept (``eaves.config`` provenance)
---------------------------------------------
* ``ALIGN_WEIGHT``              (= 2.35) wall-to-crest alignment weight (``placement``).
* ``MAX_CREST_FLOW_DOT``        (= 0.74) max ``|dot(wall, flow)|`` to accept a crest.
* ``VOID_THRESHOLD``            (= 0.05) max NaN-void fraction accepted in a fill (``curves``).
* ``DRAIN_WALL_TOLERANCE_M``    (= 1000) distance past the half wall (m) within
  which a pool outlet counts as next to the wall (``drainage``).
* ``DRAIN_MAX_OUTLET_POSITION`` (= 0.65) largest outlet position along the
  capacity-level pool accepted in a fill (``drainage``).

The constants are bound by name into ``eaves.pipeline.placement``,
``eaves.pipeline.curves`` and ``eaves.pipeline.drainage`` at import time
(``from ..config import ...``), so the sweep overrides them in those module
namespaces (not just in ``eaves.config``) for the duration of each cell and
restores them afterwards.

Param-safe
----------
This step never calls ``run_regionalization``, never writes any released
artifact, and never touches ``eaves_params.csv``. It reads ``eaves_summary.csv``
only to pick the sample, recomputes each dam's grade / trusted membership with
the *production* :func:`assign_quality` and the production trusted mask, and
writes a single new file: ``validation/sensitivity_sweep.csv``.
"""

from __future__ import annotations

import multiprocessing as mp
import os
import time

import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point

import eaves.config as _cfg
from ..pipeline import terrain as _terrain
from ..pipeline import placement as _placement
from ..pipeline import curves as _curves
from ..pipeline import drainage as _drainage
from ..pipeline.curves import process_dam
from ..pipeline.workers import DamRow
from ..utils import buffer_deg_for_dam, round_released_columns
from .regionalization import assign_quality


# Maps each swept constant to (module, attribute, baseline), read live from eaves.config
def _constants() -> dict:
    return {
        "ALIGN_WEIGHT":              (_placement, "ALIGN_WEIGHT",              float(_cfg.ALIGN_WEIGHT)),
        "MAX_CREST_FLOW_DOT":        (_placement, "MAX_CREST_FLOW_DOT",        float(_cfg.MAX_CREST_FLOW_DOT)),
        "VOID_THRESHOLD":            (_curves,    "VOID_THRESHOLD",            float(_cfg.VOID_THRESHOLD)),
        "DRAIN_WALL_TOLERANCE_M":    (_drainage,  "DRAIN_WALL_TOLERANCE_M",    float(_cfg.DRAIN_WALL_TOLERANCE_M)),
        "DRAIN_MAX_OUTLET_POSITION": (_drainage,  "DRAIN_MAX_OUTLET_POSITION", float(_cfg.DRAIN_MAX_OUTLET_POSITION)),
    }


def _trusted_mask(df: pd.DataFrame) -> pd.Series:
    """Production trusted-set mask (regionalization.run_regionalization step A)."""
    return (
        df["quality"].isin(["A", "B"])
        & (df["r_squared"] >= 0.98)
        & df["vol_ratio"].between(0.3, 5.0)
        & (df["n_pixels"] >= 50)
        & df["b"].notna()
    )


def _run_one(dam_dict, gdf_rivers):
    """Run the real ``process_dam`` once and return the summary fields needed to
    grade and trust-tag the dam, or ``None`` on failure. Writes nothing.

    Mirrors the coordinate/buffer setup of the production worker exactly.
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

    dam_row = DamRow(dam_dict, Point(kml_lon, kml_lat))
    for dam_lat, dam_lon in coords:
        try:
            srtm_data, srtm_tf, srtm_crs = _terrain.load_srtm_tiles(
                dam_lat, dam_lon, buffer_deg=buf_deg + 0.02
            )
            r = process_dam(dam_row, gdf_rivers, srtm_data, srtm_tf, srtm_crs,
                            override_lat=dam_lat, override_lon=dam_lon)
            vol = r["vol_m3"]
            max_vol_mcm = float(np.nanmax(vol)) / 1e6 if len(vol) else np.nan
            cap_mcm = capacity_m3 / 1e6
            z_range = float(r["z_max"]) - float(r["z_min"])
            sp = float(r["spillway_height_m"])
            return {
                "b": float(r["b"]),
                "r_squared": float(r["r_squared"]),
                "n_pixels": int(r["n_pixels"]),
                "spillway_height_m": sp,
                "srtm_max_vol_mcm": max_vol_mcm,
                "vol_ratio": (max_vol_mcm / cap_mcm) if cap_mcm > 0 else np.nan,
                "z_range_ratio": (z_range / sp) if sp > 0 else np.nan,
            }
        except Exception:
            continue
        finally:
            for src in _cfg._srtm_cache.values():
                try:
                    src.close()
                except Exception:
                    pass
            _cfg._srtm_cache = {}
    return None


# Dam dicts and river table of the running sweep, read by the workers forked for each cell
_sweep = {"by_id": {}, "gdf_rivers": None}


def _run_sample_dam(dam_id):
    """Run one sample dam at the constants the forked worker inherited."""
    dd = _sweep["by_id"].get(dam_id)
    return _run_one(dd, _sweep["gdf_rivers"]) if dd is not None else None


def _grade_and_tag(rows):
    """Apply :func:`assign_quality` + the trusted mask to a list of result dicts.

    Returns ``(n_trusted, median_b_trusted, grade_counts_dict, n_success)``.
    """
    df = pd.DataFrame([r for r in rows if r is not None])
    if len(df) == 0:
        return 0, np.nan, {}, 0
    df["quality"] = df.apply(assign_quality, axis=1)
    trusted = df[_trusted_mask(df)]
    grade_counts = df["quality"].value_counts().to_dict()
    median_b = float(trusted["b"].median()) if len(trusted) else np.nan
    return int(len(trusted)), median_b, grade_counts, int(len(df))


def _set_const(name, value, consts):
    mod, attr, _ = consts[name]
    setattr(mod, attr, value)
    setattr(_cfg, attr, value)  # Keeps eaves.config in sync


def _select_sample(summary_csv: str, n_dams: int, seed: int):
    """Pick ~``n_dams`` trusted srtm_derived dams spanning the capacity range.

    Log-capacity quantile bins span the small -> large reservoir range rather
    than clustering at the dense small end. Reproduces the production trusted
    gate exactly and computes no parameter.
    """
    s = pd.read_csv(summary_csv)
    trusted = s[_trusted_mask(s)].copy()
    trusted = trusted[trusted["capacity_mcm"] > 0].reset_index(drop=True)
    logcap = np.log10(trusted["capacity_mcm"].values)
    n = min(n_dams, len(trusted))
    edges = np.quantile(logcap, np.linspace(0, 1, n + 1))
    rng = np.random.default_rng(seed)
    picks = []
    for i in range(n):
        lo, hi = edges[i], edges[i + 1]
        mask = (logcap >= lo) & (logcap <= hi) if i == n - 1 else (logcap >= lo) & (logcap < hi)
        idxs = np.where(mask)[0]
        if len(idxs):
            picks.append(int(rng.choice(idxs)))
    picks = sorted(set(picks))
    return trusted.iloc[picks].reset_index(drop=True)


def sensitivity_sweep(
    summary_csv: str,
    domain_dir: str,
    out_dir: str,
    *,
    dam_data_list,
    gdf_rivers,
    n_dams: int = 60,
    seed: int = 7,
    perturbations=(-0.30, -0.20, 0.0, 0.20, 0.30),
) -> pd.DataFrame:
    """Run the placement/acceptance constant sensitivity sweep.

    Parameters
    ----------
    summary_csv : path to ``eaves_summary.csv`` (sample selection + baselines).
    domain_dir : unused directly here, accepted for a uniform validation API.
    out_dir : directory to write ``sensitivity_sweep.csv`` into.
    dam_data_list : worker dam dicts (from ``cli._build_dam_data_list``).
    gdf_rivers : split river network GeoDataFrame (or ``None``).
    n_dams : trusted-dam sample size (log-capacity-stratified).
    seed : RNG seed for the sample draw.
    perturbations : fractional offsets applied to each constant in turn. The
        ``0.0`` entry is the shared baseline cell.

    Returns the per-cell result DataFrame (also written to disk).
    """
    consts = _constants()
    by_id = {str(d["dam_id"]).strip(): d for d in dam_data_list}

    sample = _select_sample(summary_csv, n_dams, seed)
    sample_ids = [str(x).strip() for x in sample["dam_id"]]
    print(f"Sensitivity sample: {len(sample_ids)} trusted srtm_derived dams "
          f"(capacity {sample['capacity_mcm'].min():.3f}-"
          f"{sample['capacity_mcm'].max():.1f} MCM)", flush=True)

    records = []
    t0 = time.time()
    _sweep["by_id"] = by_id
    _sweep["gdf_rivers"] = gdf_rivers
    n_workers = min(len(sample_ids), os.cpu_count() or 1)
    can_fork = "fork" in mp.get_all_start_methods()

    def run_cell(label, const_name, frac, value):
        if can_fork and n_workers > 1:
            # Workers forked for the cell inherit the constants set for it, and the rows keep the sample order
            with mp.get_context("fork").Pool(n_workers) as pool:
                rows = pool.map(_run_sample_dam, sample_ids)
        else:
            rows = [_run_sample_dam(did) for did in sample_ids]
        n_trust, med_b, grades, n_succ = _grade_and_tag(rows)
        rec = {
            "constant": const_name,
            "perturbation_frac": frac,
            "value": value,
            "n_sample": len(sample_ids),
            "n_success": n_succ,
            "n_trusted": n_trust,
            "frac_trusted": n_trust / len(sample_ids) if sample_ids else np.nan,
            "median_b_trusted": med_b,
        }
        for g in ["A", "B", "C", "D", "F"]:
            rec[f"grade_{g}"] = int(grades.get(g, 0))
        records.append(rec)
        print(f"  [{label}] {const_name}={value:.4f} (frac {frac:+.2f})  "
              f"n_trusted={n_trust}/{len(sample_ids)}  median_b={med_b:.4f}  "
              f"grades A/B/C/D/F="
              f"{rec['grade_A']}/{rec['grade_B']}/{rec['grade_C']}/"
              f"{rec['grade_D']}/{rec['grade_F']}  ({time.time()-t0:.0f}s)", flush=True)
        return rec

    # Computes the baseline once, with every constant at its released value
    base = run_cell("baseline", "baseline", 0.0, np.nan)

    for const_name, (_mod, _attr, baseval) in consts.items():
        for frac in perturbations:
            if frac == 0.0:
                # Records a per-constant copy of the shared baseline row
                rec = dict(base)
                rec["constant"] = const_name
                rec["perturbation_frac"] = 0.0
                rec["value"] = baseval
                records.append(rec)
                continue
            value = baseval * (1.0 + frac)
            try:
                _set_const(const_name, value, consts)
                run_cell(f"{const_name} {frac:+.0%}", const_name, frac, value)
            finally:
                _set_const(const_name, baseval, consts)  # Restores the baseline value

    df = pd.DataFrame(records)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "sensitivity_sweep.csv")
    round_released_columns(df).to_csv(out_path, index=False)

    _print_summary(df, base, consts, out_path)
    return df


def _print_summary(df, base, consts, out_path):
    print("\n" + "=" * 70)
    print("  PLACEMENT/ACCEPTANCE CONSTANT SENSITIVITY SWEEP")
    print("=" * 70)
    b0 = base["n_trusted"]
    mb0 = base["median_b_trusted"]
    print(f"  Baseline: n_trusted={b0}/{base['n_sample']}, "
          f"median_b={mb0:.4f}, grades A/B/C/D/F="
          f"{base['grade_A']}/{base['grade_B']}/{base['grade_C']}/"
          f"{base['grade_D']}/{base['grade_F']}")
    for const_name in consts:
        sub = df[(df["constant"] == const_name) & (df["perturbation_frac"] != 0.0)]
        if not len(sub):
            continue
        d_trust = sub["n_trusted"] - b0
        d_b = sub["median_b_trusted"] - mb0
        print(f"\n  {const_name}: across +/-20-30% perturbations")
        print(f"    n_trusted change:  min {int(d_trust.min()):+d}  "
              f"max {int(d_trust.max()):+d}  (baseline {b0})")
        print(f"    median_b change:   min {d_b.min():+.4f}  "
              f"max {d_b.max():+.4f}  (baseline {mb0:.4f})")
    print(f"\n  Saved: {out_path}")
    print("=" * 70)
