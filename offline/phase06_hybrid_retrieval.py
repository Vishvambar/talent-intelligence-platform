import os
import json
import time
import numpy as np
import polars as pl
from collections import defaultdict
from sklearn.feature_extraction.text import CountVectorizer

# --- CONFIGURATION FOR KAGGLE OFFLINE ---
INPUT_ARTIFACTS_DIR = "/kaggle/working/artifacts"
CANDIDATE_TEXTS_PARQUET = "/kaggle/input/datasets/vishvambarudavant/redrob-candidate-data/candidate_texts.parquet"
OUTPUT_DIR = "/kaggle/working/artifacts"

JD_TEXT = """
Senior AI Engineer Founding Team
Required: embeddings, vector databases, retrieval systems, ranking evaluation,
NDCG, MAP, semantic search, RAG, product company, startup
Experience: 5-9 years applied ML, production retrieval systems,
founding team mindset, fast execution, ownership
"""

# Weighted Dense RRF Config
DENSE_WEIGHTS = {
    "e5_career": 1.0,
    "e5_profile": 0.5,
    "e5_skills": 0.4,
    "bge_career": 0.9,
    "bge_profile": 0.4,
    "bge_skills": 0.3
}

DENSE_TOP_K_PER_INDEX = 5000
DENSE_RRF_POOL_SIZE = 10000
BM25_TOP_K = 10000
FINAL_TOP_K = 3000
RRF_K = 60

# --- PURE NUMPY BM25 (100% OFFLINE COMPATIBLE) ---
class VectorizedBM25:
    def __init__(self, k1=1.5, b=0.75):
        self.k1 = k1
        self.b = b
        self.vectorizer = CountVectorizer(lowercase=True, token_pattern=r'(?u)\b\w+\b')
        
    def fit(self, corpus):
        print("    Fitting CountVectorizer...")
        self.X = self.vectorizer.fit_transform(corpus)
        
        # Calculate doc lengths and average doc length
        self.doc_len = self.X.sum(axis=1).A1
        self.avgdl = self.doc_len.mean()
        
        # Calculate IDF
        df = np.diff(self.X.indptr)
        N = self.X.shape[0]
        # Standard BM25 IDF formulation
        self.idf = np.log((N - df + 0.5) / (df + 0.5) + 1)
        
    def get_top_k(self, query, k=10000):
        print("    Transforming Query...")
        query_vec = self.vectorizer.transform([query]).tocoo()
        
        query_terms_idx = query_vec.col
        
        if len(query_terms_idx) == 0:
            return [], []
            
        print("    Calculating BM25 Scores...")
        scores = np.zeros(self.X.shape[0], dtype=np.float32)
        
        for idx in query_terms_idx:
            # Term frequency in all docs
            tf = self.X[:, idx].toarray().flatten()
            
            # BM25 term weighting
            numerator = tf * (self.k1 + 1)
            denominator = tf + self.k1 * (1 - self.b + self.b * (self.doc_len / self.avgdl))
            
            # Add to scores
            scores += self.idf[idx] * (numerator / denominator)
            
        print("    Extracting Top K...")
        # O(n) extraction
        top_indices_unsorted = np.argpartition(scores, -k)[-k:]
        # Sort the top k
        top_indices = top_indices_unsorted[np.argsort(scores[top_indices_unsorted])[::-1]]
        
        return top_indices.tolist(), scores[top_indices].tolist()

def main():
    print("=== REDROB PHASE 6: HYBRID RETRIEVAL ===\n")
    overall_start_time = time.time()
    
    # 1. Load Data
    print("Loading Parquet Artifacts...")
    df_bge = pl.read_parquet(f"{INPUT_ARTIFACTS_DIR}/candidate_embeddings_bge.parquet")
    df_e5 = pl.read_parquet(f"{INPUT_ARTIFACTS_DIR}/candidate_embeddings_e5.parquet")
    jd_embs = np.load(f"{INPUT_ARTIFACTS_DIR}/jd_embeddings.npz")
    
    jd_bge = jd_embs["JD_BGE"].squeeze().astype(np.float32)
    jd_e5 = jd_embs["JD_E5"].squeeze().astype(np.float32)
    
    print("Loading Candidate Texts for BM25...")
    df_texts = pl.read_parquet(CANDIDATE_TEXTS_PARQUET)
    
    # Ensure aligned candidate IDs (they should be identical rows)
    candidate_ids = df_bge["candidate_id"].to_list()
    
    # 2. Dense Retrieval (Parallel Numpy Dot Products)
    print("\n--- 1. DENSE RETRIEVAL (FAISS Equivalent) ---")
    dense_rrf_scores = defaultdict(float)
    
    scopes = ["profile", "career", "skills"]
    
    # Query BGE
    print("\nQuerying BGE Indices...")
    for scope in scopes:
        print(f"  -> bge_{scope}")
        bge_vectors = np.vstack(df_bge[f"{scope}_vector"].to_list()).astype(np.float32)
        scores = np.dot(bge_vectors, jd_bge)
        
        # Fast Top-K extraction
        top_idx_unsorted = np.argpartition(scores, -DENSE_TOP_K_PER_INDEX)[-DENSE_TOP_K_PER_INDEX:]
        top_idx = top_idx_unsorted[np.argsort(scores[top_idx_unsorted])[::-1]]
        
        weight = DENSE_WEIGHTS[f"bge_{scope}"]
        for rank, idx in enumerate(top_idx, start=1):
            c_id = candidate_ids[idx]
            dense_rrf_scores[c_id] += weight / (RRF_K + rank)
            
    # Query E5
    print("\nQuerying E5 Indices...")
    for scope in scopes:
        print(f"  -> e5_{scope}")
        e5_vectors = np.vstack(df_e5[f"{scope}_vector"].to_list()).astype(np.float32)
        scores = np.dot(e5_vectors, jd_e5)
        
        # Fast Top-K extraction
        top_idx_unsorted = np.argpartition(scores, -DENSE_TOP_K_PER_INDEX)[-DENSE_TOP_K_PER_INDEX:]
        top_idx = top_idx_unsorted[np.argsort(scores[top_idx_unsorted])[::-1]]
        
        weight = DENSE_WEIGHTS[f"e5_{scope}"]
        for rank, idx in enumerate(top_idx, start=1):
            c_id = candidate_ids[idx]
            dense_rrf_scores[c_id] += weight / (RRF_K + rank)
            
    # Resolve Dense Top 10k
    print(f"\nSorting Dense RRF to extract Top {DENSE_RRF_POOL_SIZE}...")
    sorted_dense = sorted(dense_rrf_scores.items(), key=lambda x: x[1], reverse=True)[:DENSE_RRF_POOL_SIZE]
    dense_top_10k_ids = [k for k, v in sorted_dense]
    dense_top_10k_scores = {k: v for k, v in sorted_dense}
    
    # 3. Sparse Retrieval (BM25)
    print("\n--- 2. SPARSE RETRIEVAL (BM25) ---")
    retrieval_texts = df_texts["retrieval_text"].fill_null("").to_list()
    
    bm25 = VectorizedBM25()
    bm25.fit(retrieval_texts)
    bm25_top_idx, bm25_raw_scores = bm25.get_top_k(JD_TEXT, k=BM25_TOP_K)
    
    bm25_top_10k_ids = [candidate_ids[idx] for idx in bm25_top_idx]
    
    # 4. Global Fusion
    print("\n--- 3. GLOBAL RRF FUSION ---")
    global_scores = defaultdict(float)
    retrieval_sources = {}
    
    dense_ranks = {}
    bm25_ranks = {}
    
    # Add Dense
    for rank, c_id in enumerate(dense_top_10k_ids, start=1):
        global_scores[c_id] += 1.0 / (RRF_K + rank)
        retrieval_sources[c_id] = "dense_only"
        dense_ranks[c_id] = rank
        
    # Add BM25
    for rank, c_id in enumerate(bm25_top_10k_ids, start=1):
        global_scores[c_id] += 1.0 / (RRF_K + rank)
        if c_id in retrieval_sources:
            retrieval_sources[c_id] = "dense+bm25"
        else:
            retrieval_sources[c_id] = "bm25_only"
        bm25_ranks[c_id] = rank
            
    # Resolve Final Top 10k and Top 3k
    sorted_global = sorted(global_scores.items(), key=lambda x: x[1], reverse=True)[:DENSE_RRF_POOL_SIZE]
    
    final_output = []
    for rank, (c_id, score) in enumerate(sorted_global, start=1):
        final_output.append({
            "candidate_id": c_id,
            "final_rank": rank,
            "final_rrf_score": score,
            "dense_rrf_score": dense_top_10k_scores.get(c_id, 0.0),
            "dense_rank": dense_ranks.get(c_id, -1),
            "bm25_rank": bm25_ranks.get(c_id, -1),
            "retrieval_source": retrieval_sources[c_id]
        })
        
    df_final_10k = pl.DataFrame(final_output)
    df_final_3k = df_final_10k.head(FINAL_TOP_K)
    
    # 5. Save Artifacts
    print("\n--- 4. SAVING ARTIFACTS ---")
    df_final_10k.write_parquet(f"{OUTPUT_DIR}/retrieval_top_{DENSE_RRF_POOL_SIZE}.parquet")
    df_final_3k.write_parquet(f"{OUTPUT_DIR}/retrieval_top_{FINAL_TOP_K}.parquet")
    
    # 6. Diagnostics
    intersection_count = sum(1 for src in df_final_10k["retrieval_source"] if src == "dense+bm25")
    intersection_pct = (intersection_count / DENSE_RRF_POOL_SIZE) * 100
    
    dense_unique = sum(1 for src in df_final_10k["retrieval_source"] if "dense" in src)
    bm25_unique = sum(1 for src in df_final_10k["retrieval_source"] if "bm25" in src)
    
    diagnostics = {
        "generated_at": datetime.now().isoformat() if 'datetime' in globals() else time.strftime('%Y-%m-%dT%H:%M:%S'),
        "dense_unique_candidates": dense_unique,
        "bm25_unique_candidates": bm25_unique,
        "intersection_count": intersection_count,
        "intersection_pct": round(intersection_pct, 2),
        "rrf_pool_size": DENSE_RRF_POOL_SIZE,
        "final_top3000_size": FINAL_TOP_K,
        "final_top10000_size": len(df_final_10k)
    }
    
    with open(f"{OUTPUT_DIR}/retrieval_diagnostics.json", "w") as f:
        json.dump(diagnostics, f, indent=2)
        
    print(json.dumps(diagnostics, indent=2))
    
    print(f"\n✅ Phase 6 Complete! Executed in {time.time() - overall_start_time:.2f} seconds.")

if __name__ == "__main__":
    from datetime import datetime
    main()
