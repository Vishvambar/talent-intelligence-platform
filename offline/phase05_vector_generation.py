import os
import json
import hashlib
import time
import numpy as np
import polars as pl
import torch
from datetime import datetime
from tqdm import tqdm
from sentence_transformers import SentenceTransformer

# --- CONFIGURATION FOR KAGGLE OFFLINE ---
BGE_PATH = "/kaggle/input/datasets/hycloud/bge-large-en-v1-5/bge-large-en-v1.5"
E5_PATH = "/kaggle/input/datasets/gmhost/e5-large-v2"
INPUT_PARQUET = "/kaggle/input/redrob-candidate-data/candidate_texts.parquet"
OUTPUT_DIR = "/kaggle/working/artifacts"
BATCH_SIZE = 2048

# Set to True to run the 1,000-candidate smoke test before committing to 100k
SMOKE_TEST = False
SMOKE_LIMIT = 5000

os.makedirs(OUTPUT_DIR, exist_ok=True)

JD_TEXT = """
Senior AI Engineer Founding Team
Required: embeddings, vector databases, retrieval systems, ranking evaluation,
NDCG, MAP, semantic search, RAG, product company, startup
Experience: 5-9 years applied ML, production retrieval systems,
founding team mindset, fast execution, ownership
"""

def compute_file_hash(filepath: str) -> str:
    hasher = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hasher.update(chunk)
    return hasher.hexdigest()

def get_peak_gpu_memory():
    if torch.cuda.is_available():
        # Convert bytes to GB
        return round(torch.cuda.max_memory_allocated() / (1024 ** 3), 2)
    return 0.0

def main():
    print(f"CUDA Available: {torch.cuda.is_available()}")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()
    
    print(f"Computing SHA-256 for {INPUT_PARQUET}...")
    try:
        text_hash = compute_file_hash(INPUT_PARQUET)
    except Exception as e:
        print(f"CRITICAL: Could not hash {INPUT_PARQUET}. Error: {e}")
        return
        
    print(f"Reading candidates from {INPUT_PARQUET}...")
    df = pl.read_parquet(INPUT_PARQUET)
    
    if SMOKE_TEST:
        print(f"\n🚀 RUNNING SMOKE TEST: Limiting to first {SMOKE_LIMIT} candidates")
        df = df.head(SMOKE_LIMIT)
        
    candidate_ids = df["candidate_id"].to_list()
    p_texts = df["profile_text"].to_list()
    c_texts = df["career_text"].to_list()
    s_texts = df["skills_text"].to_list()
    total = len(candidate_ids)
    
    scopes = [
        ("profile", p_texts), 
        ("career", c_texts), 
        ("skills", s_texts)
    ]
    
    overall_start_time = time.time()
    
    # --- MODEL 1: BGE-LARGE ---
    print("\nLoading BGE-Large onto GPU...")
    model_bge = SentenceTransformer(BGE_PATH, device=device)
    bge_max_seq_length = model_bge.max_seq_length if hasattr(model_bge, "max_seq_length") else 512
    
    
    # Pre-computation: Token Stats & Truncation
    print("Calculating BGE Token Stats & Truncation (Batch Mode)...")
    bge_stats = {}
    for scope_name, texts in scopes:
        # Batch tokenization is extremely fast and avoids 100k separate python calls
        # Note: truncation=False is REQUIRED to accurately count lengths > 512
        encoded = model_bge.tokenizer(texts, truncation=False, padding=False)
        lengths = [len(ids) for ids in encoded["input_ids"]]
        avg_len = sum(lengths) / total
        pct_truncated = sum(1 for l in lengths if l > 512) / total * 100
        bge_stats[f"{scope_name}_truncated_pct"] = round(pct_truncated, 2)
        bge_stats[f"{scope_name}_avg_tokens"] = round(avg_len, 2)
        print(f"  -> {scope_name}: Avg Tokens: {avg_len:.1f} | Truncated: {pct_truncated:.2f}%")
    
    print("\nGenerating BGE Vectors...")
    bge_embeddings = {}
    bge_start_time = time.time()
    dynamic_dim = 1024 # Will be updated dynamically
    for scope_name, texts in scopes:
        print(f"  -> BGE Embedding: {scope_name}")
        emb = model_bge.encode(texts, batch_size=BATCH_SIZE, normalize_embeddings=True, show_progress_bar=True)
        emb = emb.astype(np.float16)  # Crucial to prevent memory explosion
        dynamic_dim = emb.shape[1]
        print(f"     Shape: {emb.shape} | Dtype: {emb.dtype}")
        bge_embeddings[f"{scope_name}_vector"] = emb.tolist()
        
    print("  -> BGE Embedding: JD_TEXT")
    jd_bge = model_bge.encode([JD_TEXT], normalize_embeddings=True).astype(np.float16)
    bge_duration = time.time() - bge_start_time
        
    print("Saving BGE Parquet Matrix...")
    bge_df = pl.DataFrame({"candidate_id": candidate_ids, **bge_embeddings})
    bge_df.write_parquet(f"{OUTPUT_DIR}/candidate_embeddings_bge.parquet")
    
    del model_bge, bge_embeddings, bge_df
    torch.cuda.empty_cache()
    
    # --- MODEL 2: E5-LARGE ---
    print("\nLoading E5-Large onto GPU...")
    model_e5 = SentenceTransformer(E5_PATH, device=device)
    e5_max_seq_length = model_e5.max_seq_length if hasattr(model_e5, "max_seq_length") else 512
    
    
    # Note: E5 stats omitted to avoid duplicate calculation; BGE proxy is sufficient
    print("\nGenerating E5 Vectors (with 'passage: ' prefix)...")
    e5_embeddings = {}
    e5_start_time = time.time()
    for scope_name, texts in scopes:
        print(f"  -> E5 Embedding: {scope_name}")
        prefixed_texts = [f"passage: {t}" for t in texts]
        emb = model_e5.encode(prefixed_texts, batch_size=BATCH_SIZE, normalize_embeddings=True, show_progress_bar=True)
        emb = emb.astype(np.float16)  # Crucial to prevent memory explosion
        print(f"     Shape: {emb.shape} | Dtype: {emb.dtype}")
        e5_embeddings[f"{scope_name}_vector"] = emb.tolist()
        
    print("  -> E5 Embedding: JD_TEXT (with 'query: ' prefix)")
    jd_e5 = model_e5.encode([f"query: {JD_TEXT}"], normalize_embeddings=True).astype(np.float16)
    e5_duration = time.time() - e5_start_time
        
    print("Saving E5 Parquet Matrix...")
    e5_df = pl.DataFrame({"candidate_id": candidate_ids, **e5_embeddings})
    e5_df.write_parquet(f"{OUTPUT_DIR}/candidate_embeddings_e5.parquet")
    
    # Save JD Embeddings (Use npz to avoid object arrays)
    print("Saving JD Embeddings...")
    np.savez(f"{OUTPUT_DIR}/jd_embeddings.npz", JD_BGE=jd_bge, JD_E5=jd_e5)
    
    overall_duration = time.time() - overall_start_time
    
    # --- METRICS & REGISTRY ---
    total_vectors = total * 6 # 3 scopes * 2 models
    embedding_duration = bge_duration + e5_duration
    pure_throughput = round(total_vectors / embedding_duration, 2) if embedding_duration > 0 else 0
    e2e_throughput = round(total_vectors / overall_duration, 2) if overall_duration > 0 else 0
    peak_vram = get_peak_gpu_memory()
    
    print(f"\n--- PERFORMANCE METRICS ---")
    print(f"Total Vectors Generated: {total_vectors}")
    print(f"Pure Embedding Throughput: {pure_throughput} embeddings/sec")
    print(f"End-to-End Throughput: {e2e_throughput} embeddings/sec")
    print(f"Peak VRAM: {peak_vram} GB")
    
    # --- ARTIFACT SIZE PROFILING ---
    bge_size_mb = os.path.getsize(f"{OUTPUT_DIR}/candidate_embeddings_bge.parquet") / (1024 * 1024)
    e5_size_mb = os.path.getsize(f"{OUTPUT_DIR}/candidate_embeddings_e5.parquet") / (1024 * 1024)
    
    print(f"\n--- ARTIFACT SIZES ---")
    print(f"BGE Parquet Size: {bge_size_mb:.2f} MB")
    print(f"E5 Parquet Size:  {e5_size_mb:.2f} MB")
    print(f"Total Size:       {(bge_size_mb + e5_size_mb):.2f} MB")
    
    if SMOKE_TEST:
        multiplier = 100000 / SMOKE_LIMIT
        est_bge = bge_size_mb * multiplier / 1024
        est_e5 = e5_size_mb * multiplier / 1024
        print(f"\n--- 100K EXTRAPOLATION ---")
        print(f"Estimated BGE Parquet at 100k: {est_bge:.2f} GB")
        print(f"Estimated E5 Parquet at 100k:  {est_e5:.2f} GB")
        print(f"Total Estimated Storage:       {(est_bge + est_e5):.2f} GB")
    
    registry = {
        "generated_at": datetime.now().isoformat(),
        "input_parquet_hash": text_hash,
        "is_smoke_test": SMOKE_TEST,
        "candidate_count": total,
        "vector_count": total_vectors,
        "embedding_dimension": dynamic_dim,
        "pure_throughput_embeddings_per_second": pure_throughput,
        "e2e_throughput_embeddings_per_second": e2e_throughput,
        "peak_gpu_memory_gb": peak_vram,
        "models": {
            "bge": {
                "name": "BAAI/bge-large-en-v1.5", 
                "normalized": True, 
                "prefix": None,
                "max_seq_length": bge_max_seq_length,
                "token_stats": bge_stats
            },
            "e5": {
                "name": "intfloat/e5-large-v2", 
                "normalized": True, 
                "prefix": "passage: ",
                "max_seq_length": e5_max_seq_length
            }
        },
        "scopes": ["profile", "career", "skills"]
    }
    with open(f"{OUTPUT_DIR}/embedding_registry.json", "w") as f:
        json.dump(registry, f, indent=2)
        
    print(f"\n✅ Phase 5 {'SMOKE TEST ' if SMOKE_TEST else ''}Complete! Artifacts saved to {OUTPUT_DIR}")

if __name__ == "__main__":
    main()
