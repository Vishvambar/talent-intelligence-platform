import os
import json
import numpy as np
import polars as pl
from scipy.stats import pearsonr, spearmanr, kendalltau

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

def generate_dashboard():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print("--- PHASE 9D: Model Comparison Dashboard ---")
    
    try:
        # Load predictions
        lgbm_df = pl.read_parquet(os.path.join(PHASE8_DIR, "student_predictions.parquet"))
        xgb_df = pl.read_parquet(os.path.join(OUTPUT_DIR, "oof_predictions.parquet"))
        ens_df = pl.read_parquet(os.path.join(OUTPUT_DIR, "ensemble_predictions.parquet"))
        elite_df = pl.read_parquet(os.path.join(OUTPUT_DIR, "elite_predictions.parquet"))
    except FileNotFoundError:
        print("Required parquets not found! Ensure 9A, 9B, 9C have been run.")
        return
        
    df = ens_df.join(lgbm_df.select(["candidate_id", "student_score"]), on="candidate_id")
    
    # ---------------------------------------------------------
    # COMPLEMENTARITY METRICS (LGBM vs XGBoost)
    # ---------------------------------------------------------
    lgbm_scores = df["student_score"].to_numpy()
    xgb_scores = df["xgb_oof_score"].to_numpy()
    
    pearson_corr, _ = pearsonr(lgbm_scores, xgb_scores)
    spearman_corr, _ = spearmanr(lgbm_scores, xgb_scores)
    kendall_corr, _ = kendalltau(lgbm_scores, xgb_scores)
    
    # ---------------------------------------------------------
    # OVERLAP CASCADES
    # ---------------------------------------------------------
    def get_top_ids(d, rank_col, k):
        return set(d.sort(rank_col).head(k)["candidate_id"].to_list())
        
    t_top100 = get_top_ids(df, "teacher_rank", 100)
    l_top100 = get_top_ids(df, "student_rank", 100)
    x_top100 = get_top_ids(df, "xgb_rank", 100)
    e_top100 = get_top_ids(df, "ensemble_rank", 100)
    el_top100 = get_top_ids(elite_df, "elite_rank", 100)
    
    overlap_lx_pct = (len(l_top100.intersection(x_top100)) / 100.0) * 100
    overlap_te_pct = (len(t_top100.intersection(e_top100)) / 100.0) * 100
    overlap_tel_pct = (len(t_top100.intersection(el_top100)) / 100.0) * 100
    
    # ---------------------------------------------------------
    # ENSEMBLE GAINS
    # ---------------------------------------------------------
    y = df["teacher_relevance"].to_numpy()
    ideal_relevances = np.sort(y)[::-1]
    
    def score_df(score_col):
        sorted_y = y[np.argsort(df[score_col].to_numpy())[::-1]]
        n10 = ndcg_at_k(sorted_y, ideal_relevances, 10)
        n50 = ndcg_at_k(sorted_y, ideal_relevances, 50)
        return n10, n50
        
    lgbm_n10, lgbm_n50 = score_df("student_score")
    ens_n10, ens_n50 = score_df("ensemble_score")
    
    # For Elite, sort by elite_rank to preserve 0.0 ties correctly
    sorted_elite = y[np.argsort(elite_df["elite_rank"].to_numpy())]
    elite_n10 = ndcg_at_k(sorted_elite, ideal_relevances, 10)
    elite_n50 = ndcg_at_k(sorted_elite, ideal_relevances, 50)
    
    gain_n10 = ens_n10 - lgbm_n10
    gain_n50 = ens_n50 - lgbm_n50
    elite_gain_n10 = elite_n10 - lgbm_n10
    elite_gain_n50 = elite_n50 - lgbm_n50
    
    # ---------------------------------------------------------
    # GENERATE MARKDOWN
    # ---------------------------------------------------------
    md = "# Phase 9 Ensemble Comparison Dashboard\n\n"
    
    md += "## 1. Model Complementarity (LightGBM vs XGBoost)\n"
    md += "If these are < 0.95, the models are successfully catching each other's blind spots.\n"
    md += f"- **Pearson Correlation (Raw Scores):** {pearson_corr:.4f}\n"
    md += f"- **Spearman Correlation (Rank Order):** {spearman_corr:.4f}\n"
    md += f"- **Kendall Tau:** {kendall_corr:.4f}\n\n"
    
    md += "## 2. Overlap Cascade (Top 100)\n"
    md += f"- **LightGBM vs XGBoost Overlap:** {overlap_lx_pct:.1f}%\n"
    md += f"- **Ensemble vs Teacher Overlap:** {overlap_te_pct:.1f}%\n"
    md += f"- **Elite vs Teacher Overlap:** {overlap_tel_pct:.1f}%\n\n"
    
    md += "## 3. Ensemble Gains\n"
    md += "| Metric | LightGBM Student | XGBoost OOF | Ensemble | Elite Rerank | Gain over LGBM (Elite) |\n"
    md += "|---|---|---|---|---|---|\n"
    md += f"| NDCG@10 | {lgbm_n10:.4f} | {score_df('xgb_oof_score')[0]:.4f} | {ens_n10:.4f} | {elite_n10:.4f} | **{elite_gain_n10:+.4f}** |\n"
    md += f"| NDCG@50 | {lgbm_n50:.4f} | {score_df('xgb_oof_score')[1]:.4f} | {ens_n50:.4f} | {elite_n50:.4f} | **{elite_gain_n50:+.4f}** |\n\n"
    
    # Load Feature Importance
    try:
        with open(os.path.join(PHASE8_DIR, "feature_importance.json"), "r") as f:
            lgbm_fi = json.load(f)
        with open(os.path.join(OUTPUT_DIR, "feature_importance.json"), "r") as f:
            xgb_fi = json.load(f)
            
        l_top = sorted(lgbm_fi.items(), key=lambda x: x[1], reverse=True)[:5]
        x_top = sorted(xgb_fi.items(), key=lambda x: x[1], reverse=True)[:5]
        
        md += "## 4. Top Feature Divergence\n"
        md += "| Rank | LightGBM Top Feature | XGBoost Top Feature |\n"
        md += "|---|---|---|\n"
        for i in range(5):
            md += f"| {i+1} | {l_top[i][0]} | {x_top[i][0]} |\n"
    except FileNotFoundError:
        md += "\n*Feature importance JSONs missing, skipping FI comparison.*"
        
    with open(os.path.join(OUTPUT_DIR, "ensemble_dashboard.md"), "w") as f:
        f.write(md)
        
    print("✅ Phase 9D Complete! Dashboard generated at artifacts/phase09/ensemble_dashboard.md")

if __name__ == "__main__":
    generate_dashboard()
