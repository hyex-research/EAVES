"""Regionalization: reliability tagging and parameter assignment.

Tags trusted SRTM fits (grade, R^2, volume-ratio, and pixel gates), sweeps
the capacity threshold behind the reliability cut, assigns (c, b) to the
remaining dams from the regional median b and a multi-feature linear
regression anchor for A_cap, clamps b to [1.1, 2.0] with c re-solved
through the full-pool anchor, and writes ``eaves_params.csv`` plus the
threshold and clustering diagnostics.
"""

from __future__ import annotations

import os

import numpy as np
import pandas as pd

import eaves.config as _cfg
# Diagnostic plots are rendered by the panels step; this module emits CSVs only.

try:
    from sklearn.linear_model import LinearRegression
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.model_selection import LeaveOneOut
    from sklearn.metrics import r2_score, mean_absolute_error
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False


# Log-space features for the multi-LR A_cap anchor; missing values median-imputed at predict time.
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




def acap_regression_diagnostics(summary_df, out_dir):
    """Collinearity + incremental-skill diagnostics for the A_cap regression.

    Pure diagnostic. Reports, for the multi-feature $\\log A_\\mathrm{cap}$
    anchor used in deployment (see :data:`_REGIONAL_FEATURES`), three things
    the statistician asked for, **without dropping any feature** from the
    deployed recipe:

    1. **Variance-inflation factors (VIF) and the condition number** of the
       7 standardized log-features on the trusted training set. A VIF above
       ~5--10, or a condition number above ~30, signals collinearity.
    2. **Incremental leave-one-out skill** as features are added one at a time
       in the deployed order (1 -> 7). Skill is the LOO root-mean-square
       residual of $\\log_{10} A_\\mathrm{cap}$ (log10 units), so smaller is better;
       the marginal value of each extra feature is ``delta_loo_rms``.
    3. The same incremental sweep **with catalogue capacity** ($V_\\mathrm{cap}$,
       the ``capacity_mcm`` feature) **excluded**, to show how much skill the
       six purely-geometric features retain once the anchor target's own
       capacity is removed from the inputs.

    Writes ``acap_regression_diagnostics.csv`` (one row per diagnostic) and
    returns the DataFrame. The deployed model in
    :func:`run_regionalization` is untouched.
    """
    feats = list(_REGIONAL_FEATURES)
    reliable = (summary_df["reliable"] if "reliable" in summary_df.columns
                else _reliable_default(summary_df))
    rows_X, y = [], []
    for _, r in summary_df[reliable].iterrows():
        v = _log_feature_vector(r, feats)
        a = r.get("footprint_area_km2")
        try:
            a = float(a)
        except (TypeError, ValueError):
            a = np.nan
        if v is None or not np.isfinite(a) or a <= 0:
            continue
        rows_X.append(v)
        y.append(np.log(a))
    X = np.asarray(rows_X, dtype=float)
    y = np.asarray(y, dtype=float)
    n = len(y)

    records = []

    # --- (1) VIF and condition number on standardized log-features ---
    if n > len(feats) + 1:
        Xc = X - X.mean(axis=0)
        sd = Xc.std(axis=0, ddof=1)
        sd[sd == 0] = 1.0
        Xs = Xc / sd
        # condition number of the standardized design (no intercept):
        sv = np.linalg.svd(Xs, compute_uv=False)
        cond_number = float(sv.max() / sv.min()) if sv.min() > 0 else np.inf
        corr = np.corrcoef(Xs, rowvar=False)
        try:
            vif = np.diag(np.linalg.inv(corr))
        except np.linalg.LinAlgError:
            vif = np.full(len(feats), np.nan)
        for f, v in zip(feats, vif):
            records.append({
                "diagnostic": "vif", "feature": f, "n_features": "",
                "value": float(v), "metric": "VIF",
            })
        records.append({
            "diagnostic": "condition_number", "feature": "(7 log-features)",
            "n_features": len(feats), "value": cond_number,
            "metric": "condition_number_standardized_design",
        })

    # --- (2) + (3) incremental leave-one-out skill ---
    def _loo_rms_log10(Xsub):
        """LOO RMS residual of log10 A_cap (log10 units) for an OLS with intercept."""
        if Xsub.shape[1] == 0:
            Xi = np.ones((n, 1))
        else:
            Xi = np.column_stack([np.ones(n), Xsub])
        if n <= Xi.shape[1]:
            return np.nan
        resid = np.empty(n)
        idx = np.arange(n)
        for i in range(n):
            tr = idx != i
            coef, *_ = np.linalg.lstsq(Xi[tr], y[tr], rcond=None)
            resid[i] = y[i] - Xi[i] @ coef
        # natural-log residual -> log10 units
        return float(np.sqrt(np.mean(resid ** 2)) / np.log(10.0))

    def _incremental(order_idx, tag):
        prev = None
        for k in range(1, len(order_idx) + 1):
            cols = order_idx[:k]
            rms = _loo_rms_log10(X[:, cols])
            delta = (prev - rms) if (prev is not None and np.isfinite(rms)
                                     and np.isfinite(prev)) else np.nan
            records.append({
                "diagnostic": tag,
                "feature": feats[order_idx[k - 1]],
                "n_features": k,
                "value": rms,
                "metric": "loo_rms_log10",
                "delta_loo_rms_log10": delta,
            })
            prev = rms

    # full deployed order, 1->7
    _incremental(list(range(len(feats))), "incremental_loo")
    # capacity (V_cap) excluded: keep the other six in deployed order
    cap_i = feats.index("capacity_mcm")
    no_cap_order = [i for i in range(len(feats)) if i != cap_i]
    _incremental(no_cap_order, "incremental_loo_no_capacity")

    out = pd.DataFrame(records)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "acap_regression_diagnostics.csv")
    out.to_csv(out_path, index=False)

    print("\n" + "=" * 70)
    print("  A_cap REGRESSION DIAGNOSTICS (collinearity + incremental skill)")
    print("=" * 70)
    print(f"  Trusted training dams: {n}")
    vif_rows = out[out["diagnostic"] == "vif"]
    if len(vif_rows):
        print("  VIF (standardized log-features):")
        for _, r in vif_rows.iterrows():
            print(f"    {r['feature']:<22s} {r['value']:6.2f}")
    cn = out[out["diagnostic"] == "condition_number"]
    if len(cn):
        print(f"  Condition number (standardized design): {cn['value'].iloc[0]:.1f}")
    for tag, lab in (("incremental_loo", "1->7 features"),
                     ("incremental_loo_no_capacity", "V_cap excluded")):
        sub = out[out["diagnostic"] == tag]
        print(f"  Incremental LOO RMS (log10 units), {lab}:")
        for _, r in sub.iterrows():
            d = "" if not np.isfinite(r.get("delta_loo_rms_log10", np.nan)) else f"  (delta {r['delta_loo_rms_log10']:+.4f})"
            print(f"    +{r['feature']:<22s} k={int(r['n_features'])}  LOO_RMS={r['value']:.4f}{d}")
    print(f"\n  Saved: {out_path}")
    print("=" * 70)
    return out


def _reliable_default(df):
    """Trusted-set mask, identical to run_regionalization step A."""
    return (
        df["quality"].isin(["A", "B"])
        & (df["r_squared"] >= 0.98)
        & df["vol_ratio"].between(0.3, 5.0)
        & (df["n_pixels"] >= 50)
        & df["b"].notna()
    )


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

            # The regression diagnostic plot is rendered by the panels step, not here.
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
    # Trained on the full trusted set: the capacity-thresholded subset starves small regions below min_n.
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

    # 1-sigma b spread from the trusted set, used to inflate the c uncertainty in quadrature.
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

    # (c) Failed dams with features; skip those already in summary_df to avoid duplicate rows.
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

        # Median-impute missing features so the multi-LR never short-circuits at predict time.
        for feat, med in feature_medians.items():
            if feat in region_df.columns:
                region_df[feat] = region_df[feat].where(
                    region_df[feat].notna() & (region_df[feat] > 0), med,
                )

        # Back-solve c = V_cap / A_cap^b through the predicted anchor.
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
    # Clamp b to [1.1, 2.0]; for moved SRTM curves re-solve c through the full-pool anchor.
    _b_raw = params_df["b"].copy()
    params_df["b"] = params_df["b"].clip(1.1, 2.0)
    _anchor = summary_df.set_index("dam_id")
    _reclamp = (params_df["b"] != _b_raw) & (params_df["source"] == "srtm_derived")
    for _i in params_df.index[_reclamp]:
        _did = params_df.at[_i, "dam_id"]
        _A = float(_anchor.at[_did, "footprint_area_km2"]) * 1e6
        _V = float(_anchor.at[_did, "srtm_max_vol_mcm"]) * 1e6
        if _A > 0 and np.isfinite(_V) and _V > 0:
            params_df.at[_i, "c"] = _V / (_A ** params_df.at[_i, "b"])
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
