"""
Theme 1: Parking-Induced Congestion
Module 3: ML Model Training

Trains LightGBM + CatBoost ensemble with Nelder-Mead weight optimization.
Uses Walk-Forward TimeSeriesSplit to respect temporal ordering.

Usage:
    python model_trainer.py
"""

import pandas as pd
import numpy as np
import pickle
import time
from sklearn.metrics import r2_score, mean_squared_error, mean_absolute_error
from scipy.optimize import minimize
from config import TOTAL_OFFICERS


# FEATURE COLUMNS & TARGET

TARGET_COL = 'total_pcu_impact'

# Features for the ML model
FEATURE_COLS = [
    # Temporal (cyclical)
    'hour_sin', 'hour_cos',
    'day_sin', 'day_cos',
    'is_weekend',

    # Vehicle composition ratios (strategy triggers)
    'two_wheeler_ratio',
    'three_wheeler_ratio',
    'heavy_vehicle_ratio',

    # Enforcement quality
    'validation_ratio',

    # Spatial
    'junction_ratio',
    'distance_to_cbd',
    'lat_mean', 'lon_mean',

    # Zone archetype (encoded)
    'zone_archetype_code',

    # Severity
    'avg_offence_count',
    'avg_violation_count',

    # Zone-level stats
    'weekend_surge_ratio',
    'persistence_score',

    # Spatial spillover (balloon effect)
    'spatial_lag_pcu',
    'spatial_lag_delta',
]


# TIME-BASED SPLIT (Walk-Forward Validation)

def prepare_time_splits(df):
    """
    Create walk-forward time splits based on month.
    Train on expanding window, test on next month.
    
    Fold 1: Train [Nov]      -> Test [Dec]
    Fold 2: Train [Nov-Dec]  -> Test [Jan]
    Fold 3: Train [Nov-Jan]  -> Test [Feb]
    Fold 4: Train [Nov-Feb]  -> Test [Mar]
    Fold 5: Train [Nov-Mar]  -> Test [Apr]
    """
    print("Preparing walk-forward time splits...")

    # Month mapping: Nov=11, Dec=12, Jan=1, Feb=2, Mar=3, Apr=4
    # Remap to sequential order for proper splitting
    month_order = {11: 0, 12: 1, 1: 2, 2: 3, 3: 4, 4: 5}
    df['month_seq'] = df['month'].map(month_order)

    # Handle any unmapped months
    if df['month_seq'].isnull().any():
        unmapped = df[df['month_seq'].isnull()]['month'].unique()
        print(f"  WARNING: Unmapped months: {unmapped}. Dropping these rows.")
        df = df.dropna(subset=['month_seq'])
    df['month_seq'] = df['month_seq'].astype(int)

    folds = []
    unique_months = sorted(df['month_seq'].unique())

    for i in range(len(unique_months) - 1):
        train_months = unique_months[:i + 1]
        test_month = unique_months[i + 1]

        train_mask = df['month_seq'].isin(train_months)
        test_mask = df['month_seq'] == test_month

        train_idx = df[train_mask].index.tolist()
        test_idx = df[test_mask].index.tolist()

        if len(train_idx) > 0 and len(test_idx) > 0:
            folds.append((train_idx, test_idx))
            print(f"  Fold {len(folds)}: Train months {train_months} "
                  f"({len(train_idx)} rows) -> Test month {test_month} "
                  f"({len(test_idx)} rows)")

    return folds


# MODEL TRAINING

def train_lightgbm(X_train, y_train, X_val=None, y_val=None):
    """Train a LightGBM regressor."""
    import lightgbm as lgb

    params = {
        'objective': 'regression',
        'metric': 'rmse',
        'boosting_type': 'gbdt',
        'num_leaves': 63,
        'learning_rate': 0.05,
        'feature_fraction': 0.8,
        'bagging_fraction': 0.8,
        'bagging_freq': 5,
        'verbose': -1,
        'n_jobs': -1,
        'seed': 42,
    }

    dtrain = lgb.Dataset(X_train, label=y_train)

    callbacks = [lgb.log_evaluation(period=0)]  # Suppress verbose

    if X_val is not None and y_val is not None:
        dval = lgb.Dataset(X_val, label=y_val, reference=dtrain)
        model = lgb.train(
            params, dtrain,
            num_boost_round=1000,
            valid_sets=[dval],
            callbacks=[lgb.early_stopping(50), lgb.log_evaluation(period=0)]
        )
    else:
        model = lgb.train(params, dtrain, num_boost_round=500, callbacks=callbacks)

    return model


def train_catboost(X_train, y_train, X_val=None, y_val=None):
    """Train a CatBoost regressor."""
    from catboost import CatBoostRegressor

    model = CatBoostRegressor(
        iterations=1000,
        learning_rate=0.05,
        depth=8,
        l2_leaf_reg=3,
        random_seed=42,
        verbose=0,
        early_stopping_rounds=50 if X_val is not None else None,
    )

    eval_set = None
    if X_val is not None and y_val is not None:
        eval_set = (X_val, y_val)

    model.fit(X_train, y_train, eval_set=eval_set)
    return model


def train_xgboost(X_train, y_train, X_val=None, y_val=None):
    """Train an XGBoost regressor (backup / third ensemble member)."""
    import xgboost as xgb

    params = {
        'objective': 'reg:squarederror',
        'max_depth': 8,
        'learning_rate': 0.05,
        'colsample_bytree': 0.8,
        'subsample': 0.8,
        'seed': 42,
        'n_jobs': -1,
        'verbosity': 0,
    }

    dtrain = xgb.DMatrix(X_train, label=y_train)

    evals = []
    if X_val is not None and y_val is not None:
        dval = xgb.DMatrix(X_val, label=y_val)
        evals = [(dval, 'eval')]

    model = xgb.train(
        params, dtrain,
        num_boost_round=1000,
        evals=evals,
        early_stopping_rounds=50 if evals else None,
        verbose_eval=False,
    )
    return model


# ENSEMBLE WEIGHT OPTIMIZATION (Nelder-Mead — Your Round 1 technique)

def optimize_ensemble_weights(predictions_dict, y_true):
    """
    Use Nelder-Mead to find mathematically optimal ensemble blend weights.
    
    predictions_dict: {'lgbm': array, 'catboost': array, 'xgboost': array}
    y_true: true target values
    
    Returns dict of optimal weights.
    """
    model_names = list(predictions_dict.keys())
    pred_arrays = [predictions_dict[name] for name in model_names]
    n_models = len(model_names)

    def neg_r2(weights):
        """Negative R2 (we minimize this)."""
        # Normalize weights to sum to 1
        w = np.array(weights)
        w = np.abs(w) / np.sum(np.abs(w))

        blended = sum(w[i] * pred_arrays[i] for i in range(n_models))
        return -r2_score(y_true, blended)

    # Initial weights: equal
    x0 = [1.0 / n_models] * n_models

    result = minimize(neg_r2, x0, method='Nelder-Mead',
                      options={'maxiter': 5000, 'xatol': 1e-6})

    # Normalize final weights
    optimal = np.abs(result.x) / np.sum(np.abs(result.x))
    weights = {name: round(float(w), 4) for name, w in zip(model_names, optimal)}

    # Report
    blended = sum(optimal[i] * pred_arrays[i] for i in range(n_models))
    ensemble_r2 = r2_score(y_true, blended)

    print(f"\n  Nelder-Mead Ensemble Optimization:")
    for name, w in weights.items():
        individual_r2 = r2_score(y_true, predictions_dict[name])
        print(f"    {name}: weight={w:.4f}, individual R2={individual_r2:.6f}")
    print(f"    ENSEMBLE R2 = {ensemble_r2:.6f}")

    return weights


# EVALUATION

def evaluate_model(y_true, y_pred, label=""):
    """Compute R2, RMSE, MAE."""
    r2 = r2_score(y_true, y_pred)
    rmse = np.sqrt(mean_squared_error(y_true, y_pred))
    mae = mean_absolute_error(y_true, y_pred)
    print(f"  {label} -> R2={r2:.6f}, RMSE={rmse:.4f}, MAE={mae:.4f}")
    return {'r2': r2, 'rmse': rmse, 'mae': mae}


def get_feature_importance(lgbm_model, feature_names):
    """Extract and display feature importance from LightGBM model."""
    importance = lgbm_model.feature_importance(importance_type='gain')
    feat_imp = pd.DataFrame({
        'feature': feature_names,
        'importance': importance
    }).sort_values('importance', ascending=False)

    print("\n  Top 15 Features (LightGBM gain):")
    for _, row in feat_imp.head(15).iterrows():
        bar = '#' * int(row['importance'] / feat_imp['importance'].max() * 30)
        print(f"    {row['feature']:<25s} {row['importance']:>12.1f}  {bar}")

    return feat_imp


# FULL TRAINING PIPELINE

def run_training_pipeline(df):
    """
    Run the full walk-forward cross-validated training pipeline.
    Returns trained models, ensemble weights, and CV results.
    """
    print("\n" + "=" * 70)
    print("MODEL TRAINING PIPELINE")
    print("=" * 70)

    # Prepare features and target
    available_features = [f for f in FEATURE_COLS if f in df.columns]
    missing_features = [f for f in FEATURE_COLS if f not in df.columns]
    if missing_features:
        print(f"  WARNING: Missing features: {missing_features}")

    X = df[available_features].copy()
    y = df[TARGET_COL].copy()

    # Fill any NaN in features
    nan_cols = X.columns[X.isnull().any()].tolist()
    if nan_cols:
        print(f"  Filling NaN in features: {nan_cols}")
        X = X.fillna(0)

    print(f"  Features: {len(available_features)} columns")
    print(f"  Target: {TARGET_COL} (mean={y.mean():.2f}, std={y.std():.2f})")

    # Walk-forward splits
    folds = prepare_time_splits(df)

    # Storage for CV results
    cv_results = []
    all_oof_preds = {}  # Out-of-fold predictions per model
    all_oof_true = []
    all_oof_idx = []

    for fold_idx, (train_idx, test_idx) in enumerate(folds):
        print(f"\n--- Fold {fold_idx + 1}/{len(folds)} ---")

        X_train, X_test = X.loc[train_idx], X.loc[test_idx]
        y_train, y_test = y.loc[train_idx], y.loc[test_idx]

        # Train LightGBM
        start = time.time()
        lgbm_model = train_lightgbm(X_train, y_train, X_test, y_test)
        lgbm_preds = lgbm_model.predict(X_test)
        lgbm_preds = np.clip(lgbm_preds, 0, None)  # Non-negative
        lgbm_time = time.time() - start
        evaluate_model(y_test, lgbm_preds, f"LightGBM (fold {fold_idx+1}, {lgbm_time:.1f}s)")

        # Train CatBoost
        start = time.time()
        cat_model = train_catboost(X_train, y_train, X_test, y_test)
        cat_preds = cat_model.predict(X_test)
        cat_preds = np.clip(cat_preds, 0, None)
        cat_time = time.time() - start
        evaluate_model(y_test, cat_preds, f"CatBoost  (fold {fold_idx+1}, {cat_time:.1f}s)")

        # Try XGBoost if available
        try:
            import xgboost as xgb
            start = time.time()
            xgb_model = train_xgboost(X_train, y_train, X_test, y_test)
            xgb_preds = xgb_model.predict(xgb.DMatrix(X_test))
            xgb_preds = np.clip(xgb_preds, 0, None)
            xgb_time = time.time() - start
            evaluate_model(y_test, xgb_preds, f"XGBoost   (fold {fold_idx+1}, {xgb_time:.1f}s)")
            has_xgboost = True
        except ImportError:
            has_xgboost = False

        # Optimize ensemble weights for this fold
        pred_dict = {'lgbm': lgbm_preds, 'catboost': cat_preds}
        if has_xgboost:
            pred_dict['xgboost'] = xgb_preds

        weights = optimize_ensemble_weights(pred_dict, y_test)

        # Blend predictions
        blended = sum(weights[name] * pred_dict[name] for name in pred_dict)
        fold_metrics = evaluate_model(y_test, blended, f"ENSEMBLE  (fold {fold_idx+1})")
        cv_results.append(fold_metrics)

        # Store OOF predictions
        all_oof_true.extend(y_test.tolist())
        all_oof_idx.extend(test_idx)
        for name in pred_dict:
            if name not in all_oof_preds:
                all_oof_preds[name] = []
            all_oof_preds[name].extend(pred_dict[name].tolist())

    # Overall CV summary
    print("\n" + "=" * 70)
    print("CROSS-VALIDATION SUMMARY")
    print("=" * 70)
    r2_scores = [r['r2'] for r in cv_results]
    rmse_scores = [r['rmse'] for r in cv_results]
    print(f"  R2  per fold: {[f'{s:.6f}' for s in r2_scores]}")
    print(f"  R2  mean={np.mean(r2_scores):.6f}, std={np.std(r2_scores):.6f}")
    print(f"  RMSE per fold: {[f'{s:.4f}' for s in rmse_scores]}")
    print(f"  RMSE mean={np.mean(rmse_scores):.4f}")

    # Overall OOF ensemble optimization
    print("\n  Overall OOF Ensemble Optimization:")
    oof_pred_dict = {name: np.array(preds) for name, preds in all_oof_preds.items()}
    oof_true = np.array(all_oof_true)
    overall_weights = optimize_ensemble_weights(oof_pred_dict, oof_true)

    # Final retrain on ALL data
    print("\n" + "=" * 70)
    print("FINAL RETRAIN ON ALL DATA")
    print("=" * 70)

    final_lgbm = train_lightgbm(X, y)
    final_cat = train_catboost(X, y)

    try:
        import xgboost as xgb
        final_xgb = train_xgboost(X, y)
        final_models = {'lgbm': final_lgbm, 'catboost': final_cat, 'xgboost': final_xgb}
    except ImportError:
        final_models = {'lgbm': final_lgbm, 'catboost': final_cat}

    # Feature importance from final LightGBM
    feat_imp = get_feature_importance(final_lgbm, available_features)

    print("\nTraining complete!")

    return {
        'models': final_models,
        'weights': overall_weights,
        'feature_importance': feat_imp,
        'cv_results': cv_results,
        'feature_cols': available_features,
    }


def predict_ensemble(models, weights, X):
    """Generate ensemble predictions from trained models."""
    predictions = {}

    for name, model in models.items():
        if name == 'lgbm':
            predictions[name] = model.predict(X)
        elif name == 'catboost':
            predictions[name] = model.predict(X)
        elif name == 'xgboost':
            import xgboost as xgb
            predictions[name] = model.predict(xgb.DMatrix(X))

    # Blend
    blended = sum(weights.get(name, 0) * preds for name, preds in predictions.items())
    return np.clip(blended, 0, None)


def save_training_results(results, prefix='model'):
    """Save trained models and weights to disk."""
    # Save models
    for name, model in results['models'].items():
        path = f"{prefix}_{name}.pkl"
        with open(path, 'wb') as f:
            pickle.dump(model, f)
        print(f"  Saved {name} model -> {path}")

    # Save weights
    weights_path = f"{prefix}_weights.pkl"
    with open(weights_path, 'wb') as f:
        pickle.dump(results['weights'], f)
    print(f"  Saved ensemble weights -> {weights_path}")

    # Save feature importance
    results['feature_importance'].to_csv(f"{prefix}_feature_importance.csv", index=False)
    print(f"  Saved feature importance -> {prefix}_feature_importance.csv")


# STANDALONE TEST
if __name__ == '__main__':
    from data_loader import load_parking_data, clean_parking_data, convert_utc_to_ist
    from feature_engineer import engineer_all_features

    # Load and prepare data
    df = load_parking_data()
    df = clean_parking_data(df)
    df = convert_utc_to_ist(df)

    # Feature engineering
    aggregated, centroids, adj_map = engineer_all_features(df)

    # Train models
    results = run_training_pipeline(aggregated)

    # Save
    print("\nSaving training results...")
    save_training_results(results)

    print("\nAll done!")
