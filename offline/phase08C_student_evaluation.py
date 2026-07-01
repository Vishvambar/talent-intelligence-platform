import os
import json
import numpy as np
import polars as pl
from scipy.stats import spearmanr, kendalltau

OUTPUT_DIR = "artifacts/phase08"

def evaluate_student():
    print("--- PHASE 8C: Teacher vs Student Evaluation ---")
    df = pl.read_parquet(os.path.join(OUTPUT_DIR, "student_predictions.parquet"))
    
    # Check that df has teacher_rank and student_rank
    if "teacher_rank" not in df.columns or "student_rank" not in df.columns:
        print("Missing rank columns in student_predictions.parquet!")
        return
        
    t_rank = df["teacher_rank"].to_numpy()
    s_rank = df["student_rank"].to_numpy()
    
    # 1. Top-K Overlaps
    def top_k_overlap(k):
        t_top = set(df.filter(pl.col("teacher_rank") <= k)["candidate_id"].to_list())
        s_top = set(df.filter(pl.col("student_rank") <= k)["candidate_id"].to_list())
        return len(t_top & s_top) / max(1, k)
        
    overlaps = {
        "top_1": top_k_overlap(1),
        "top_10": top_k_overlap(10),
        "top_25": top_k_overlap(25),
        "top_50": top_k_overlap(50),
        "top_100": top_k_overlap(100),
        "top_300": top_k_overlap(300),
    }
    
    # 2. Recall at K (Assuming Top K of Teacher is the ground truth)
    def recall_at_k(k):
        t_top = set(df.filter(pl.col("teacher_rank") <= k)["candidate_id"].to_list())
        s_top = set(df.filter(pl.col("student_rank") <= k)["candidate_id"].to_list())
        return len(t_top & s_top) / max(1, len(t_top))

    recalls = {
        "recall_100": recall_at_k(100),
        "recall_300": recall_at_k(300),
        "recall_500": recall_at_k(500),
    }

    # 3. Mean Rank Error
    mean_rank_error = float(np.mean(np.abs(t_rank - s_rank)))
    
    # 4. Average NDCG Loss (using simple relevances if teacher_relevance is available)
    # To compute this, we need teacher relevances. We can load them from the parquet.
    if "teacher_relevance" in df.columns:
        y = df["teacher_relevance"].to_numpy()
        ideal_relevances = np.sort(y)[::-1]
        
        # Helper for NDCG
        def dcg_at_k(relevances, k):
            relevances = np.array(relevances[:k])
            if len(relevances) == 0: return 0.0
            gains = (2 ** relevances - 1) / np.log2(np.arange(2, len(relevances) + 2))
            return float(np.sum(gains))

        def ndcg_at_k(ranked_relevances, ideal_relevances, k):
            idcg = dcg_at_k(ideal_relevances, k)
            if idcg == 0: return 0.0
            return dcg_at_k(ranked_relevances, k) / idcg
            
        t_order_rels = df.sort("teacher_rank")["teacher_relevance"].to_numpy()
        s_order_rels = df.sort("student_rank")["teacher_relevance"].to_numpy()
        
        t_ndcg10 = ndcg_at_k(t_order_rels, ideal_relevances, 10)
        s_ndcg10 = ndcg_at_k(s_order_rels, ideal_relevances, 10)
        ndcg10_loss = float(t_ndcg10 - s_ndcg10)
    else:
        ndcg10_loss = 0.0
    
    # 5. Correlations
    spearman, _ = spearmanr(t_rank, s_rank)
    kendall, _ = kendalltau(t_rank, s_rank)
    
    metrics = {
        "teacher_vs_student_overlap": overlaps,
        "recall_at_k": recalls,
        "mean_rank_error": mean_rank_error,
        "ndcg10_loss": ndcg10_loss,
        "spearman_rho": float(spearman),
        "kendall_tau": float(kendall)
    }
    
    with open(os.path.join(OUTPUT_DIR, "metrics.json"), "w") as f:
        json.dump(metrics, f, indent=2)
        
    print(f"  Top 1 Overlap:   {overlaps['top_1']:.0%}")
    print(f"  Top 10 Overlap:  {overlaps['top_10']:.0%}")
    print(f"  Top 100 Overlap: {overlaps['top_100']:.0%}")
    print(f"  Recall@100:      {recalls['recall_100']:.0%}")
    print(f"  Recall@300:      {recalls['recall_300']:.0%}")
    print(f"  Recall@500:      {recalls['recall_500']:.0%}")
    print(f"  Mean Rank Error: {mean_rank_error:.1f} positions")
    print(f"  NDCG@10 Loss:    {ndcg10_loss:.4f}")
    print(f"  Spearman Rho:    {spearman:.3f}")
    
    print("✅ Phase 8C Complete! Metrics saved.")

if __name__ == "__main__":
    evaluate_student()
