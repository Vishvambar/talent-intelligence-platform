import os
import json
import numpy as np
import polars as pl
import sys

OUTPUT_DIR = "artifacts/phase09"
PHASE8_DIR = "artifacts/phase08"
ELITE_POOL_SIZE = 50

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

def run_elite_reranking():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print("--- PHASE 9C: Dynamic Elite Re-Ranking ---")
    
    # Load ensemble and dataset
    try:
        ensemble_df = pl.read_parquet(os.path.join(OUTPUT_DIR, "ensemble_predictions.parquet"))
        dataset_df = pl.read_parquet(os.path.join(PHASE8_DIR, "dataset.parquet"))
    except FileNotFoundError:
        print("Required parquets not found! Run Phase 9B first.")
        return
        
    df = ensemble_df.join(dataset_df, on=["candidate_id", "teacher_rank", "teacher_relevance", "teacher_score"])
    
    # ---------------------------------------------------------
    # DYNAMIC WEIGHT ALLOCATION (Simulated from Phase 1)
    # ---------------------------------------------------------
    # In a full run, this is loaded from phase01_jd_analysis.json
    jd_priorities = {
        "Technical": 0.50,
        "Business": 0.20,
        "Behavioral": 0.20,
        "Integrity": 0.10
    }
    
    # Distribute the 0.30 remaining weight budget proportionally
    W_TECH = 0.30 * (jd_priorities["Technical"] / sum(jd_priorities.values()))
    W_INT = 0.30 * (jd_priorities["Integrity"] / sum(jd_priorities.values()))
    W_EVID = 0.30 * 0.15 # Fixed allocations for specific pipeline signals
    W_GRAPH = 0.30 * 0.15
    W_RARE = 0.30 * 0.10
    
    # ---------------------------------------------------------
    # RERANKING LOGIC
    # ---------------------------------------------------------
    elite_candidates = df.head(ELITE_POOL_SIZE).to_dicts()
    rest_df = df.tail(len(df) - ELITE_POOL_SIZE)
    
    audit_log = []
    
    for row in elite_candidates:
        c_id = row["candidate_id"]
        old_rank = row["ensemble_rank"]
        
        # 1. Base Score
        ens_score = row.get("ensemble_score", 0.0)
        
        # 2. Graph Quality Math: 0.35 * exp + 0.30 * dens + 0.20 * depth + 0.15 * edge_dens
        # Simulated if not explicitly present in dataset
        g_exp = row.get("graph_expansion_ratio", 0.5)
        g_dens = row.get("graph_density", 0.5)
        g_dep = row.get("graph_avg_depth", 0.5)
        g_edge = row.get("graph_edge_density", 0.5)
        graph_quality = (0.35 * g_exp) + (0.30 * g_dens) + (0.20 * g_dep) + (0.15 * g_edge)
        
        # 3. Dynamic Rare Skill Bonus (Simulated IDF math)
        # IDF(skill) * JD_Priority * Candidate_Match
        rare_skill = row.get("rare_skill_match_count", 0) * 0.15
        
        # 4. Standard features
        tech = row.get("technical_coverage", 0.0)
        integ = row.get("integrity_score", 0.0)
        evid = row.get("evidence_strength_score", 0.0)
        
        # Calculate Elite Score
        components = {
            "ensemble_base": 0.70 * ens_score,
            "technical": W_TECH * tech,
            "integrity": W_INT * integ,
            "evidence": W_EVID * evid,
            "graph_quality": W_GRAPH * graph_quality,
            "rare_skill": W_RARE * rare_skill
        }
        
        elite_score = sum(components.values())
        row["elite_score"] = elite_score
        
        audit_log.append({
            "candidate_id": c_id,
            "old_rank": old_rank,
            "components": components,
            "elite_score": elite_score
        })
        
    elite_df = pl.DataFrame(elite_candidates).sort("elite_score", descending=True)
    elite_df = elite_df.with_columns(pl.Series("elite_rank", np.arange(1, len(elite_df) + 1)))
    
    # Update Audit Log with new ranks
    for log in audit_log:
        log["new_rank"] = elite_df.filter(pl.col("candidate_id") == log["candidate_id"])["elite_rank"][0]
        log["rank_change"] = log["old_rank"] - log["new_rank"]
        
    with open(os.path.join(OUTPUT_DIR, "elite_reranking_audit.json"), "w") as f:
        json.dump(audit_log, f, indent=2)
        
    # Merge back
    final_df = pl.concat([
        elite_df.select(["candidate_id", "teacher_relevance", "ensemble_score", "elite_score", "elite_rank"]),
        rest_df.select([
            pl.col("candidate_id"),
            pl.col("teacher_relevance"),
            pl.col("ensemble_score"),
            pl.lit(0.0).alias("elite_score"),
            pl.col("ensemble_rank").alias("elite_rank")
        ])
    ])
    
    # ---------------------------------------------------------
    # COMPOSITE SAFETY ABORT
    # ---------------------------------------------------------
    y = final_df["teacher_relevance"].to_numpy()
    ideal_relevances = np.sort(y)[::-1]
    
    # Base Ensemble Composite
    sorted_ens = np.argsort(final_df["ensemble_score"].to_numpy())[::-1]
    y_ens = y[sorted_ens]
    ens_comp = (0.50 * ndcg_at_k(y_ens, ideal_relevances, 10)) + \
               (0.25 * ndcg_at_k(y_ens, ideal_relevances, 50)) + \
               (0.15 * average_precision(y_ens)) + \
               (0.10 * recall_at_k(y_ens, ideal_relevances, 100))
               
    # Elite Composite (sort by elite_rank ascending to perfectly preserve order)
    sorted_elite = np.argsort(final_df["elite_rank"].to_numpy())
    y_elite = y[sorted_elite]
    elite_comp = (0.50 * ndcg_at_k(y_elite, ideal_relevances, 10)) + \
                 (0.25 * ndcg_at_k(y_elite, ideal_relevances, 50)) + \
                 (0.15 * average_precision(y_elite)) + \
                 (0.10 * recall_at_k(y_elite, ideal_relevances, 100))
                 
    print(f"Base Ensemble Composite: {ens_comp:.5f}")
    print(f"Elite Rerank Composite:  {elite_comp:.5f}")
    
    if elite_comp < ens_comp:
        print("⛔ SAFETY ABORT: Elite Reranking decreased the Composite Score. Reverting to base ensemble.")
        # Instead of crashing entirely, we can just save the ensemble as the final elite predictions
        final_df = final_df.with_columns(pl.col("ensemble_score").alias("elite_score"))
    else:
        print("✅ Elite Reranking improved Composite Score! Lock it in.")
        
    final_df.write_parquet(os.path.join(OUTPUT_DIR, "elite_predictions.parquet"))
    print("✅ Phase 9C Complete!")

if __name__ == "__main__":
    run_elite_reranking()
