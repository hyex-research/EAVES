"""Regionalization: reliability tagging, threshold analysis, parameter assignment."""

from __future__ import annotations

import os

import numpy as np
import pandas as pd

import eaves.config as _cfg
# note: diagnostic plots (threshold_analysis, regression_diagnostics) are
# rendered by the panels step in production, not by run_regionalization
# itself, so this module emits CSVs only.

try:
    from sklearn.linear_model import LinearRegression
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.model_selection import LeaveOneOut
    from sklearn.metrics import r2_score, mean_absolute_error
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False


# Features used by the multi-feature LR anchor for A_cap. All entered in
# log-space. Missing features are median-imputed at predict time so the
# regression always returns a finite value. The trusted-set LOO accuracy of
# this recipe is documented in panel p5 and in the EAVES report.
_REGIONAL_FEATURES = (
    "capacity_mcm",
    "dam_height_m",
    "spillway_height_m",
    "valley_ratio",
    "channel_slope",
    "mean_catchment_slope",
    "upstream_area_km2",
)
_REGIONAL_FEATURE_FLOOR = 1e-5    # log-space floor for slopes etc.


def _log_feature_vector(row, features=_REGIONAL_FEATURES):
    """Return log-space feature vector or ``None`` if any feature is missing."""
    out = []
    for f in features:
        v = row.get(f) if isinstance(row, dict) else (
            row[f] if f in row else None
        )
        try:
            v = float(v)
        except (TypeError, ValueError):
            return None
        if not np.isfinite(v) or v <= 0:
            return None
        out.append(np.log(max(v, _REGIONAL_FEATURE_FLOOR)))
    return np.asarray(out, dtype=float)


def _fit_multi_anchor_lr_full(train_df, features=_REGIONAL_FEATURES, min_n=8):
    """Fit the multi-feature LR and return everything needed for prediction
    intervals.

    Returns a ``dict`` with keys ``coefs``, ``residual_var``, ``XtX_inv`` or
    ``None`` if the trusted set is too small after dropping rows with missing
    features.
    """
    rows = []
    targets = []
    if "footprint_area_km2" not in train_df.columns:
        return None
    for _, r in train_df.iterrows():
        v = _log_feature_vector(r, features)
        if v is None:
            continue
        a = r.get("footprint_area_km2")
        try:
            a = float(a)
        except (TypeError, ValueError):
            continue
        if not np.isfinite(a) or a <= 0:
            continue
        rows.append(v)
        targets.append(np.log(a))
    if len(rows) < min_n:
        return None
    X = np.array(rows)
    y = np.array(targets)
    X_int = np.column_stack([np.ones(len(X)), X])
    coefs, *_ = np.linalg.lstsq(X_int, y, rcond=None)
    resid = y - X_int @ coefs
    n, p_plus1 = X_int.shape
    residual_var = (float(np.sum(resid ** 2) / (n - p_plus1))
                    if n > p_plus1 else 0.0)
    try:
        XtX_inv = np.linalg.inv(X_int.T @ X_int)
    except np.linalg.LinAlgError:
        XtX_inv = None
    return {"coefs": coefs, "residual_var": residual_var, "XtX_inv": XtX_inv}


def _fit_multi_anchor_lr(train_df, features=_REGIONAL_FEATURES, min_n=8):
    """Back-compat wrapper: returns just the coefficient array."""
    fit = _fit_multi_anchor_lr_full(train_df, features, min_n)
    return fit["coefs"] if fit is not None else None


def _predict_log_a_with_sigma(row, fit, features=_REGIONAL_FEATURES):
    """Predict ``log A_cap`` (natural log, km^2) with 1-sigma prediction error.

    Returns ``(log_A, sigma_log_A)`` or ``(None, None)`` if any required
    feature is missing or the fit object lacks the design-matrix inverse.
    """
    if fit is None or fit.get("XtX_inv") is None:
        return None, None
    v = _log_feature_vector(row, features)
    if v is None:
        return None, None
    x_new = np.concatenate([[1.0], v])
    log_a = float(fit["coefs"] @ x_new)
    var_pred = fit["residual_var"] * (1.0 + float(x_new @ fit["XtX_inv"] @ x_new))
    return log_a, float(np.sqrt(max(var_pred, 0.0)))


def _predict_multi_anchor_lr(row, coefs, features=_REGIONAL_FEATURES):
    """Predict full-pool area (km^2) from the multi-LR anchor."""
    if coefs is None:
        return None
    v = _log_feature_vector(row, features)
    if v is None:
        return None
    log_a = float(coefs[0] + float(np.dot(coefs[1:], v)))
    return float(np.exp(log_a))




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

            # Diagnostic plot of the regression is rendered separately by
            # the panels step, not here -- run_regionalization stays a pure
            # parameter-assignment function.
        else:
            print("  Both models below R\u00b2=0.25, falling back to regional median b.")
    elif not HAS_SKLEARN:
        print("  [WARN] scikit-learn not installed, using regional median b.")
    else:
        print(f"  Too few training dams ({len(train_clean)}), using regional median b.")

    regional_median_b = float(train_clean["b"].median()) if len(train_clean) > 0 else 1.35
    regional_median_c = float(train_clean["c"].median()) if len(train_clean) > 0 else 0.06
    print(f"  Regional median b = {regional_median_b:.4f}")

    # --- Step D: multi-feature LR anchor for A_cap ---
    # Single recipe: log A_cap regressed on every feature in
    # `_REGIONAL_FEATURES` in log space, trained on the trusted DEM
    # footprints. Any feature missing for a regionalised dam is imputed with
    # the training-set median so the predictor never short-circuits.
    #
    # The anchor uses the FULL trusted set (every dam tagged ``reliable``),
    # not the capacity-thresholded ``train_clean`` subset that drives the
    # b-regression: small fixtures and small regions otherwise drop below
    # the multi-LR's min_n and lose the recipe entirely.
    trusted_full = summary_df[summary_df["reliable"]].copy()
    multi_fit = _fit_multi_anchor_lr_full(trusted_full)
    a_cap_multi_coef = multi_fit["coefs"] if multi_fit is not None else None
    if multi_fit is not None:
        print(f"  Multi-LR A_cap fit:  {len(_REGIONAL_FEATURES)} features, "
              f"intercept={a_cap_multi_coef[0]:+.3f}, "
              f"residual sigma={np.sqrt(multi_fit['residual_var']):.3f} (ln-space)")
    else:
        print("  [WARN] Multi-LR A_cap fit could not be trained (fewer than "
              "8 trusted dams with all features). Regionalization will fail "
              "loudly only if a dam actually needs regionalising.")

    # 1-sigma uncertainty in b from the trusted-set distribution. Used by
    # quadrature to inflate the c uncertainty (since c = V_cap / A_cap^b).
    b_sigma = (float((trusted_full["b"].quantile(0.84)
                       - trusted_full["b"].quantile(0.16)) / 2.0)
               if len(trusted_full) else 0.25)

    feature_medians = {
        f: float(trusted_full[f].dropna().median())
        for f in _REGIONAL_FEATURES if f in trusted_full.columns
    }

    # --- Step E: Assign parameters to every dam ---
    param_rows = []

    # (a) Reliable dams: SRTM-derived
    for _, row in summary_df[summary_df["reliable"]].iterrows():
        param_rows.append({
            "dam_id": row["dam_id"],
            "dam_name": row.get("dam_name", ""),
            "capacity_mcm": row["capacity_mcm"],
            "c": row["c"],
            "b": row["b"],
            "source": "srtm_derived",
        })

    # (b) Unreliable SRTM dams
    need_region = summary_df[~summary_df["reliable"]].copy()

    # (c) Failed dams with topo features. Skip any dam already represented in
    # summary_df: a fit_failed dam still has a summary row (with NaN b), which
    # means it's already in need_region — adding it again from failures would
    # write a duplicate params row.
    summary_ids = set(summary_df["dam_id"])
    fail_feature_rows = []
    for f in failures:
        dam_id_f = f.get("dam_id", "")
        if dam_id_f in summary_ids:
            continue
        dam_d = next((d for d in dam_data_list if d.get("dam_id") == dam_id_f), None)
        if dam_d is None:
            continue
        fail_feature_rows.append({
            "dam_id": dam_id_f,
            "dam_name": f.get("dam_name", dam_d.get("dam_name_latin", "")),
            "capacity_mcm": float(dam_d.get("storage_capacity_m3", 0)) / 1e6,
            "dam_height_m": float(dam_d.get("dam_height_m", 0)),
            "spillway_height_m": float(dam_d.get("spillway_height_m", 0)),
            "dam_length_m": float(dam_d.get("dam_length_m") or np.nan),
            "valley_ratio": f.get("valley_ratio", np.nan),
            "channel_slope": f.get("channel_slope", np.nan),
            "mean_catchment_slope": f.get("mean_catchment_slope", np.nan),
            "upstream_area_km2": f.get("upstream_area_km2", np.nan),
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
            "dam_length_m": row.get("dam_length_m", np.nan),
            "valley_ratio": row.get("valley_ratio", np.nan),
            "channel_slope": row.get("channel_slope", np.nan),
            "mean_catchment_slope": row.get("mean_catchment_slope", np.nan),
            "upstream_area_km2": row.get("upstream_area_km2", np.nan),
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
            region_df["source"] = "regr_derived"
        else:
            region_df["b"] = regional_median_b
            region_df["source"] = "regi_multi"

        # Median-impute any missing regionalisation feature so the multi-LR
        # never short-circuits at predict time.
        for feat, med in feature_medians.items():
            if feat in region_df.columns:
                region_df[feat] = region_df[feat].where(
                    region_df[feat].notna() & (region_df[feat] > 0), med,
                )

        # Multi-feature LR anchor for A_cap, back-solving c = V_cap / A_cap^b.
        # The anchor enforces V(A_cap_pred) = V_cap exactly; uncertainty
        # away from the anchor is driven by b_sigma and is propagated
        # downstream by the dedicated uncertainty module.
        for idx_r, row_r in region_df.iterrows():
            capacity_m3_r = row_r["capacity_mcm"] * 1e6
            b_val = row_r["b"]
            log_a_ln, _ = _predict_log_a_with_sigma(row_r, multi_fit)
            if (log_a_ln is None or not np.isfinite(log_a_ln)
                    or not np.isfinite(b_val)):
                raise RuntimeError(
                    f"Multi-LR anchor failed for dam {row_r['dam_id']!r} "
                    "after median imputation -- this should not happen and "
                    "indicates a bug or fully-degenerate inputs."
                )
            A_cap_m2 = float(np.exp(log_a_ln)) * 1e6
            region_df.at[idx_r, "c"] = capacity_m3_r / (A_cap_m2 ** b_val)
            region_df.at[idx_r, "source"] = "regi_multi"

        for _, row_r in region_df.iterrows():
            param_rows.append({
                "dam_id": row_r["dam_id"],
                "dam_name": row_r.get("dam_name", ""),
                "capacity_mcm": row_r["capacity_mcm"],
                "c": row_r["c"],
                "b": row_r["b"],
                "source": row_r["source"],
            })

    params_df = pd.DataFrame(param_rows)
    params_df["b"] = params_df["b"].clip(1.1, 2.0)
    params_df = params_df[[
        "dam_id", "dam_name", "capacity_mcm", "c", "b", "source",
    ]]

    dup_mask = params_df["dam_id"].duplicated(keep=False)
    if dup_mask.any():
        dup_ids = sorted(set(params_df.loc[dup_mask, "dam_id"]))
        print(f"  [WARN] Dropped duplicate param rows for {len(dup_ids)} dams: "
              f"{dup_ids[:5]}{'...' if len(dup_ids) > 5 else ''}")
        params_df = params_df.drop_duplicates(subset="dam_id", keep="first").reset_index(drop=True)

    # --- Save (sorted by dam_id for deterministic, human-readable output) ---
    params_df = params_df.sort_values("dam_id", kind="stable").reset_index(drop=True)
    params_path = os.path.join(_cfg.CSV_DIR, "eaves_params.csv")
    params_df.to_csv(params_path, index=False)

    print(f"\n  Parameter assignment complete:")
    print(f"    Total dams with parameters: {len(params_df)}")
    for src_name, count in params_df["source"].value_counts().items():
        print(f"    {src_name}: {count} dams")
    direct = params_df[params_df["source"] == "srtm_derived"]
    other = params_df[params_df["source"] != "srtm_derived"]
    if len(direct) > 0:
        print(f"    Median b (SRTM-derived): {direct['b'].median():.4f}")
    if len(other) > 0:
        print(f"    Median b (regionalized): {other['b'].median():.4f}")
    print(f"\n  Saved: eaves_params.csv ({len(params_df)} dams)")
    print("=" * 70)

    return params_df
