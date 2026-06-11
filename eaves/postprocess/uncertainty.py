"""Per-dam V uncertainty propagation.

For every dam in ``eaves_params.csv``, propagates uncertainty into a
1$\\sigma$ band on V at three standard fill levels:

- half pool   (A = 0.50 A_cap)
- quarter pool (A = 0.25 A_cap)
- tenth pool  (A = 0.10 A_cap)

The band combines three independent error sources in quadrature:

.. math::

    \\sigma^2(\\log_{10}V) \\approx (b\\,\\sigma_{\\log A_\\mathrm{cap}})^2
        + (b_\\sigma\\,\\log_{10}(A/A_\\mathrm{cap}))^2
        + \\sigma^2(\\log_{10}V_\\mathrm{cap})

1. **A_cap regression error** ``(b * sigma_logAcap)``. For regionalized
   dams the full-pool area is predicted by the multi-feature log-A_cap
   regression, whose leave-one-out residual (``sigma_logAcap`` in log10
   units, from ``validation/regionalization_loo.csv``) propagates to
   V through the exponent ``b``. This term is **constant in area** (it is an
   anchor-position error) and therefore does **not vanish at the anchor**.
   SRTM-derived dams measure A_cap directly from the DEM, so this term is
   zero for them.
2. **Exponent-spread error** ``(b_sigma * log10(A/A_cap))``. The original
   term: the dam-to-dam geometric spread of $b$, which fans out away from
   full pool and is zero at the anchor.
3. **Catalog-capacity error** ``sigma_logVcap``. A stated 1$\\sigma$ on the
   published storage capacity that anchors $V_\\mathrm{cap}$, taken from the
   uncapped-training-fill spread of $\\log_{10}(V_\\mathrm{SRTM}/V_\\mathrm{cap})$. Also
   constant in area, so it too does not vanish at the anchor.

Because terms (1) and (3) are area-independent, the band for regionalized
(``regi_multi``) dams is strictly positive everywhere, including at full
pool, and is substantially wider than for ``srtm_derived`` dams.

The single output is ``<CSV_DIR>/validation/v_uncertainty.csv``, a flat
per-dam table with the log10-units sigma (and its term decomposition) and the
equivalent fractional bounds (``V_frac_up_*`` / ``V_frac_down_*``, stored as
decimal fractions: 0.29 = +29%, a value > 1.0 denotes > 100%) at each of the
three fill levels.

Usage
-----
    python -m eaves.postprocess.uncertainty --settings region/<region>/<region>.json
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import numpy as np
import pandas as pd

import eaves.config as _cfg
from .reliability import training_mask


_FILL_LEVELS = {
    "half_pool":    0.50,
    "quarter_pool": 0.25,
    "tenth_pool":   0.10,
}


_TRUSTED_FILTER_GATES = {
    "quality":   ("A", "B"),
    "r_squared": 0.98,
    "vol_ratio": (0.3, 5.0),
    "n_pixels":  50,
}


def compute_b_sigma(summary_df: pd.DataFrame) -> float:
    """Population 1$\\sigma$ half-width on $b$ from the training set.

    The training set is the trusted dams built after the SRTM acquisition
    (the same population the regionalization recipe is trained on). Equal
    to the LOO baseline sigma for predicting $b$ from the global median,
    and the single region-level number that propagates into every per-dam
    V band below.
    """
    m = training_mask(summary_df)
    b = summary_df.loc[m, "b"].dropna()
    if len(b) < 10:
        return 0.25
    return float((b.quantile(0.84) - b.quantile(0.16)) / 2.0)


def compute_sigma_log_acap(loo_df: pd.DataFrame) -> float:
    """1$\\sigma$ (log10 units) leave-one-out error of the multi-feature
    $\\log A_\\mathrm{cap}$ regression.

    Computed as the population half-width of
    $\\log_{10}(A_\\mathrm{cap}^\\mathrm{pred} / A_\\mathrm{DEM})$ over the
    trusted dams in ``validation/regionalization_loo.csv``. This is the
    A_cap-position error that applies to every regionalized dam (whose
    full-pool area is predicted, not measured). Falls back to 0.16 log10
    units (the KSA value) when the table is missing or too small.
    """
    if loo_df is None or not {"multi_A_cap_km2", "A_DEM_km2"}.issubset(loo_df.columns):
        return 0.16
    m = loo_df.dropna(subset=["multi_A_cap_km2", "A_DEM_km2"])
    m = m[(m["multi_A_cap_km2"] > 0) & (m["A_DEM_km2"] > 0)]
    if len(m) < 10:
        return 0.16
    r = np.log10(m["multi_A_cap_km2"].values / m["A_DEM_km2"].values)
    return float((np.quantile(r, 0.84) - np.quantile(r, 0.16)) / 2.0)


def compute_sigma_log_vcap(summary_df: pd.DataFrame) -> float:
    """1$\\sigma$ (log10 units) catalog-capacity error.

    Estimated from the uncapped-training-fill spread of
    $\\log_{10}(V_\\mathrm{SRTM}/V_\\mathrm{cap})$: how much the independent
    geometric (SRTM) volume disagrees with the published catalog capacity on
    dams where both are trustworthy. Stands in for the unknown error on the
    catalog storage value that anchors every curve. Falls back to 0.08 log10
    units (the KSA value) when unavailable.
    """
    if summary_df is None or "vol_ratio" not in summary_df.columns:
        return 0.08
    m = training_mask(summary_df)
    sub = summary_df.loc[m]
    # Capped fills are right-censored by the capacity cap (their ratio is
    # pinned near unity), so only uncapped fills carry usable spread. The
    # resulting estimate is conservative: the uncapped subset also contains
    # genuine sub-pixel shortfall, which inflates the spread.
    if "capped" in sub.columns:
        sub = sub[~sub["capped"].astype(bool)]
    vr = sub["vol_ratio"].dropna()
    vr = vr[vr > 0]
    if len(vr) < 10:
        return 0.08
    r = np.log10(vr.values)
    return float((np.quantile(r, 0.84) - np.quantile(r, 0.16)) / 2.0)


def _a_cap_m2(c: float, b: float, capacity_mcm: float) -> float:
    """Implicit anchor area: solve V_cap = c * A_cap^b for A_cap."""
    V_cap_m3 = capacity_mcm * 1e6
    return float((V_cap_m3 / c) ** (1.0 / b))


def _v_sigma_log10(b_sigma: float, fill_frac: float) -> float:
    """1-sigma uncertainty on log10(V) at A = fill_frac * A_cap."""
    return float(b_sigma * abs(np.log10(fill_frac)))


def compute_uncertainty_table(params_df: pd.DataFrame,
                              b_sigma: float,
                              sigma_log_acap: float = 0.0,
                              sigma_log_vcap: float = 0.0) -> pd.DataFrame:
    """Return one row per dam with V uncertainty at the three fill levels.

    The 1$\\sigma$ band on $\\log_{10}V$ combines three terms in quadrature:

    - ``b * sigma_log_acap`` -- the A_cap-regression error, applied **only**
      to regionalized (``regi_multi`` / ``regr_derived``) dams whose
      full-pool area is predicted. SRTM-derived dams measure A_cap from the
      DEM and carry no A_cap-regression error. Area-independent (does not
      vanish at the anchor).
    - ``b_sigma * |log10(A/A_cap)|`` -- the exponent-spread error. Zero at
      the anchor, fans out at low fill.
    - ``sigma_log_vcap`` -- the catalog-capacity error. Area-independent.

    Setting ``sigma_log_acap = sigma_log_vcap = 0`` recovers the legacy
    ``b_sigma``-only band.
    """
    rows = []
    for _, p in params_df.iterrows():
        c = float(p["c"])
        b = float(p["b"])
        cap = float(p["capacity_mcm"])
        if not (np.isfinite(c) and np.isfinite(b) and c > 0 and b > 0 and cap > 0):
            continue
        a_cap = _a_cap_m2(c, b, cap)
        v_cap = cap * 1e6
        src = str(p.get("source", ""))
        # Predicted-A_cap term applies to regionalized tiers only; SRTM dams measure A_cap.
        acap_term = (b * sigma_log_acap) if src.startswith("regi") or src.startswith("regr") else 0.0
        vcap_term = sigma_log_vcap
        row = {
            "dam_id":           p["dam_id"],
            "source":           src,
            "capacity_mcm":     cap,
            "b":                b,
            "b_sigma":          b_sigma,
            "sigma_log_acap":   sigma_log_acap if acap_term > 0 else 0.0,
            "sigma_log_vcap":   vcap_term,
            "sigma_acap_term":  acap_term,
            "A_cap_km2":        a_cap / 1e6,
        }
        for label, frac in _FILL_LEVELS.items():
            bspread_term = _v_sigma_log10(b_sigma, frac)
            sigma_log10 = float(np.sqrt(acap_term**2 + bspread_term**2 + vcap_term**2))
            v_pred_m3 = c * (a_cap * frac) ** b
            row[f"V_pred_{label}_mcm"]    = v_pred_m3 / 1e6
            row[f"V_sigma_log10_{label}"] = sigma_log10
            row[f"V_sigma_bspread_{label}"] = bspread_term
            row[f"V_frac_up_{label}"]     = 10.0**sigma_log10 - 1.0
            row[f"V_frac_down_{label}"]   = 1.0 - 10.0**(-sigma_log10)
        rows.append(row)
    return pd.DataFrame(rows)


def run(settings_path: str | None = None) -> pd.DataFrame:
    """Compute the table and write it to ``<CSV_DIR>/validation/v_uncertainty.csv``."""
    if settings_path is not None:
        from eaves.settings import load_settings
        load_settings(settings_path)

    params_path  = Path(_cfg.CSV_DIR) / "eaves_params.csv"
    summary_path = Path(_cfg.CSV_DIR) / "eaves_summary.csv"
    if not params_path.exists() or not summary_path.exists():
        raise RuntimeError(
            "eaves_params.csv or eaves_summary.csv missing -- run the "
            "regionalization step first."
        )
    params_df  = pd.read_csv(params_path)
    summary_df = pd.read_csv(summary_path)

    loo_path = Path(_cfg.CSV_DIR) / "validation" / "regionalization_loo.csv"
    loo_df = pd.read_csv(loo_path) if loo_path.exists() else None

    b_sigma = compute_b_sigma(summary_df)
    sigma_log_acap = compute_sigma_log_acap(loo_df)
    sigma_log_vcap = compute_sigma_log_vcap(summary_df)
    print(f"  b_sigma (population 1-sigma on b)            = {b_sigma:.4f} log10 units")
    print(f"  sigma_log_acap (A_cap LOO regression error)  = {sigma_log_acap:.4f} log10 units")
    print(f"  sigma_log_vcap (catalog-capacity error)      = {sigma_log_vcap:.4f} log10 units")

    df = compute_uncertainty_table(params_df, b_sigma, sigma_log_acap, sigma_log_vcap)

    out_dir = Path(_cfg.CSV_DIR) / "validation"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "v_uncertainty.csv"
    df.to_csv(out_path, index=False)

    print(f"wrote {out_path}  ({len(df)} dams)")
    if len(df) > 0:
        for tier in ("srtm_derived", "regi_multi"):
            sub = df[df["source"] == tier]
            if len(sub) == 0:
                continue
            print(f"  --- {tier} (n={len(sub)}) ---")
            for label in _FILL_LEVELS:
                med_log10 = sub[f"V_sigma_log10_{label}"].median()
                med_up  = sub[f"V_frac_up_{label}"].median()
                med_dn  = sub[f"V_frac_down_{label}"].median()
                print(f"    median sigma at {label:<12s}: {med_log10:.3f} log10 units  "
                      f"(+{med_up*100:.0f}% / -{med_dn*100:.0f}%)")
    return df


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--settings", required=True,
                   help="Path to region settings JSON.")
    args = p.parse_args(argv)
    run(settings_path=args.settings)


if __name__ == "__main__":
    main()
