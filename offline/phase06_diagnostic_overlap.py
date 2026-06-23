import os
import json
import time
import numpy as np
import polars as pl
from scipy.stats import spearmanr

INPUT_DIR = "/kaggle/working/artifacts"

def run_diagnostic():
    print("Loading Parquet Artifacts...")
    
    start_time = time.time()
    df_bge = pl.read_parquet(f"{INPUT_DIR}/candidate_embeddings_bge.parquet")
    df_e5 = pl.read_parquet(f"{INPUT_DIR}/candidate_embeddings_e5.parquet")
    jd_embs = np.load(f"{INPUT_DIR}/jd_embeddings.npz")
    print(f"Loading completed in {time.time() - start_time:.2f} seconds.")
    
    jd_bge = jd_embs["JD_BGE"]
    jd_e5 = jd_embs["JD_E5"]
    
    scopes = ["profile", "career", "skills"]
    k_values = [100, 500, 1000]
    results = {}
    
    for scope in scopes:
        print(f"\n--- Processing Scope: {scope.upper()} ---")
        
        # 1. Extract Vectors
        bge_vectors = np.vstack(df_bge[f"{scope}_vector"].to_list()).astype(np.float32)
        e5_vectors = np.vstack(df_e5[f"{scope}_vector"].to_list()).astype(np.float32)
        
        # 2. Compute Cosine Similarity (Dot Product since vectors are normalized)
        jd_bge_vec = jd_bge.squeeze().astype(np.float32)
        jd_e5_vec = jd_e5.squeeze().astype(np.float32)
        
        scores_bge = np.dot(bge_vectors, jd_bge_vec)
        scores_e5 = np.dot(e5_vectors, jd_e5_vec)
        
        # 3. Calculate Spearman Correlation over the entire 100k distribution
        corr, _ = spearmanr(scores_bge, scores_e5)
        print(f"  Spearman correlation: {corr:.4f}")
        print(f"  BGE Scores -> Mean: {scores_bge.mean():.4f} | Std: {scores_bge.std():.4f}")
        print(f"  E5 Scores  -> Mean: {scores_e5.mean():.4f} | Std: {scores_e5.std():.4f}")
        
        print(f"  BGE Range  -> Min: {scores_bge.min():.4f} | Max: {scores_bge.max():.4f}")
        print(f"  E5 Range   -> Min: {scores_e5.min():.4f} | Max: {scores_e5.max():.4f}")
        
        top10_bge = scores_bge[np.argsort(scores_bge)[-10:]]
        top10_e5 = scores_e5[np.argsort(scores_e5)[-10:]]
        
        print(f"  BGE Top-10 Spread: {(top10_bge[-1] - top10_bge[0]):.4f} ({top10_bge[0]:.4f} to {top10_bge[-1]:.4f})")
        print(f"  E5 Top-10 Spread:  {(top10_e5[-1] - top10_e5[0]):.4f} ({top10_e5[0]:.4f} to {top10_e5[-1]:.4f})")
        
        results[scope] = {"correlation": corr, "overlaps": {}}
        
        # 4. Retrieve Top-K at multiple levels
        for k in k_values:
            # Fast O(n) extraction of top k elements, then sorting just those k
            indices_bge_unsorted = np.argpartition(scores_bge, -k)[-k:]
            indices_bge = indices_bge_unsorted[np.argsort(scores_bge[indices_bge_unsorted])[::-1]]
            
            indices_e5_unsorted = np.argpartition(scores_e5, -k)[-k:]
            indices_e5 = indices_e5_unsorted[np.argsort(scores_e5[indices_e5_unsorted])[::-1]]
            
            # 5. Map back to Candidate IDs
            candidates_bge = set(df_bge["candidate_id"][indices_bge].to_list())
            candidates_e5 = set(df_e5["candidate_id"][indices_e5].to_list())
            
            # 6. Calculate Overlap
            intersection = candidates_bge.intersection(candidates_e5)
            overlap_pct = (len(intersection) / k) * 100
            
            print(f"  Top {k:<4} Overlap: {len(intersection):<4} candidates ({overlap_pct:.1f}%)")
            results[scope]["overlaps"][k] = overlap_pct
        
    print("\n--- DIAGNOSTIC SUMMARY ---")
    for scope, metrics in results.items():
        print(f"\n{scope.upper()}:")
        print(f"  Correlation : {metrics['correlation']:.4f}")
        for k, pct in metrics['overlaps'].items():
            print(f"  Top {k:<4}   : {pct:.1f}% overlap")
        
    print("\n--- INTERPRETATION GUIDE ---")
    print("Overlap > 85% & Corr > 0.95 : Models are basically redundant.")
    print("Overlap ~ 50% & Corr ~ 0.65 : Real retrieval diversity. Keep both models.")
    print("Overlap < 30% & Corr < 0.30 : Huge diversity. Dual-model architecture paying off massively.")

if __name__ == "__main__":
    run_diagnostic()
