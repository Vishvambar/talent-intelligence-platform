import os
import json
import hashlib
import numpy as np
import polars as pl
import xgboost as xgb
import pickle
from sklearn.model_selection import RepeatedKFold

OUTPUT_DIR = "artifacts/phase09"
PHASE8_DIR = "artifacts/phase08"

def compute_feature_hash(feature_cols, dtypes):
    schema_str = "".join([f"{f}:{str(d)}" for f, d in zip(feature_cols, dtypes)])
    return hashlib.sha256(schema_str.encode()).hexdigest()

def dcg_at_k(relevances, k):
    relevances = np.array(relevances[:k])
    if len(relevances) == 0: return 0.0
    gains = (2 ** relevances - 1) / np.log2(np.arange(2, len(relevances) + 2))
    return float(np.sum(gains))

def ndcg_at_k(ranked_relevances, ideal_relevances, k):
    idcg = dcg_at_k(ideal_relevances, k)
    if idcg == 0: return 0.0
    return dcg_at_k(ranked_relevances, k) / idcg

def train_xgb_ranker():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print("--- PHASE 9A: XGBoost Ranker Training ---")
    
    # Load identical dataset as Phase 8
    dataset_path = os.path.join(PHASE8_DIR, "dataset.parquet")
    df = pl.read_parquet(dataset_path)
    
    ignore_cols = ["candidate_id", "teacher_rank", "teacher_relevance", "teacher_score", "teacher_percentile"]
    feature_cols = [c for c in df.columns if c not in ignore_cols]
    
    print(f"Training XGBoost on {len(feature_cols)} features...")
    
    X = df.select(feature_cols).to_numpy().astype(np.float32)
    y = df["teacher_relevance"].to_numpy().astype(np.float32)
    candidate_ids = df["candidate_id"].to_numpy()
    
    f_hash = compute_feature_hash(feature_cols, [df[c].dtype for c in feature_cols])
    
    # ---------------------------------------------------------
    # REPEATED HOLDOUT WITH OOF PREDICTIONS
    # ---------------------------------------------------------
    num_repeats = 5
    oof_ndcgs = []
    cv_best_iters = []
    oof_predictions = np.zeros(len(X), dtype=np.float32)
    oof_counts = np.zeros(len(X), dtype=np.float32)
    
    rkf = RepeatedKFold(n_splits=5, n_repeats=1, random_state=42)
    
    xgb_params = {
        "objective": "rank:ndcg",
        "learning_rate": 0.05,
        "max_depth": 6,
        "n_estimators": 100,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "random_state": 42,
        "n_jobs": -1
    }
    
    print("Running RepeatedKFold Validation (5 splits)...")
    for fold, (train_idx, val_idx) in enumerate(rkf.split(X)):
        X_t, y_t = X[train_idx], y[train_idx]
        X_v, y_v = X[val_idx], y[val_idx]
        
        # [KNOWN LIMITATION]: Single-query ranking.
        # We only have one recruiter (one JD) in this pipeline, meaning all 1000 candidates 
        # belong to a single search query. XGBRanker uses group=[len(X_t)] to represent this single query.
        # Future extension: Multiple recruiter datasets.
        model = xgb.XGBRanker(**xgb_params, early_stopping_rounds=20)
        model.fit(X_t, y_t, group=[len(X_t)], eval_set=[(X_v, y_v)], eval_group=[[len(X_v)]], verbose=False)
        
        preds = model.predict(X_v)
        
        # Accumulate OOF for downstream blending
        oof_predictions[val_idx] += preds
        oof_counts[val_idx] += 1
        
        sorted_indices = np.argsort(preds)[::-1]
        ranked_relevances = y_v[sorted_indices]
        ideal_relevances = np.sort(y_v)[::-1]
        
        ndcg_10 = ndcg_at_k(ranked_relevances, ideal_relevances, 10)
        oof_ndcgs.append(ndcg_10)
        
        best_iter = model.best_iteration if getattr(model, "best_iteration", None) is not None else 100
        cv_best_iters.append(best_iter)
        
        print(f"  Holdout {fold+1}/5 NDCG@10: {ndcg_10:.4f} (Trees: {best_iter})")
        
    avg_ndcg = float(np.mean(oof_ndcgs))
    print(f"Average Holdout NDCG@10: {avg_ndcg:.4f}")
    
    # Average OOF predictions for any candidates that were validated multiple times
    # If a candidate was never in a validation set, we'll fall back to training score later
    valid_mask = oof_counts > 0
    oof_predictions[valid_mask] /= oof_counts[valid_mask]
    
    # ---------------------------------------------------------
    # FINAL FULL TRAINING
    # ---------------------------------------------------------
    print("\nTraining final XGBRanker on 100% of data...")
    final_params = xgb_params.copy()
    final_params["n_estimators"] = int(np.mean(cv_best_iters))
    
    print(f"Training final XGBRanker with {final_params['n_estimators']} trees...")
    
    final_model = xgb.XGBRanker(**final_params)
    # [KNOWN LIMITATION]: Single-query ranking (see fold training comment for details)
    final_model.fit(X, y, group=[len(X)])
    
    train_scores = final_model.predict(X)
    
    # Use OOF predictions where available, else fallback to train scores
    final_oof_scores = np.where(valid_mask, oof_predictions, train_scores)
    
    # Export OOF predictions parquet
    oof_df = df.select(["candidate_id", "teacher_rank", "teacher_relevance", "teacher_score", "teacher_percentile"]).with_columns(
        pl.Series("xgb_oof_score", final_oof_scores),
        pl.Series("xgb_train_score", train_scores)
    ).sort("xgb_oof_score", descending=True)
    
    oof_df = oof_df.with_columns(pl.Series("xgb_rank", np.arange(1, len(oof_df) + 1)))
    
    # ---------------------------------------------------------
    # SAVE ARTIFACTS
    # ---------------------------------------------------------
    with open(os.path.join(OUTPUT_DIR, "xgb_model.pkl"), "wb") as f:
        pickle.dump(final_model, f)
        
    oof_df.write_parquet(os.path.join(OUTPUT_DIR, "oof_predictions.parquet"))
    
    with open(os.path.join(OUTPUT_DIR, "feature_list.json"), "w") as f:
        json.dump(feature_cols, f, indent=2)
        
    with open(os.path.join(OUTPUT_DIR, "params.json"), "w") as f:
        json.dump(final_params, f, indent=2)
        
    training_metrics = {
        "cv_ndcg10_mean": avg_ndcg,
        "cv_ndcg10_std": float(np.std(oof_ndcgs)),
        "feature_hash": f_hash,
        "num_features": len(feature_cols),
        "num_candidates": len(X)
    }
    with open(os.path.join(OUTPUT_DIR, "training_metrics.json"), "w") as f:
        json.dump(training_metrics, f, indent=2)
        
    feature_importances = final_model.feature_importances_
    fi_dict = {f: float(imp) for f, imp in zip(feature_cols, feature_importances)}
    with open(os.path.join(OUTPUT_DIR, "feature_importance.json"), "w") as f:
        json.dump(fi_dict, f, indent=2)
        
    print("✅ Phase 9A Complete! XGBoost Model and OOF metadata suite saved.")

if __name__ == "__main__":
    train_xgb_ranker()
