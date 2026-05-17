"""Per-dam V uncertainty propagation from ``b_sigma``.

For every dam in ``eaves_params.csv``, propagates the 1$\\sigma$ uncertainty
on $b$ (the LOO noise floor, identical for every dam) into a 1$\\sigma$
uncertainty band on V at three standard fill levels:

- half pool   (A = 0.50 A_cap)
- quarter pool (A = 0.25 A_cap)
- tenth pool  (A = 0.10 A_cap)

The band is forced through the catalogue anchor $(A_\\mathrm{cap}, V_\\mathrm{cap})$
by construction, so at A = A_cap the uncertainty is exactly zero. Away from
the anchor it grows as $\\sigma(\\log_{10}V) = b_\\sigma \\cdot |\\log_{10}(A/A_\\mathrm{cap})|$.

The single output is ``<CSV_DIR>/validation/v_uncertainty.csv``, a flat
per-dam table with the dex sigma and the equivalent percentage upper bound
at each of the three fill levels.

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
    """Population 1$\\sigma$ half-width on $b$ from the trusted-set.

    Equal to the LOO baseline sigma for predicting $b$ from the global
    median (they are mathematically the same quantity), and the single
    region-level number that propagates into every per-dam V band below.
    """
    m = (summary_df["quality"].isin(["A", "B"])
         & (summary_df["r_squared"] >= 0.98)
         & summary_df["vol_ratio"].between(0.3, 5.0)
         & (summary_df["n_pixels"] >= 50)
         & summary_df["b"].notna())
    b = summary_df.loc[m, "b"].dropna()
    if len(b) < 10:
        return 0.25
    return float((b.quantile(0.84) - b.quantile(0.16)) / 2.0)


def _a_cap_m2(c: float, b: float, capacity_mcm: float) -> float:
    """Implicit anchor area: solve V_cap = c * A_cap^b for A_cap."""
    V_cap_m3 = capacity_mcm * 1e6
    return float((V_cap_m3 / c) ** (1.0 / b))


def _v_sigma_dex(b_sigma: float, fill_frac: float) -> float:
    """1-sigma uncertainty on log10(V) at A = fill_frac * A_cap."""
    return float(b_sigma * abs(np.log10(fill_frac)))


def compute_uncertainty_table(params_df: pd.DataFrame,
                              b_sigma: float) -> pd.DataFrame:
    """Return one row per dam with V uncertainty at the three fill levels."""
    rows = []
    for _, p in params_df.iterrows():
        c = float(p["c"])
        b = float(p["b"])
        cap = float(p["capacity_mcm"])
        if not (np.isfinite(c) and np.isfinite(b) and c > 0 and b > 0 and cap > 0):
            continue
        a_cap = _a_cap_m2(c, b, cap)
        v_cap = cap * 1e6
        row = {
            "dam_id":       p["dam_id"],
            "source":       p["source"],
            "capacity_mcm": cap,
            "b":            b,
            "b_sigma":      b_sigma,
            "A_cap_km2":    a_cap / 1e6,
        }
        for label, frac in _FILL_LEVELS.items():
            sigma_dex = _v_sigma_dex(b_sigma, frac)
            v_pred_m3 = c * (a_cap * frac) ** b
            row[f"V_pred_{label}_mcm"]   = v_pred_m3 / 1e6
            row[f"V_sigma_dex_{label}"]  = sigma_dex
            row[f"V_pct_up_{label}"]     = (10.0**sigma_dex - 1.0) * 100.0
            row[f"V_pct_down_{label}"]   = (1.0 - 10.0**(-sigma_dex)) * 100.0
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

    b_sigma = compute_b_sigma(summary_df)
    print(f"  b_sigma (population 1-sigma on b) = {b_sigma:.4f} dex")

    df = compute_uncertainty_table(params_df, b_sigma)

    out_dir = Path(_cfg.CSV_DIR) / "validation"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "v_uncertainty.csv"
    df.to_csv(out_path, index=False)

    print(f"wrote {out_path}  ({len(df)} dams)")
    if len(df) > 0:
        for label in _FILL_LEVELS:
            med_dex = df[f"V_sigma_dex_{label}"].median()
            med_pct = df[f"V_pct_up_{label}"].median()
            print(f"  median sigma at {label:<12s}: {med_dex:.3f} dex  "
                  f"(+{med_pct:.0f}% / -{(1 - 10**(-med_dex))*100:.0f}%)")
    return df


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--settings", required=True,
                   help="Path to region settings JSON.")
    args = p.parse_args(argv)
    run(settings_path=args.settings)


if __name__ == "__main__":
    main()
