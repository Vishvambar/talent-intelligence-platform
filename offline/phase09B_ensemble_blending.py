import os
import json
import numpy as np
import polars as pl
import pickle
from sklearn.preprocessing import RobustScaler

OUTPUT_DIR = "artifacts/phase09"
PHASE8_DIR = "artifacts/phase08"

def dcg_at_k(relevances, k):
    relevances = np.array(relevances[:k])
    if len(relevances) == 0: return 0.0
    gains = (2 ** relevances - 1) / np.log2(np.arange(2, len(relevances) + 2))
    return float(np.sum(gains))

def ndcg_at_k(ranked_relevances, ideal_relevances, k):
    idcg = dcg_at_k(ideal_relevances, k)
    if idcg == 0: return 0.0
    return dcg_at_k(ranked_relevances, k) / idcg

def average_precision(ranked_relevances, threshold=2.0):
    relevant = np.array(ranked_relevances) >= threshold
    if relevant.sum() == 0: return 0.0
    precisions = []
    num_rel = 0
    for i, rel in enumerate(relevant):
        if rel:
            num_rel += 1
            precisions.append(num_rel / (i + 1))
    return float(np.mean(precisions))

def recall_at_k(ranked_relevances, ideal_relevances, k, threshold=2.0):
    total_relevant = np.sum(ideal_relevances >= threshold)
    if total_relevant == 0: return 1.0
    found_relevant = np.sum(np.array(ranked_relevances[:k]) >= threshold)
    return float(found_relevant / total_relevant)

def run_ensemble_blending():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print("--- PHASE 9B: Dynamic Ensemble Blending ---")
    
    # Load LightGBM predictions (from Phase 8) and XGBoost OOF predictions (Phase 9A)
    # Note: For strict correctness, Phase 8 should also generate OOF, but we use what we have available.
    try:
        lgbm_df = pl.read_parquet(os.path.join(PHASE8_DIR, "student_predictions.parquet"))
        xgb_df = pl.read_parquet(os.path.join(OUTPUT_DIR, "oof_predictions.parquet"))
    except FileNotFoundError:
        print("Required parquets not found! Ensure Phase 8 and 9A have been run.")
        return
        
    df = lgbm_df.join(xgb_df.select(["candidate_id", "xgb_oof_score", "xgb_rank"]), on="candidate_id")
    
    y = df["teacher_relevance"].to_numpy()
    lgbm_scores = df["student_score"].to_numpy() # From Phase 8
    xgb_scores = df["xgb_oof_score"].to_numpy()
    
    ideal_relevances = np.sort(y)[::-1]
    
    # ---------------------------------------------------------
    # CALIBRATION & NORMALIZATION
    # ---------------------------------------------------------
    def get_stats(arr):
        return {"mean": float(np.mean(arr)), "std": float(np.std(arr)), "min": float(np.min(arr)), "max": float(np.max(arr))}
        
    calib_stats = {
        "lgbm_raw": get_stats(lgbm_scores),
        "xgb_raw": get_stats(xgb_scores)
    }
    
    # We use RobustScaler instead of Min-Max to be resilient against extreme outliers
    # which can heavily skew tree-based model outputs
    scaler_lgbm = RobustScaler()
    scaler_xgb = RobustScaler()
    
    l_norm = scaler_lgbm.fit_transform(lgbm_scores.reshape(-1, 1)).flatten()
    x_norm = scaler_xgb.fit_transform(xgb_scores.reshape(-1, 1)).flatten()
    
    calib_stats["lgbm_norm"] = get_stats(l_norm)
    calib_stats["xgb_norm"] = get_stats(x_norm)
    
    with open(os.path.join(OUTPUT_DIR, "calibration_statistics.json"), "w") as f:
        json.dump(calib_stats, f, indent=2)
        
    # ---------------------------------------------------------
    # GRID SEARCH COMPOSITE OPTIMIZATION
    # ---------------------------------------------------------
    print("Searching for optimal blend weights...")
    results = []
    
    best_composite = -1
    best_blend = 0.0
    
    best_ndcg10_score = -1
    best_ndcg10_blend = 0.0
    
    best_map_score = -1
    best_map_blend = 0.0
    
    for w in np.arange(0.0, 1.01, 0.01):
        w = round(w, 2)
        blend_scores = w * l_norm + (1 - w) * x_norm
        
        # Sort current blend
        sorted_indices = np.argsort(blend_scores)[::-1]
        ranked_relevances = y[sorted_indices]
        
        n10 = ndcg_at_k(ranked_relevances, ideal_relevances, 10)
        n50 = ndcg_at_k(ranked_relevances, ideal_relevances, 50)
        map_score = average_precision(ranked_relevances, threshold=2.0)
        r100 = recall_at_k(ranked_relevances, ideal_relevances, 100, threshold=2.0)
        
        # Composite Score: 0.50 × NDCG@10 + 0.25 × NDCG@50 + 0.15 × MAP + 0.10 × Recall@100
        composite = (0.50 * n10) + (0.25 * n50) + (0.15 * map_score) + (0.10 * r100)
        
        results.append({
            "lgbm_weight": w,
            "xgb_weight": round(1-w, 2),
            "ndcg10": n10,
            "ndcg50": n50,
            "map": map_score,
            "recall100": r100,
            "composite": composite
        })
        
        if composite > best_composite:
            best_composite = composite
            best_blend = w
            
        if n10 > best_ndcg10_score:
            best_ndcg10_score = n10
            best_ndcg10_blend = w
            
        if map_score > best_map_score:
            best_map_score = map_score
            best_map_blend = w
            
    # Save Landscape
    results_df = pl.DataFrame(results)
    results_df.write_parquet(os.path.join(OUTPUT_DIR, "blend_search_results.parquet"))
    
    # Get Top 4 Composite Blends
    sorted_comps = sorted(results, key=lambda x: x["composite"], reverse=True)
    top_4_blends = sorted_comps[:4]
    
    optimal = {
        "top_4_composite_blends": top_4_blends,
        "best_ndcg10_blend": {"lgbm_weight": best_ndcg10_blend, "xgb_weight": round(1-best_ndcg10_blend, 2), "score": best_ndcg10_score},
        "best_map_blend": {"lgbm_weight": best_map_blend, "xgb_weight": round(1-best_map_blend, 2), "score": best_map_score}
    }
    
    # ---------------------------------------------------------
    # APPLY OPTIMAL BLEND
    # ---------------------------------------------------------
    best_blend = top_4_blends[0]["lgbm_weight"]
    final_scores = best_blend * l_norm + (1 - best_blend) * x_norm
    df = df.with_columns(pl.Series("ensemble_score", final_scores))
    df = df.sort("ensemble_score", descending=True)
    df = df.with_columns(pl.Series("ensemble_rank", np.arange(1, len(df) + 1)))
    
    df.write_parquet(os.path.join(OUTPUT_DIR, "ensemble_predictions.parquet"))
    
    # Agreement Metrics (Rank Divergence)
    rank_diff = np.abs(df["student_rank"].to_numpy() - df["xgb_rank"].to_numpy())
    agreement = {
        "mean_rank_diff": float(np.mean(rank_diff)),
        "std_rank_diff": float(np.std(rank_diff)),
        "90_percentile_diff": float(np.percentile(rank_diff, 90)),
        "max_diff": float(np.max(rank_diff))
    }
    
    with open(os.path.join(OUTPUT_DIR, "agreement_metrics.json"), "w") as f:
        json.dump(agreement, f, indent=2)
        
    optimal_path = os.path.join(OUTPUT_DIR, "optimal_blend.json")
    with open(optimal_path, "w") as f:
        json.dump(optimal, f, indent=4)
        
    # Serialize the scalers for online inference (Phase 11)
    with open(os.path.join(OUTPUT_DIR, "lgb_scaler.pkl"), "wb") as f:
        pickle.dump(scaler_lgbm, f)
        
    with open(os.path.join(OUTPUT_DIR, "xgb_scaler.pkl"), "wb") as f:
        pickle.dump(scaler_xgb, f)
        
    # Save Elite Formula for Phase 11
    # Determine valid features based on actual dataset schema
    valid_features = {"ensemble_score": 0.70}
    
    if "retrieval_strength" in df.columns:
        valid_features["retrieval_strength"] = 0.20
    elif "retrieval_score" in df.columns:
        valid_features["retrieval_score"] = 0.20
        
    if "dense_consensus_score" in df.columns:
        valid_features["dense_consensus_score"] = 0.20
    elif "vector_db_score" in df.columns:
        valid_features["vector_db_score"] = 0.20
        
    if "technical_coverage" in df.columns:
        valid_features["technical_coverage"] = 0.20
    elif "evaluation_score" in df.columns:
        valid_features["evaluation_score"] = 0.20
        
    if "integrity_score" in df.columns:
        valid_features["integrity_score"] = 0.10

    elite_formula = {
        "elite_pool_size": 50,
        "features": valid_features,
        "description": "Notice technical scores are summed before multiplying by 0.20 in run_ranking.py. This formula config replaces hardcoded values."
    }
    with open(os.path.join(OUTPUT_DIR, "elite_formula.json"), "w") as f:
        json.dump(elite_formula, f, indent=4)
        
    print(f"✅ Phase 9B Complete! Optimal blend and scalers saved to {OUTPUT_DIR}")

if __name__ == "__main__":
    run_ensemble_blending()
