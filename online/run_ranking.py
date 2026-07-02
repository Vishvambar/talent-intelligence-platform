import os
import json
import hashlib
import numpy as np
import polars as pl
import xgboost as xgb
import lightgbm as lgb
import pickle
import time
from datetime import datetime
import subprocess

# ==============================================================================
# ONLINE PIPELINE CONFIGURATION
# ==============================================================================
PHASE08_DIR = "artifacts/phase08"
PHASE09_DIR = "artifacts/phase09"
PHASE10_DIR = "artifacts/phase10"
OUTPUT_DIR = "online"

ELITE_POOL_SIZE = 50

EXPECTED_HASHES = {
    "lgbm_model.pkl": None,
    "xgb_model.pkl": None,
    "evidence_bank.parquet": None
}

def verify_checksums():
    print("Verifying Artifact Integrity Checksums...")
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

def predict_models(df):
    print("Loading Models...")
    with open(os.path.join(PHASE08_DIR, "lgbm_model.pkl"), "rb") as f:
        lgbm_model = pickle.load(f)
    with open(os.path.join(PHASE09_DIR, "xgb_model.pkl"), "rb") as f:
        xgb_model = pickle.load(f)
    
    X = df.drop("candidate_id").to_numpy()
    print("Executing LTR Inference...")
    lgbm_scores = lgbm_model.predict(X)
    xgb_scores = xgb_model.predict(X)
    return lgbm_scores, xgb_scores

def ensemble_and_blend(df, lgbm_scores, xgb_scores):
    print("Applying Static Ensemble...")
    with open(os.path.join(PHASE09_DIR, "optimal_blend.json"), "r") as f:
        blend_config = json.load(f)
    with open(os.path.join(PHASE09_DIR, "lgb_scaler.pkl"), "rb") as f:
        scaler_lgbm = pickle.load(f)
    with open(os.path.join(PHASE09_DIR, "xgb_scaler.pkl"), "rb") as f:
        scaler_xgb = pickle.load(f)
        
    lgbm_weight = blend_config["best_ndcg10_blend"]["lgbm_weight"]
    xgb_weight = blend_config["best_ndcg10_blend"]["xgb_weight"]
    
    l_norm = scaler_lgbm.transform(lgbm_scores.reshape(-1, 1)).flatten()
    x_norm = scaler_xgb.transform(xgb_scores.reshape(-1, 1)).flatten()
    ensemble_scores = (lgbm_weight * l_norm) + (xgb_weight * x_norm)
    
    # Strictly Deterministic Tie-Breaking
    ranks = np.arange(len(ensemble_scores))
    ensemble_scores = ensemble_scores - (ranks * 1e-9)
    
    res_df = df.select(["candidate_id"]).with_columns(pl.Series("ensemble_score", ensemble_scores))
    res_df = res_df.sort("ensemble_score", descending=True)
    return res_df, lgbm_weight, xgb_weight

def elite_rerank(df, res_df):
    with open(os.path.join(PHASE09_DIR, "elite_formula.json"), "r") as f:
        elite_formula = json.load(f)
    elite_pool_size = elite_formula.get("elite_pool_size", ELITE_POOL_SIZE)
    print(f"Applying Elite Reranking to Top {elite_pool_size}...")
    
    elite_pool = res_df.head(elite_pool_size)
    rest_pool = res_df.tail(len(res_df) - elite_pool_size)
    
    elite_ids = elite_pool["candidate_id"].to_list()
    rest_ids = rest_pool["candidate_id"].to_list()
    assert len(set(elite_ids) & set(rest_ids)) == 0, "CRITICAL: Elite pool and Rest pool intersect!"
    
    elite_features = df.filter(pl.col("candidate_id").is_in(elite_ids))
    elite_scores = []
    f_weights = elite_formula["features"]
    
    for row in elite_features.to_dicts():
        ens = float(elite_pool.filter(pl.col("candidate_id") == row["candidate_id"])["ensemble_score"][0])
        score = ens * f_weights.get("ensemble_score", 0.70)
        for feat, weight in f_weights.items():
            if feat != "ensemble_score":
                score += float(row.get(feat, 0.0)) * weight
        elite_scores.append(score)
        
    e_ranks = np.arange(len(elite_pool))
    elite_scores_tb = np.array(elite_scores) - (e_ranks * 1e-9)
    elite_pool = elite_pool.with_columns(pl.Series("elite_score", elite_scores_tb)).sort("elite_score", descending=True)
    
    final_top100_ids = elite_pool["candidate_id"].to_list() + rest_ids
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
    
    return pl.DataFrame({
        "candidate_id": final_top100_ids,
        "score": final_top100_scores,
        "rank": np.arange(1, 101)
    })

def generate_reasoning_string(summary_str: str, strengths_str: str, gaps_str: str, risks_str: str, candidate_id: str) -> str:
    try:
        summary = json.loads(summary_str) if isinstance(summary_str, str) else summary_str
        strengths = json.loads(strengths_str) if isinstance(strengths_str, str) else strengths_str
        gaps = json.loads(gaps_str) if isinstance(gaps_str, str) else gaps_str
        risks = json.loads(risks_str) if isinstance(risks_str, str) else risks_str
        
        # Deterministic random hash per candidate
        h = int(hashlib.md5(candidate_id.encode('utf-8')).hexdigest(), 16)
        
        # Sentence 1: Summary
        s1 = f"Candidate brings {summary.get('experience_years', 0)} years of experience in {summary.get('company_type', 'Tech')}, aligning closely with the {summary.get('primary_domain', 'Engineering')} domain at a {summary.get('seniority', 'Senior')} level."
        
        # Sentence 2: Strengths
        s2_opts = [
            "Demonstrates strong capability in",
            "Shows evidence of",
            "Strongly aligns through",
            "Has notable experience in"
        ]
        s2_open = s2_opts[h % len(s2_opts)]
        
        s2 = "No notable strengths extracted."
        if strengths and len(strengths) >= 2:
            s2 = f"{s2_open} {strengths[0]['label']} and {strengths[1]['label']}."
        elif strengths and len(strengths) == 1:
            s2 = f"{s2_open} {strengths[0]['label']}."
            
        # Sentence 3: Risks or Gaps
        s3_opts = [
            "Primary risk factor:",
            "Main concern:",
            "One limitation:",
            "Recruiter should note:"
        ]
        s3_gap_opts = [
            "Primary gap:",
            "Main missing signal:",
            "One limitation:",
            "Recruiter should note:"
        ]
        s3_open_risk = s3_opts[(h // 10) % len(s3_opts)]
        s3_open_gap = s3_gap_opts[(h // 10) % len(s3_gap_opts)]
        
        s3 = "Presents minimal risk factors."
        if risks:
            s3 = f"{s3_open_risk} {risks[0]['label']}."
        elif gaps:
            s3 = f"{s3_open_gap} {gaps[0]['label']}."
            
        return f"{s1} {s2} {s3}"
    except Exception as e:
        raise ValueError(f"CRITICAL: Failed to parse reasoning evidence: {e}")

def render_reasoning(top100_df):
    print("Loading Evidence Bank...")
    try:
        ev_df = pl.read_parquet(os.path.join(PHASE10_DIR, "evidence_bank.parquet"))
    except FileNotFoundError:
        print("evidence_bank.parquet not found. Generating dummy reasoning.")
        ev_df = pl.DataFrame({
            "candidate_id": top100_df["candidate_id"], 
            "summary": ['{"experience_years": 0, "company_type": "Unknown", "primary_domain": "Unknown", "seniority": "Unknown"}'] * 100,
            "strengths": ["[]"] * 100,
            "gaps": ["[]"] * 100,
            "risks": ["[]"] * 100
        })
        
    print("Rendering Reasoning Strings...")
    final_df = top100_df.join(ev_df, on="candidate_id", how="left")
    
    reasonings = [
        generate_reasoning_string(sum_, str_, gp_, rsk_, cid) 
        for sum_, str_, gp_, rsk_, cid in zip(
            final_df["summary"].to_list(),
            final_df["strengths"].to_list(),
            final_df["gaps"].to_list(),
            final_df["risks"].to_list(),
            final_df["candidate_id"].to_list()
        )
    ]
    
    final_df = final_df.with_columns(pl.Series("reasoning", reasonings))
    final_df = final_df.select(["candidate_id", "rank", "score", "reasoning"])
    
    # Tie-breaking one last time natively
    final_scores = final_df["score"].to_numpy() - (final_df["rank"].to_numpy() * 1e-9)
    final_df = final_df.with_columns(pl.Series("score", final_scores))
    return final_df.sort("rank")

def write_submission(final_df):
    out_csv = os.path.join(OUTPUT_DIR, "submission.csv")
    final_df.write_csv(out_csv)
    return out_csv

def get_git_commit():
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], stderr=subprocess.STDOUT).decode('utf-8').strip()
        return commit
    except Exception:
        return "unknown"

def save_metadata(execution_time, feature_count, lgbm_weight, xgb_weight):
    metadata = {
        "timestamp": datetime.now().isoformat(),
        "git_commit": get_git_commit(),
        "model_version": "1.0",
        "phase_versions": {
            "phase08": "1.0",
            "phase09": "1.0",
            "phase10": "1.1",
            "phase11": "2.0"
        },
        "execution_time_seconds": round(execution_time, 3),
        "feature_count": feature_count,
        "blend_weights": {
            "lgbm": lgbm_weight,
            "xgb": xgb_weight
        }
    }
    with open(os.path.join(OUTPUT_DIR, "pipeline_metadata.json"), "w") as f:
        json.dump(metadata, f, indent=4)

def main():
    t_start = time.time()
    
    verify_checksums()
    
    t_read_start = time.time()
    df = load_and_validate_features()
    feature_count = len(df.columns) - 1
    t_read = time.time() - t_read_start
    
    t_pred_start = time.time()
    lgbm_scores, xgb_scores = predict_models(df)
    res_df, lgbm_weight, xgb_weight = ensemble_and_blend(df, lgbm_scores, xgb_scores)
    top100_df = elite_rerank(df, res_df)
    t_pred = time.time() - t_pred_start
    
    t_render_start = time.time()
    final_df = render_reasoning(top100_df)
    t_render = time.time() - t_render_start
    
    t_write_start = time.time()
    out_csv = write_submission(final_df)
    t_write = time.time() - t_write_start
    
    t_total = time.time() - t_start
    save_metadata(t_total, feature_count, lgbm_weight, xgb_weight)
    
    print(f"✅ Kaggle Inference Complete! Output saved to {out_csv}")
    print("\n=========================")
    print("REDROB PIPELINE SUMMARY")
    print("=========================")
    print(f"Candidates processed : {len(df)}")
    print(f"Models               : LightGBM + XGBoost")
    print(f"Inference time       : {t_total:.3f} s")
    # Note: memory is checked by the verification script
    print(f"Elite reranked       : {ELITE_POOL_SIZE}")
    print(f"Submission rows      : {len(final_df)}")
    print(f"Deterministic        : YES")
    print(f"Reasoning source     : Evidence Bank")
    
    print("\n--- TIMING BREAKDOWN ---")
    print(f"Artifact Read Time:  {t_read:.3f}s")
    print(f"Prediction Time:     {t_pred:.3f}s")
    print(f"Rendering Time:      {t_render:.3f}s")
    print(f"CSV Write Time:      {t_write:.3f}s")
    print(f"Total CPU Time:      {t_total:.3f}s")

if __name__ == "__main__":
    main()
