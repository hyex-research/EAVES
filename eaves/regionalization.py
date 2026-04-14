"""Regionalization: reliability tagging, threshold analysis, parameter assignment."""

from __future__ import annotations

import os

import numpy as np
import pandas as pd

import eaves.config as _cfg
from .utils import fit_power_law
from .plots import plot_threshold_analysis, plot_regression_diagnostics

try:
    from sklearn.linear_model import LinearRegression
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.model_selection import LeaveOneOut
    from sklearn.metrics import r2_score, mean_absolute_error
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False


def assign_quality(row):
    """Grade a dam's EAV curve quality A..F."""
    vr = row["vol_ratio"]
    zrr = row.get("z_range_ratio", np.nan)
    if np.isnan(row.get("b", np.nan)):
        return "F"
    if row["spillway_height_m"] < 3 or row["n_pixels"] < 20:
        return "D"
    if (not np.isnan(zrr) and zrr > 3) or vr > 10:
        return "D"
    if vr > 5 or vr < 0.1:
        return "C"
    if 0.5 <= vr <= 2.0 and row["r_squared"] >= 0.99:
        return "A"
    if 0.3 <= vr <= 5.0:
        return "B"
    return "C"


def run_regionalization(summary_df, failures, dam_data_list):
    """Assign EAV parameters to every dam.

    Returns a ``pd.DataFrame`` with columns ``dam_id, dam_name, c, b, source, capacity_mcm, r_squared``.
    Saves ``eaves_params.csv`` and ``threshold_analysis.csv``.
    """
    print("\n" + "=" * 70)
    print("  REGIONALIZATION")
    print("=" * 70)

    if len(summary_df) == 0 or "b" not in summary_df.columns:
        print("  [WARN] No successful dams \u2014 skipping regionalization.")
        print("=" * 70)
        return pd.DataFrame()

    # --- Step A: Tag reliable dams ---
    summary_df["reliable"] = (
        summary_df["quality"].isin(["A", "B"])
        & (summary_df["r_squared"] >= 0.98)
        & summary_df["vol_ratio"].between(0.3, 5.0)
        & (summary_df["n_pixels"] >= 50)
        & summary_df["b"].notna()
    )

    # --- Step B: Determine reliability threshold ---
    thresholds = np.arange(1.0, 20.5, 0.5)
    threshold_results = []
    for T in thresholds:
        above = summary_df[summary_df["capacity_mcm"] >= T]
        n_above = len(above)
        n_reliable = int(above["reliable"].sum()) if n_above > 0 else 0
        frac = n_reliable / n_above if n_above > 0 else 0
        threshold_results.append({
            "threshold_mcm": T, "n_above": n_above,
            "n_reliable": n_reliable, "frac_reliable": frac,
        })
    threshold_df = pd.DataFrame(threshold_results)

    candidates_thr = threshold_df[
        (threshold_df["frac_reliable"] >= 0.80) & (threshold_df["n_above"] >= 30)
    ]
    if len(candidates_thr) > 0:
        chosen_threshold = float(candidates_thr.iloc[0]["threshold_mcm"])
    else:
        candidates_thr = threshold_df[
            (threshold_df["frac_reliable"] >= 0.70) & (threshold_df["n_above"] >= 20)
        ]
        if len(candidates_thr) > 0:
            chosen_threshold = float(candidates_thr.iloc[0]["threshold_mcm"])
        else:
            chosen_threshold = 5.0
            print("  [WARN] Could not determine optimal threshold, using 5 MCM default.")

    print(f"\n  Chosen reliability threshold: {chosen_threshold:.1f} MCM")
    threshold_df.to_csv(os.path.join(_cfg.CSV_DIR, "threshold_analysis.csv"), index=False)

    plot_threshold_analysis(summary_df, threshold_df, chosen_threshold, _cfg.PLOT_DIR)

    # --- Step C: Fit regression for b ---
    features = ["valley_ratio", "channel_slope", "mean_catchment_slope", "dam_height_m"]
    train = summary_df[
        (summary_df["capacity_mcm"] >= chosen_threshold) & (summary_df["reliable"])
    ].copy()
    train_clean = train.dropna(subset=features + ["b"])

    print(f"  Training set: {len(train_clean)} dams with complete features")

    use_regression = False
    best_model = None
    best_model_name = "regional_median"
    best_r2_val = 0.0

    if HAS_SKLEARN and len(train_clean) >= 15:
        X = train_clean[features].values
        y = train_clean["b"].values

        loo = LeaveOneOut()
        lr_preds = np.zeros(len(y))
        rf_preds = np.zeros(len(y))

        for tr_idx, te_idx in loo.split(X):
            lr_preds[te_idx] = LinearRegression().fit(
                X[tr_idx], y[tr_idx]
            ).predict(X[te_idx])
            rf_preds[te_idx] = RandomForestRegressor(
                n_estimators=100, max_depth=4, random_state=42
            ).fit(X[tr_idx], y[tr_idx]).predict(X[te_idx])

        lr_r2 = r2_score(y, lr_preds)
        rf_r2 = r2_score(y, rf_preds)
        lr_mae = mean_absolute_error(y, lr_preds)
        rf_mae = mean_absolute_error(y, rf_preds)

        print(f"  Linear  LOO: R\u00b2={lr_r2:.3f}, MAE={lr_mae:.4f}")
        print(f"  RF      LOO: R\u00b2={rf_r2:.3f}, MAE={rf_mae:.4f}")

        best_r2_val = max(lr_r2, rf_r2)
        if best_r2_val >= 0.25:
            use_regression = True
            if rf_r2 >= lr_r2:
                best_model = RandomForestRegressor(
                    n_estimators=100, max_depth=4, random_state=42
                ).fit(X, y)
                best_model_name = "random_forest"
                best_preds = rf_preds
            else:
                best_model = LinearRegression().fit(X, y)
                best_model_name = "linear_regression"
                best_preds = lr_preds
            print(f"  Selected model: {best_model_name} (LOO R\u00b2={best_r2_val:.3f})")

            if best_model_name == "random_forest":
                importances = best_model.feature_importances_
            else:
                importances = np.abs(best_model.coef_)
                imp_sum = importances.sum()
                if imp_sum > 0:
                    importances = importances / imp_sum

            plot_regression_diagnostics(
                y, best_preds, train_clean, features, importances,
                best_model_name, best_r2_val, _cfg.PLOT_DIR,
            )
        else:
            print("  Both models below R\u00b2=0.25, falling back to regional median b.")
    elif not HAS_SKLEARN:
        print("  [WARN] scikit-learn not installed, using regional median b.")
    else:
        print(f"  Too few training dams ({len(train_clean)}), using regional median b.")

    regional_median_b = float(train_clean["b"].median()) if len(train_clean) > 0 else 1.35
    regional_median_c = float(train_clean["c"].median()) if len(train_clean) > 0 else 0.06
    print(f"  Regional median b = {regional_median_b:.4f}")

    # --- Step D: A_cap empirical fallback ---
    a_cap_fallback_coef = None
    if len(train_clean) >= 10 and "footprint_area_km2" in train_clean.columns:
        log_cap = np.log(train_clean["capacity_mcm"].values)
        log_area = np.log(train_clean["footprint_area_km2"].values)
        valid_mask = np.isfinite(log_cap) & np.isfinite(log_area)
        if valid_mask.sum() >= 10:
            from numpy.polynomial.polynomial import polyfit
            coefs = polyfit(log_cap[valid_mask], log_area[valid_mask], 1)
            a_cap_fallback_coef = coefs

    # --- Step E: Assign parameters to every dam ---
    param_rows = []

    # (a) Reliable dams: SRTM-derived
    for _, row in summary_df[summary_df["reliable"]].iterrows():
        param_rows.append({
            "dam_id": row["dam_id"],
            "dam_name": row.get("dam_name", ""),
            "c": row["c"],
            "b": row["b"],
            "source": "srtm_direct",
            "capacity_mcm": row["capacity_mcm"],
            "r_squared": row["r_squared"],
        })

    # (b) Unreliable SRTM dams
    need_region = summary_df[~summary_df["reliable"]].copy()

    # (c) Failed dams with topo features
    fail_feature_rows = []
    for f in failures:
        dam_id_f = f.get("dam_id", "")
        dam_d = next((d for d in dam_data_list if d.get("dam_id") == dam_id_f), None)
        if dam_d is None:
            continue
        fail_feature_rows.append({
            "dam_id": dam_id_f,
            "dam_name": f.get("dam_name", dam_d.get("dam_name_latin", "")),
            "capacity_mcm": float(dam_d.get("storage_capacity_m3", 0)) / 1e6,
            "dam_height_m": float(dam_d.get("dam_height_m", 0)),
            "spillway_height_m": float(dam_d.get("spillway_height_m", 0)),
            "valley_ratio": f.get("valley_ratio", np.nan),
            "channel_slope": f.get("channel_slope", np.nan),
            "mean_catchment_slope": f.get("mean_catchment_slope", np.nan),
            "lat": dam_d.get("_lat", np.nan),
            "lon": dam_d.get("_lon", np.nan),
        })

    dams_to_regionalize = []
    for _, row in need_region.iterrows():
        dams_to_regionalize.append({
            "dam_id": row["dam_id"],
            "dam_name": row.get("dam_name", ""),
            "capacity_mcm": row["capacity_mcm"],
            "dam_height_m": row.get("dam_height_m", np.nan),
            "spillway_height_m": row.get("spillway_height_m", np.nan),
            "valley_ratio": row.get("valley_ratio", np.nan),
            "channel_slope": row.get("channel_slope", np.nan),
            "mean_catchment_slope": row.get("mean_catchment_slope", np.nan),
            "lat": row.get("lat", np.nan),
            "lon": row.get("lon", np.nan),
        })
    dams_to_regionalize.extend(fail_feature_rows)

    region_df = pd.DataFrame(dams_to_regionalize)

    if len(region_df) > 0:
        if use_regression:
            for feat in features:
                median_val = train_clean[feat].median()
                region_df[feat] = region_df[feat].fillna(median_val)
            X_predict = region_df[features].values
            b_predicted = best_model.predict(X_predict)
            region_df["b"] = np.clip(b_predicted, 1.1, 2.0)
            region_df["source"] = "regression"
        else:
            region_df["b"] = regional_median_b
            region_df["source"] = "regional_median"

        for idx_r, row_r in region_df.iterrows():
            dam_id_r = row_r["dam_id"]
            capacity_m3_r = row_r["capacity_mcm"] * 1e6
            b_val = row_r["b"]
            A_cap_m2 = np.nan

            sat_path = os.path.join(_cfg.WATER_EXTENT_DIR, f"{dam_id_r}_ts_filtered.csv")
            if os.path.isfile(sat_path):
                try:
                    sat_df = pd.read_csv(sat_path)
                    if "water_area_km2" in sat_df.columns:
                        areas = sat_df["water_area_km2"].dropna()
                        if len(areas) > 5:
                            A_cap_km2 = float(areas.quantile(0.95))
                            A_cap_m2 = A_cap_km2 * 1e6
                except Exception:
                    pass

            if np.isnan(A_cap_m2) and a_cap_fallback_coef is not None:
                cap_mcm = row_r["capacity_mcm"]
                if np.isfinite(cap_mcm) and cap_mcm > 0:
                    log_a = (a_cap_fallback_coef[0]
                             + a_cap_fallback_coef[1] * np.log(cap_mcm))
                    A_cap_km2 = np.exp(log_a)
                    A_cap_m2 = A_cap_km2 * 1e6

            c_val = np.nan
            if np.isfinite(A_cap_m2) and A_cap_m2 > 0 and np.isfinite(b_val):
                c_val = capacity_m3_r / (A_cap_m2 ** b_val)
                v_check = c_val * (A_cap_m2 ** b_val)
                if v_check <= 0 or v_check > 2.0 * capacity_m3_r or v_check < 0.5 * capacity_m3_r:
                    c_val = regional_median_c
                    region_df.at[idx_r, "b"] = regional_median_b
                    region_df.at[idx_r, "source"] = "regional_median"

            if np.isnan(c_val) or c_val <= 0:
                c_val = regional_median_c
                region_df.at[idx_r, "b"] = regional_median_b
                region_df.at[idx_r, "source"] = "regional_median"

            region_df.at[idx_r, "c"] = c_val

        for _, row_r in region_df.iterrows():
            param_rows.append({
                "dam_id": row_r["dam_id"],
                "dam_name": row_r.get("dam_name", ""),
                "c": row_r["c"],
                "b": row_r["b"],
                "source": row_r["source"],
                "capacity_mcm": row_r["capacity_mcm"],
                "r_squared": np.nan,
            })

    # --- Override Baish with sonar bathymetry ---
    params_df = pd.DataFrame(param_rows)
    if os.path.isfile(_cfg.BAYSH_EAV_CSV) and len(params_df) > 0:
        bathy = pd.read_csv(_cfg.BAYSH_EAV_CSV)
        c_bathy, b_bathy, _ = fit_power_law(
            bathy["area_m2_integrated_dem"].values,
            bathy["volume_m3_integrated_dem"].values,
        )
        if np.isfinite(c_bathy) and np.isfinite(b_bathy):
            baysh_mask = params_df["dam_id"].str.contains("120000", case=False, na=False)
            if baysh_mask.any():
                params_df.loc[baysh_mask, "c"] = c_bathy
                params_df.loc[baysh_mask, "b"] = b_bathy
                params_df.loc[baysh_mask, "source"] = "baish_sonar"
                print(f"  Baish overridden with sonar: c={c_bathy:.5g}, b={b_bathy:.4f}")

    params_df["b"] = params_df["b"].clip(1.1, 2.0)

    # --- Save ---
    params_path = os.path.join(_cfg.CSV_DIR, "eaves_params.csv")
    params_df.to_csv(params_path, index=False)

    print(f"\n  Parameter assignment complete:")
    print(f"    Total dams with parameters: {len(params_df)}")
    for src_name, count in params_df["source"].value_counts().items():
        print(f"    {src_name}: {count} dams")
    direct = params_df[params_df["source"] == "srtm_direct"]
    other = params_df[params_df["source"] != "srtm_direct"]
    if len(direct) > 0:
        print(f"    Median b (SRTM direct): {direct['b'].median():.4f}")
    if len(other) > 0:
        print(f"    Median b (regionalized): {other['b'].median():.4f}")
    print(f"\n  Saved: eaves_params.csv ({len(params_df)} dams)")
    print("=" * 70)

    return params_df
