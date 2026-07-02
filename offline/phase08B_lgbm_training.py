import os
import json
import hashlib
import numpy as np
import polars as pl
import lightgbm as lgb
import pickle
from sklearn.model_selection import RepeatedKFold

OUTPUT_DIR = "artifacts/phase08"

def compute_feature_hash(feature_cols, dtypes):
    """Computes a SHA256 hash of the exact feature schema."""
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

def train_ranker():
    print("--- PHASE 8B: LightGBMRanker Training ---")
    df = pl.read_parquet(os.path.join(OUTPUT_DIR, "dataset.parquet"))
    
    # Identify features
    ignore_cols = ["candidate_id", "teacher_rank", "teacher_relevance", "teacher_score", "teacher_percentile"]
    feature_cols = [c for c in df.columns if c not in ignore_cols]
    
    print(f"Training on {len(feature_cols)} features...")
    
    X = df.select(feature_cols).to_numpy().astype(np.float32)
    y = df["teacher_relevance"].to_numpy().astype(np.float32)
    
    # Feature Versioning Hash
    dtypes = [df[c].dtype for c in feature_cols]
    f_hash = compute_feature_hash(feature_cols, dtypes)
    
    # ---------------------------------------------------------
    # REPEATED HOLDOUT RANKING VALIDATION
    # Because this is a single query, we simulate ranking splits
    # ---------------------------------------------------------
    num_repeats = 5
    oof_ndcgs = []
    cv_best_iters = []
    
    # We use RepeatedKFold to evaluate how the ranker performs on held-out subsets of the candidate pool
    rkf = RepeatedKFold(n_splits=5, n_repeats=1, random_state=42)
    
    print("Running RepeatedKFold Validation (5 splits)...")
    for fold, (train_idx, val_idx) in enumerate(rkf.split(X)):
        X_t, y_t = X[train_idx], y[train_idx]
        X_v, y_v = X[val_idx], y[val_idx]
        
        # [KNOWN LIMITATION]: Single-query ranking.
        # We only have one recruiter (one JD) in this pipeline, meaning all 1000 candidates 
        # belong to a single search query. LambdaRank was designed for multiple queries 
        # (Query1, Query2...). We use group=[len(X_t)] to represent this single query.
        # Future extension: Multiple recruiter datasets.
        model = lgb.LGBMRanker(
            objective="lambdarank",
            learning_rate=0.01,
            num_leaves=7,
            max_depth=3,
            min_child_samples=5,
            colsample_bytree=1.0,
            n_estimators=500,
            random_state=42 + fold,
            n_jobs=-1
        )
        
        # Fit silently
        model.fit(
            X_t, y_t,
            group=[len(X_t)],
            eval_set=[(X_v, y_v)],
            eval_group=[[len(X_v)]],
            eval_at=[10, 50, 100],
            callbacks=[lgb.early_stopping(stopping_rounds=50, verbose=False)]
        )
        
        preds = model.predict(X_v)
        
        # Calculate NDCG@10 on this holdout slice
        # Sort validation true labels by model predictions
        sorted_indices = np.argsort(preds)[::-1]
        ranked_relevances = y_v[sorted_indices]
        ideal_relevances = np.sort(y_v)[::-1]
        
        ndcg_10 = ndcg_at_k(ranked_relevances, ideal_relevances, 10)
        oof_ndcgs.append(ndcg_10)
        
        best_iter = model.best_iteration_ if model.best_iteration_ else 100
        cv_best_iters.append(best_iter)
        
        print(f"  Holdout {fold+1}/5 NDCG@10: {ndcg_10:.4f} (Trees: {best_iter})")
        
    avg_ndcg = float(np.mean(oof_ndcgs))
    print(f"Average Holdout NDCG@10: {avg_ndcg:.4f}")
    
    # ---------------------------------------------------------
    # FINAL FULL TRAINING
    # ---------------------------------------------------------
    print("\nTraining final LightGBMRanker on 100% of data...")
    lgbm_params = {
        "objective": "lambdarank",
        "learning_rate": 0.01,
        "num_leaves": 7,
        "max_depth": 3,
        "min_child_samples": 5,
        "colsample_bytree": 1.0,
        "n_estimators": int(np.mean(cv_best_iters)), # Data-driven from CV
        "random_state": 42,
        "n_jobs": -1
    }
    
    print(f"Training final LightGBMRanker with {lgbm_params['n_estimators']} trees...")
    
    final_model = lgb.LGBMRanker(**lgbm_params)
    # [KNOWN LIMITATION]: Single-query ranking (see fold training comment for details)
    final_model.fit(X, y, group=[len(X)])
    
    # Generate Student Predictions (preserving teacher_score for diagnostics)
    student_scores = final_model.predict(X)
    df_preds = df.select(["candidate_id", "teacher_rank", "teacher_relevance", "teacher_score", "teacher_percentile"]).with_columns(
        pl.Series("student_score", student_scores)
    ).sort("student_score", descending=True)
    
    df_preds = df_preds.with_columns(
        pl.Series("student_rank", np.arange(1, len(df_preds) + 1)),
        pl.Series("student_percentile", 100.0 * (len(df_preds) - np.arange(1, len(df_preds) + 1)) / len(df_preds))
    )
    
    # ---------------------------------------------------------
    # SAVE ARTIFACTS
    # ---------------------------------------------------------
    # Model
    with open(os.path.join(OUTPUT_DIR, "lgbm_model.pkl"), "wb") as f:
        pickle.dump(final_model, f)
        
    # Predictions
    df_preds.write_parquet(os.path.join(OUTPUT_DIR, "student_predictions.parquet"))
    
    # Metadata
    with open(os.path.join(OUTPUT_DIR, "feature_list.json"), "w") as f:
        json.dump(feature_cols, f, indent=2)
        
    with open(os.path.join(OUTPUT_DIR, "train_columns.json"), "w") as f:
        json.dump({"columns": feature_cols, "hash": f_hash}, f, indent=2)
        
    with open(os.path.join(OUTPUT_DIR, "lightgbm_params.json"), "w") as f:
        json.dump(lgbm_params, f, indent=2)
        
    training_metrics = {
        "cv_ndcg10_mean": avg_ndcg,
        "cv_ndcg10_std": float(np.std(oof_ndcgs)),
        "feature_hash": f_hash,
        "num_features": len(feature_cols),
        "num_candidates": len(X),
        "best_iteration": final_model.best_iteration_ or lgbm_params["n_estimators"]
    }
    with open(os.path.join(OUTPUT_DIR, "training_metrics.json"), "w") as f:
        json.dump(training_metrics, f, indent=2)
        
    feature_stats = {
        c: {"mean": float(np.mean(X[:, i])), "std": float(np.std(X[:, i]))}
        for i, c in enumerate(feature_cols)
    }
    with open(os.path.join(OUTPUT_DIR, "feature_stats.json"), "w") as f:
        json.dump(feature_stats, f, indent=2)
        
    # Generate Hashes for Manifest
    with open(os.path.join(OUTPUT_DIR, "dataset.parquet"), "rb") as f:
        dataset_hash = hashlib.sha256(f.read()).hexdigest()
    with open(os.path.join(OUTPUT_DIR, "lgbm_model.pkl"), "rb") as f:
        model_hash = hashlib.sha256(f.read()).hexdigest()
        
    manifest = {
        "feature_hash": f_hash,
        "model_hash": model_hash,
        "dataset_hash": dataset_hash,
        "timestamp": str(np.datetime64('now'))
    }
    with open(os.path.join(OUTPUT_DIR, "pipeline_manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
        
    print("✅ Phase 8B Complete! Model and full metadata suite saved.")

if __name__ == "__main__":
    train_ranker()
