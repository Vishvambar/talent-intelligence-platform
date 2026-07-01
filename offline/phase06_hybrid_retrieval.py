import os
import json
import time
import numpy as np
import polars as pl
from collections import defaultdict
from sklearn.feature_extraction.text import CountVectorizer

# --- CONFIGURATION FOR KAGGLE OFFLINE ---
PHASE05_OUTPUT_DIR = "/kaggle/working/phase05"
PHASE03_ARTIFACTS_DIR = "/kaggle/working/artifacts/phase03"
PHASE04_ARTIFACTS_DIR = "/kaggle/working/artifacts/phase04"
PHASE01_ARTIFACTS_DIR = "/kaggle/working/artifacts/phase01"
OUTPUT_DIR = "/kaggle/working/phase06"

# For local testing, fallback paths
if not os.path.exists(PHASE05_OUTPUT_DIR):
    PHASE05_OUTPUT_DIR = "phase_5_output"
    PHASE03_ARTIFACTS_DIR = "data/artifacts/phase03"
    PHASE04_ARTIFACTS_DIR = "data/artifacts/phase04"
    PHASE01_ARTIFACTS_DIR = "data/artifacts/phase01"
    OUTPUT_DIR = "phase_6_output"

# Configurable Pool Sizes
DENSE_POOL_SIZE = 15000
BM25_POOL_SIZE = 10000
FINAL_POOL_SIZE = 3000
RRF_K = 60

os.makedirs(OUTPUT_DIR, exist_ok=True)

class VectorizedBM25:
    def __init__(self, k1=1.5, b=0.75):
        self.k1 = k1
        self.b = b
        self.vectorizer = CountVectorizer(lowercase=True, token_pattern=r'(?u)\b\w+\b')
        
    def fit(self, corpus):
        print("    Fitting CountVectorizer for BM25...")
        self.X = self.vectorizer.fit_transform(corpus)
        self.doc_len = self.X.sum(axis=1).A1
        self.avgdl = self.doc_len.mean()
        df = np.diff(self.X.indptr)
        N = self.X.shape[0]
        self.idf = np.log((N - df + 0.5) / (df + 0.5) + 1)
        
    def get_top_k(self, query, k=10000):
        print("    Transforming Query and Calculating Scores...")
        query_vec = self.vectorizer.transform([query]).tocoo()
        query_terms_idx = query_vec.col
        
        if len(query_terms_idx) == 0:
            return [], []
            
        scores = np.zeros(self.X.shape[0], dtype=np.float32)
        for idx in query_terms_idx:
            tf = self.X[:, idx].toarray().flatten()
            numerator = tf * (self.k1 + 1)
            denominator = tf + self.k1 * (1 - self.b + self.b * (self.doc_len / self.avgdl))
            scores += self.idf[idx] * (numerator / denominator)
            
        top_indices_unsorted = np.argpartition(scores, -k)[-k:]
        top_indices = top_indices_unsorted[np.argsort(scores[top_indices_unsorted])[::-1]]
        return top_indices.tolist(), scores[top_indices].tolist()

def main():
    print("=== REDROB PHASE 6: CANDIDATE RECALL ENGINE ===\n")
    overall_start_time = time.time()
    
    # 1. Dynamic Discovery (Hardcoded since file was generated locally)
    p5_summary = {
      "views": ["profile", "career", "skills", "projects", "github", "retrieval"],
      "models": ["bge-large-en-v1.5", "e5-large-v2"],
      "dimensions": {"bge": 1024, "e5": 1024},
      "candidate_count": 100000
    }
        
    views = p5_summary["views"]
    models = p5_summary["models"]
    
    # Load candidate mapping and deduplication
    print("Loading Metadata and Deduplicating...")
    df_cand = pl.read_parquet(os.path.join(PHASE05_OUTPUT_DIR, "metadata", "candidate_ids.parquet"))
    candidate_ids_full = df_cand["candidate_id"].to_list()
    
    df_meta = pl.read_parquet(os.path.join(PHASE05_OUTPUT_DIR, "metadata", "retrieval_metadata.parquet"))
    
    # Keep only first occurrence of each sha256 to drop duplicates
    df_unique = df_meta.unique(subset=["retrieval_sha256"], keep="first")
    valid_cids = set(df_unique["candidate_id"].to_list())
    
    # Boolean mask for valid (non-duplicate) candidates
    valid_mask = np.array([c in valid_cids for c in candidate_ids_full], dtype=bool)
    candidate_ids = np.array(candidate_ids_full)[valid_mask]
    
    print(f"  -> Total vectors: {len(candidate_ids_full)}")
    print(f"  -> Deduplicated unique candidates: {len(candidate_ids)}")
    
    # Load JD Requirements for Query & Coverage
    with open(os.path.join(PHASE01_ARTIFACTS_DIR, "jd_requirements.json"), "r") as f:
        jd_reqs = json.load(f)
        
    hiring_intent = jd_reqs.get("hiring_intent", {})
    tech_reqs = hiring_intent.get("technical_priorities", {})
    behav_reqs = hiring_intent.get("behavioral_priorities", {})
    biz_reqs = hiring_intent.get("business_priorities", {})
    impl_reqs = hiring_intent.get("implicit_priorities", {})
    
    jd_text = jd_reqs.get("hiring_summary", {}).get("executive_summary", "")
    
    # Track metrics for all candidates
    candidate_data = defaultdict(dict)
    
    bitmask_mapping = {}
    bit_idx = 0
    
    print("\n--- 1. MULTI-VIEW DENSE RETRIEVAL ---")
    dense_rrf_scores = defaultdict(float)
    
    for model_name in ["bge", "e5"]:
        jd_emb_path = os.path.join(PHASE05_OUTPUT_DIR, model_name, "jd.npy")
        jd_emb = np.load(jd_emb_path).squeeze()
        
        # Verify normalization
        assert abs(np.linalg.norm(jd_emb) - 1.0) < 1e-4, f"JD Embedding {model_name} is not normalized!"
        
        for view in views:
            feature_name = f"{model_name}_{view}"
            bitmask_mapping[feature_name] = 1 << bit_idx
            bit_idx += 1
            
            print(f"  -> Processing {feature_name}...")
            npy_path = os.path.join(PHASE05_OUTPUT_DIR, model_name, f"{view}.npy")
            # Memory map to save RAM
            mat = np.load(npy_path, mmap_mode='r')
            
            # Filter to valid duplicates
            mat_valid = mat[valid_mask]
            
            # Dot product for cosine similarity
            scores = np.dot(mat_valid, jd_emb)
            
            # Store raw scores and percentiles for all valid candidates
            # Vectorized percentile rank approximation
            sort_indices = np.argsort(scores)
            ranks = np.empty_like(sort_indices)
            ranks[sort_indices] = np.arange(len(scores))
            percentiles = (ranks / (len(scores) - 1)) * 100.0
            
            # Rank descending (rank 1 is highest score)
            desc_ranks = len(scores) - ranks
            
            # Populate data
            for i, c_id in enumerate(candidate_ids):
                candidate_data[c_id][f"{feature_name}_score"] = float(scores[i])
                candidate_data[c_id][f"{feature_name}_rank"] = int(desc_ranks[i])
                candidate_data[c_id][f"{feature_name}_pct"] = float(percentiles[i])
            
            # Extract Top-K for Dense RRF
            top_k_idx = sort_indices[-DENSE_POOL_SIZE:][::-1]
            for rank, idx in enumerate(top_k_idx, start=1):
                c_id = candidate_ids[idx]
                dense_rrf_scores[c_id] += 1.0 / (RRF_K + rank)
                
                # Assign bitmask provenance
                if "retrieval_mask" not in candidate_data[c_id]:
                    candidate_data[c_id]["retrieval_mask"] = 0
                candidate_data[c_id]["retrieval_mask"] |= bitmask_mapping[feature_name]

    print(f"\nSorting Dense RRF to extract Top {DENSE_POOL_SIZE}...")
    sorted_dense = sorted(dense_rrf_scores.items(), key=lambda x: x[1], reverse=True)[:DENSE_POOL_SIZE]
    dense_pool_ids = [k for k, v in sorted_dense]
    
    print("\n--- 2. SPARSE RETRIEVAL (BM25) ---")
    bitmask_mapping["bm25"] = 1 << bit_idx
    
    print("Loading candidate texts...")
    df_texts = pl.read_parquet(os.path.join(PHASE03_ARTIFACTS_DIR, "candidate_texts.parquet"))
    
    # Filter to valid candidates and concatenate corpus (now including education)
    df_texts_valid = df_texts.filter(pl.col("candidate_id").is_in(list(valid_cids)))
    df_texts_valid = df_texts_valid.with_columns(
        pl.concat_str([
            pl.col("profile_text").fill_null(""),
            pl.lit(" "),
            pl.col("career_text").fill_null(""),
            pl.lit(" "),
            pl.col("education_text").fill_null(""),
            pl.lit(" "),
            pl.col("skills_text").fill_null(""),
            pl.lit(" "),
            pl.col("projects_text").fill_null(""),
            pl.lit(" "),
            pl.col("github_text").fill_null("")
        ]).alias("bm25_corpus")
    )
    
    bm25_corpus = df_texts_valid["bm25_corpus"].to_list()
    bm25_cids = df_texts_valid["candidate_id"].to_list()
    
    bm25 = VectorizedBM25()
    bm25.fit(bm25_corpus)
    bm25_top_idx, bm25_scores = bm25.get_top_k(jd_text, k=BM25_POOL_SIZE)
    
    bm25_pool_ids = []
    for rank, idx in enumerate(bm25_top_idx, start=1):
        c_id = bm25_cids[idx]
        bm25_pool_ids.append(c_id)
        candidate_data[c_id]["bm25_score"] = float(bm25_scores[rank-1])
        candidate_data[c_id]["bm25_rank"] = rank
        if "retrieval_mask" not in candidate_data[c_id]:
            candidate_data[c_id]["retrieval_mask"] = 0
        candidate_data[c_id]["retrieval_mask"] |= bitmask_mapping["bm25"]

    print("\n--- 3. GLOBAL RRF FUSION ---")
    global_scores = defaultdict(float)
    
    for rank, c_id in enumerate(dense_pool_ids, start=1):
        global_scores[c_id] += 1.0 / (RRF_K + rank)
        
    for rank, c_id in enumerate(bm25_pool_ids, start=1):
        global_scores[c_id] += 1.0 / (RRF_K + rank)
        
    sorted_global = sorted(global_scores.items(), key=lambda x: x[1], reverse=True)[:FINAL_POOL_SIZE]
    final_pool_ids = [k for k, v in sorted_global]
    
    print("\n--- 4. FEATURE HYDRATION (JOINING PHASES 3 & 4) ---")
    df_features = pl.read_parquet(os.path.join(PHASE03_ARTIFACTS_DIR, "candidate_features.parquet"))
    df_integrity = pl.read_parquet(os.path.join(PHASE04_ARTIFACTS_DIR, "candidate_integrity.parquet"))
    
    features_dict = {row["candidate_id"]: row for row in df_features.to_dicts()}
    integrity_dict = {row["candidate_id"]: row for row in df_integrity.to_dicts()}
    
    final_output = []
    
    def get_matched_keys(req_dict, c_feat):
        if not req_dict: return []
        return [k for k in req_dict.keys() if c_feat.get(f"{k}_score", 0) > 0]
        
    def get_weighted_coverage(req_dict, c_feat):
        if not req_dict: return 0.0
        total_wt = sum(v.get("priority_weight", 1.0) for v in req_dict.values())
        if total_wt == 0: return 0.0
        hits_wt = sum(v.get("priority_weight", 1.0) for k, v in req_dict.items() if c_feat.get(f"{k}_score", 0) > 0)
        return hits_wt / total_wt
    
    print("Computing advanced retrieval features and provenance...")
    for rank, (c_id, score) in enumerate(sorted_global, start=1):
        data = candidate_data[c_id]
        
        # Retrieval Provenance
        mask = data.get("retrieval_mask", 0)
        retrieval_votes = bin(mask).count("1")
        retrieved_by = [name for name, bit in bitmask_mapping.items() if mask & bit]
        
        # Dense Consensus Score (Fraction of dense views they appeared in Top K)
        dense_votes = sum(1 for ch in retrieved_by if ch != "bm25")
        dense_consensus_score = dense_votes / 12.0
        
        # Average Percentile across retrieved dense channels
        pcts = [data.get(f"{ch}_pct", 0) for ch in retrieved_by if ch != "bm25"]
        avg_retrieved_percentile = sum(pcts) / len(pcts) if pcts else 0.0
        
        # Retrieval Diversity Score
        # E.g., if retrieved by profile, career, skills, projects (diverse) vs just profile (not diverse)
        # We approximate by counting unique base scopes (profile, career, etc.) across models
        scopes_hit = set([ch.split("_")[1] for ch in retrieved_by if "_" in ch])
        retrieval_diversity = len(scopes_hit) / float(len(views))
        
        # Priority Coverage (using Phase 3 features and JD weights)
        c_feat = features_dict.get(c_id, {})
        c_integ = integrity_dict.get(c_id, {})
        
        tech_cov = get_weighted_coverage(tech_reqs, c_feat)
        behav_cov = get_weighted_coverage(behav_reqs, c_feat)
        biz_cov = get_weighted_coverage(biz_reqs, c_feat)
        impl_cov = get_weighted_coverage(impl_reqs, c_feat)
            
        graph_size_proxy = c_feat.get("graph_edge_count", 0)
        
        # Structured Retrieval Explanation
        explanation = {
            "primary_reason": "High Dense Consensus" if dense_consensus_score > 0.7 else ("Strong Keyword Match" if data.get("bm25_rank", 99999) <= 1000 else "Aggregate Semantic Overlap"),
            "supporting_channels": retrieved_by,
            "technical_coverage": round(tech_cov, 3),
            "behavioral_coverage": round(behav_cov, 3),
            "business_coverage": round(biz_cov, 3),
            "implicit_coverage": round(impl_cov, 3),
            "diversity_score": round(retrieval_diversity, 3),
            "matched_priorities": get_matched_keys(tech_reqs, c_feat),
            "matched_behaviors": get_matched_keys(behav_reqs, c_feat),
            "matched_business_signals": get_matched_keys(biz_reqs, c_feat)
        }
        
        row = {
            "candidate_id": c_id,
            "rrf_rank": rank,
            "rrf_score": score,
            "dense_rrf_score": dense_rrf_scores.get(c_id, 0.0),
            "bm25_score": data.get("bm25_score", 0.0),
            "bm25_rank": data.get("bm25_rank", -1),
            "retrieval_mask": mask,
            "retrieval_votes": retrieval_votes,
            "dense_consensus_score": dense_consensus_score,
            "average_retrieved_percentile": avg_retrieved_percentile,
            "retrieval_diversity": retrieval_diversity,
            "technical_coverage": tech_cov,
            "behavioral_coverage": behav_cov,
            "business_coverage": biz_cov,
            "implicit_coverage": impl_cov,
            "graph_size_proxy": graph_size_proxy,
            "retrieval_explanation": json.dumps(explanation)
        }
        
        # Append 12 view scores, ranks, and percentiles
        for name in bitmask_mapping.keys():
            if name != "bm25":
                row[f"{name}_score"] = data.get(f"{name}_score", 0.0)
                row[f"{name}_rank"] = data.get(f"{name}_rank", -1)
                row[f"{name}_pct"] = data.get(f"{name}_pct", 0.0)
                
        # Hydrate with Phase 3 & 4
        # We take a select subset of powerful features so Phase 7 has a rich context
        for f in ["years_exp", "avg_tenure", "title_inflation_score", "product_company_score", 
                  "startup_score", "graph_edge_count", "expanded_ratio"]:
            row[f] = c_feat.get(f, 0.0)
            
        for f in ["evidence_strength_score", "integrity_score", "anomaly_count", 
                  "career_gap_months", "salary_percentile"]:
            row[f] = c_integ.get(f, 0.0)
            
        final_output.append(row)
        
    df_final = pl.DataFrame(final_output)
    
    print("\n--- 5. SAVING ARTIFACTS ---")
    df_final.write_parquet(os.path.join(OUTPUT_DIR, "retrieval_pool.parquet"))
    
    # Save Statistics & Audit
    bm25_bit = bitmask_mapping["bm25"]
    df_final = df_final.with_columns([
        (pl.col("retrieval_mask") & bm25_bit > 0).alias("has_bm25"),
        ((pl.col("retrieval_mask") & ~bm25_bit) > 0).alias("has_dense")
    ])
    
    dense_only_pct = df_final.filter(pl.col("has_dense") & ~pl.col("has_bm25")).height / FINAL_POOL_SIZE * 100
    bm25_only_pct = df_final.filter(~pl.col("has_dense") & pl.col("has_bm25")).height / FINAL_POOL_SIZE * 100
    dense_bm25_pct = df_final.filter(pl.col("has_dense") & pl.col("has_bm25")).height / FINAL_POOL_SIZE * 100
    
    stats = {
        "dense_pool_size": DENSE_POOL_SIZE,
        "bm25_pool_size": BM25_POOL_SIZE,
        "final_pool_size": FINAL_POOL_SIZE,
        "total_unique_candidates": len(valid_cids),
        "mean_retrieval_votes": df_final["retrieval_votes"].mean(),
        "mean_dense_consensus": df_final["dense_consensus_score"].mean(),
        "mean_technical_coverage": df_final["technical_coverage"].mean(),
        "mean_behavioral_coverage": df_final["behavioral_coverage"].mean(),
        "mean_business_coverage": df_final["business_coverage"].mean(),
        "mean_implicit_coverage": df_final["implicit_coverage"].mean(),
        "mean_average_retrieved_percentile": df_final["average_retrieved_percentile"].mean(),
        "recall_overlap": {
            "dense_only_pct": round(dense_only_pct, 2),
            "bm25_only_pct": round(bm25_only_pct, 2),
            "dense_bm25_pct": round(dense_bm25_pct, 2)
        },
        "average_rrf_score": df_final["rrf_score"].mean(),
        "median_rrf_score": df_final["rrf_score"].median()
    }
    
    # Audit for top 100
    top_100 = df_final.head(100)
    audit = {
        "execution_time_sec": round(time.time() - overall_start_time, 2),
        "top_10_candidates": top_100["candidate_id"].head(10).to_list(),
        "top_10_explanations": [json.loads(exp) for exp in top_100["retrieval_explanation"].head(10).to_list()],
        "channel_usage_top100": {
            name: sum(1 for mask in top_100["retrieval_mask"] if mask & bit)
            for name, bit in bitmask_mapping.items()
        }
    }
    
    with open(os.path.join(OUTPUT_DIR, "retrieval_statistics.json"), "w") as f:
        json.dump(stats, f, indent=2)
        
    with open(os.path.join(OUTPUT_DIR, "retrieval_audit.json"), "w") as f:
        json.dump(audit, f, indent=2)
        
    print(f"\n✅ Phase 6 Complete! Output artifacts saved to {OUTPUT_DIR}")
    print(json.dumps(stats, indent=2))

if __name__ == "__main__":
    main()
