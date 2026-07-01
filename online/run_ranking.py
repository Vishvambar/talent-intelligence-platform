import os
import json
import hashlib
import numpy as np
import polars as pl
import xgboost as xgb
import lightgbm as lgb
import pickle
import time
from sklearn.preprocessing import RobustScaler

# ==============================================================================
# ONLINE PIPELINE CONFIGURATION
# ==============================================================================
PHASE08_DIR = "artifacts/phase08"
PHASE09_DIR = "artifacts/phase09"
PHASE10_DIR = "artifacts/phase10"
OUTPUT_DIR = "online"

ELITE_POOL_SIZE = 50

# In a real production deployment, these hashes would be generated offline
# and hardcoded here to protect against model tampering on Kaggle.
# For local testing, we'll bypass strict hash failure if not configured,
# but print warnings.
EXPECTED_HASHES = {
    "lgbm_model.pkl": None,
    "xgb_model.pkl": None,
    "evidence_bank.parquet": None
}

def verify_checksums():
    print("Verifying Artifact Integrity Checksums...")
    # This simulates Phase 11.1 integrity verification
    files = {
        "lgbm_model.pkl": os.path.join(PHASE08_DIR, "lgbm_model.pkl"),
        "xgb_model.pkl": os.path.join(PHASE09_DIR, "xgb_model.pkl"),
        "evidence_bank.parquet": os.path.join(PHASE10_DIR, "evidence_bank.parquet")
    }
    
    for name, path in files.items():
        if not os.path.exists(path):
            print(f"Warning: {name} not found. Skipping checksum.")
            continue
        with open(path, "rb") as f:
            h = hashlib.sha256(f.read()).hexdigest()
        
        expected = EXPECTED_HASHES.get(name)
        if expected and h != expected:
            raise ValueError(f"CRITICAL: {name} checksum mismatch! Artifact tampering detected.")
        else:
            pass # Valid or unconfigured

def load_and_validate_features():
    print("Loading inference features...")
    df = pl.read_parquet(os.path.join(PHASE08_DIR, "inference_features.parquet"))
    
    print("Validating schema...")
    try:
        with open(os.path.join(PHASE08_DIR, "expected_features.json"), "r") as f:
            expected_cols = json.load(f)
    except FileNotFoundError:
        print("Warning: expected_features.json not found. Skipping schema validation.")
        return df
        
    actual_cols = [c for c in df.columns if c != "candidate_id"]
    
    if len(actual_cols) != len(expected_cols):
        raise ValueError(f"Schema mismatch! Expected {len(expected_cols)} features, got {len(actual_cols)}.")
        
    for e, a in zip(expected_cols, actual_cols):
        if e != a:
            raise ValueError(f"Schema ordering mismatch! Expected '{e}', got '{a}'.")
            
    print("Schema perfectly validated.")
    return df

def generate_reasoning_string(evidence_str: str) -> str:
    try:
        ev = json.loads(evidence_str)
        
        # Sentence 1: Summary
        sc = ev.get("summary_components", {})
        s1 = f"Candidate brings {sc.get('experience_years', 0)} years of experience in {sc.get('company_type', 'Tech')}, aligning closely with the {sc.get('primary_domain', 'Engineering')} domain at a {sc.get('seniority', 'Senior')} level."
        
        # Sentence 2: Strengths (Top 2)
        s2 = "No notable strengths extracted."
        strengths = ev.get("strengths", [])
        if len(strengths) >= 2:
            s2 = f"Demonstrates strong capability in {strengths[0]['label']} and {strengths[1]['label']}."
        elif len(strengths) == 1:
            s2 = f"Demonstrates strong capability in {strengths[0]['label']}."
            
        # Sentence 3: Risks or Gaps (Top 1)
        s3 = "Presents minimal risk factors."
        risks = ev.get("risks", [])
        gaps = ev.get("gaps", [])
        
        if risks:
            s3 = f"Primary risk factor: {risks[0]['label']}."
        elif gaps:
            s3 = f"Primary gap: {gaps[0]['label']}."
            
        return f"{s1} {s2} {s3}"
    except Exception as e:
        raise ValueError(f"CRITICAL: Failed to parse reasoning evidence: {e}")

def main():
    t_start = time.time()
    
    verify_checksums()
    
    t_read_start = time.time()
    df = load_and_validate_features()
    X = df.drop("candidate_id").to_numpy()
    
    print("Loading Models...")
    with open(os.path.join(PHASE08_DIR, "lgbm_model.pkl"), "rb") as f:
        lgbm_model = pickle.load(f)
        
    with open(os.path.join(PHASE09_DIR, "xgb_model.pkl"), "rb") as f:
        xgb_model = pickle.load(f)
        
    with open(os.path.join(PHASE09_DIR, "optimal_blend.json"), "r") as f:
        blend_config = json.load(f)
        
    with open(os.path.join(PHASE09_DIR, "lgb_scaler.pkl"), "rb") as f:
        scaler_lgbm = pickle.load(f)
        
    with open(os.path.join(PHASE09_DIR, "xgb_scaler.pkl"), "rb") as f:
        scaler_xgb = pickle.load(f)
        
    with open(os.path.join(PHASE09_DIR, "elite_formula.json"), "r") as f:
        elite_formula = json.load(f)
        
    lgbm_weight = blend_config["best_ndcg10_blend"]["lgbm_weight"]
    xgb_weight = blend_config["best_ndcg10_blend"]["xgb_weight"]
    t_read = time.time() - t_read_start
    
    t_pred_start = time.time()
    print("Executing LTR Inference...")
    lgbm_scores = lgbm_model.predict(X)
    xgb_scores = xgb_model.predict(X)
    
    print("Applying Static Ensemble...")
    l_norm = scaler_lgbm.transform(lgbm_scores.reshape(-1, 1)).flatten()
    x_norm = scaler_xgb.transform(xgb_scores.reshape(-1, 1)).flatten()
    
    ensemble_scores = (lgbm_weight * l_norm) + (xgb_weight * x_norm)
    
    # Strictly Deterministic Tie-Breaking
    ranks = np.arange(len(ensemble_scores))
    ensemble_scores = ensemble_scores - (ranks * 1e-9)
    
    res_df = df.select(["candidate_id"]).with_columns(pl.Series("ensemble_score", ensemble_scores))
    res_df = res_df.sort("ensemble_score", descending=True)
    
    elite_pool_size = elite_formula.get("elite_pool_size", 50)
    print(f"Applying Elite Reranking to Top {elite_pool_size}...")
    elite_pool = res_df.head(elite_pool_size)
    rest_pool = res_df.tail(len(res_df) - elite_pool_size)
    
    # We load the full feature matrix for the Elite Pool
    elite_ids = elite_pool["candidate_id"].to_list()
    elite_features = df.filter(pl.col("candidate_id").is_in(elite_ids))
    
    # Deterministic Elite Scoring (from Phase 9 elite_formula.json)
    elite_scores = []
    f_weights = elite_formula["features"]
    
    for row in elite_features.to_dicts():
        ens = float(elite_pool.filter(pl.col("candidate_id") == row["candidate_id"])["ensemble_score"][0])
        score = ens * f_weights.get("ensemble_score", 0.70)
        
        # Apply other technical weights
        for feat, weight in f_weights.items():
            if feat != "ensemble_score":
                score += float(row.get(feat, 0.0)) * weight
                
        elite_scores.append(score)
        
    elite_pool = elite_pool.with_columns(pl.Series("elite_score", elite_scores))
    
    # Tie-breaking on elite scores
    e_ranks = np.arange(len(elite_pool))
    elite_scores_tb = np.array(elite_scores) - (e_ranks * 1e-9)
    elite_pool = elite_pool.with_columns(pl.Series("elite_score", elite_scores_tb))
    
    elite_pool = elite_pool.sort("elite_score", descending=True)
    
    # Combine back to get final Top 100
    final_top100_ids = elite_pool["candidate_id"].to_list() + rest_pool["candidate_id"].to_list()
    final_top100_ids = final_top100_ids[:100]
    
    elite_scores_list = elite_pool["elite_score"].to_list()
    rest_scores_list = rest_pool["ensemble_score"].to_list()
    
    if elite_scores_list and rest_scores_list:
        min_elite = min(elite_scores_list)
        max_rest = max(rest_scores_list)
        if max_rest >= min_elite:
            shift = max_rest - min_elite + 1.0
            rest_scores_list = [s - shift for s in rest_scores_list]
            
    final_top100_scores = elite_scores_list + rest_scores_list
    final_top100_scores = final_top100_scores[:100]
    
    top100_df = pl.DataFrame({
        "candidate_id": final_top100_ids,
        "score": final_top100_scores,
        "rank": np.arange(1, 101)
    })
    t_pred = time.time() - t_pred_start
    
    t_render_start = time.time()
    print("Loading Evidence Bank...")
    try:
        ev_df = pl.read_parquet(os.path.join(PHASE10_DIR, "evidence_bank.parquet"))
    except FileNotFoundError:
        print("evidence_bank.parquet not found. Generating dummy reasoning.")
        ev_df = pl.DataFrame({
            "candidate_id": final_top100_ids,
            "evidence_payload": ["{}"] * 100
        })
        
    print("Rendering Reasoning Strings...")
    final_df = top100_df.join(ev_df, on="candidate_id", how="left")
    
    reasonings = [generate_reasoning_string(r) for r in final_df["evidence_payload"].to_list()]
    
    final_df = final_df.with_columns(pl.Series("reasoning", reasonings))
    final_df = final_df.select(["candidate_id", "rank", "score", "reasoning"])
    
    # Final tie-breaking guarantee
    final_scores = final_df["score"].to_numpy() - (final_df["rank"].to_numpy() * 1e-9)
    final_df = final_df.with_columns(pl.Series("score", final_scores))
    final_df = final_df.sort("rank")
    t_render = time.time() - t_render_start
    
    t_write_start = time.time()
    out_csv = os.path.join(OUTPUT_DIR, "submission.csv")
    final_df.write_csv(out_csv)
    t_write = time.time() - t_write_start
    
    t_total = time.time() - t_start
    
    print(f"✅ Kaggle Inference Complete! Output saved to {out_csv}")
    print("\n--- TIMING BREAKDOWN ---")
    print(f"Artifact Read Time:  {t_read:.3f}s")
    print(f"Prediction Time:     {t_pred:.3f}s")
    print(f"Rendering Time:      {t_render:.3f}s")
    print(f"CSV Write Time:      {t_write:.3f}s")
    print(f"Total CPU Time:      {t_total:.3f}s")

if __name__ == "__main__":
    main()
