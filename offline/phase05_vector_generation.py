import os
import json
import hashlib
import time
import numpy as np
import polars as pl
import torch
from datetime import datetime
from tqdm import tqdm
import sentence_transformers
from sentence_transformers import SentenceTransformer

# --- CONFIGURATION FOR KAGGLE OFFLINE ---
BGE_PATH = "/kaggle/input/datasets/hycloud/bge-large-en-v1-5/bge-large-en-v1.5"
E5_PATH = "/kaggle/input/datasets/gmhost/e5-large-v2"
INPUT_PARQUET = "/kaggle/input/redrob-candidate-data/candidate_texts.parquet"
OUTPUT_DIR = "/kaggle/working/phase05"

# Fallbacks for local testing
if not os.path.exists("/kaggle"):
    BGE_PATH = "BAAI/bge-large-en-v1.5"
    E5_PATH = "intfloat/e5-large-v2"
    INPUT_PARQUET = "data/artifacts/phase03/candidate_texts.parquet"
    OUTPUT_DIR = "data/artifacts/phase05"

SMOKE_TEST = True
SMOKE_LIMIT = 500

# Setup Directories
os.makedirs(OUTPUT_DIR, exist_ok=True)
for sub in ["bge", "e5", "metadata"]:
    os.makedirs(os.path.join(OUTPUT_DIR, sub), exist_ok=True)

# Prioritize scopes
EMBEDDING_PRIORITY = {
    "retrieval": 1,
    "projects": 2,
    "career": 3,
    "skills": 4,
    "profile": 5,
    "github": 6
}

def compute_string_hash(text: str) -> str:
    if not text: return ""
    return hashlib.sha256(text.encode('utf-8')).hexdigest()

def compute_file_hash(filepath: str) -> str:
    if not os.path.exists(filepath): return "missing"
    hasher = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hasher.update(chunk)
    return hasher.hexdigest()

def get_peak_gpu_memory():
    if torch.cuda.is_available():
        return round(torch.cuda.max_memory_allocated() / (1024 ** 3), 2)
    return 0.0

class RecruiterDocumentBuilder:
    @staticmethod
    def format_priority(key, data):
        if isinstance(data, dict):
            title = key.replace('_', ' ').title()
            text = f"- {title}"
            if "reason" in data:
                text += f": {data['reason']}"
            elif "evidence" in data and len(data["evidence"]) > 0:
                ev = data["evidence"][0].get("text", "")
                text += f": {ev}"
            return text
        return f"- {data}"

    @staticmethod
    def build(jd: dict) -> str:
        doc_parts = []
        
        if "hard_requirements" in jd:
            doc_parts.append("Hard Requirements:")
            for k, v in jd["hard_requirements"].items():
                doc_parts.append(RecruiterDocumentBuilder.format_priority(k, v))
                
        if "preferred_requirements" in jd:
            doc_parts.append("\nPreferred Requirements:")
            for k, v in jd["preferred_requirements"].items():
                doc_parts.append(RecruiterDocumentBuilder.format_priority(k, v))
                
        intent = jd.get("hiring_intent", {})
        for p_type in ["technical_priorities", "behavioral_priorities", "business_priorities", "implicit_priorities"]:
            if p_type in intent:
                doc_parts.append(f"\n{p_type.replace('_', ' ').title()}:")
                for k, v in intent[p_type].items():
                    doc_parts.append(RecruiterDocumentBuilder.format_priority(k, v))
                    
        mental_model = jd.get("recruiter_mental_model", {})
        if "decision_priority" in mental_model:
            doc_parts.append("\nDecision Priorities:")
            dp = mental_model["decision_priority"]
            if isinstance(dp, list):
                for item in dp:
                    doc_parts.append(f"- {str(item).replace('_', ' ').title()}")
                    
        if "hiring_summary" in jd:
            doc_parts.append("\nHiring Summary:")
            summary = jd["hiring_summary"]
            if isinstance(summary, dict):
                if "executive_summary" in summary:
                    doc_parts.append(summary["executive_summary"])
            else:
                doc_parts.append(str(summary))
                
        return "\n".join(doc_parts).strip()

def load_jd_document():
    path = "data/artifacts/phase01/jd_requirements.json"
    if not os.path.exists(path):
        path = "/kaggle/input/redrob-candidate-data/jd_requirements.json"
        
    try:
        with open(path, "r") as f:
            jd = json.load(f)
        return RecruiterDocumentBuilder.build(jd)
    except Exception:
        return "Required Skills:\n- embeddings\n- vector databases\n\nExperience:\n- 5-9 years applied ML"

def dynamic_batch_benchmark(model, sample_texts, device):
    """Benchmark batch sizes for max throughput. Stops if throughput drops twice."""
    if device == "cpu":
        return 128
        
    batch_size = 512
    best_batch = 512
    max_throughput = 0.0
    drops_in_a_row = 0
    
    print(f"\n--- Dynamic GPU Batch Benchmarking ({device}) ---")
    
    while True:
        try:
            if torch.cuda.is_available(): torch.cuda.reset_peak_memory_stats()
            print(f"Testing batch_size={batch_size}...")
            
            test_slice = sample_texts[:batch_size] if len(sample_texts) >= batch_size else sample_texts * (batch_size // max(1, len(sample_texts)) + 1)
            test_slice = test_slice[:batch_size]
            
            # Warmup
            model.encode(test_slice[:10], batch_size=10, show_progress_bar=False)
            
            start_t = time.time()
            model.encode(test_slice, batch_size=batch_size, show_progress_bar=False)
            duration = time.time() - start_t
            throughput = len(test_slice) / max(0.001, duration)
            
            peak = get_peak_gpu_memory()
            print(f"  ✓ Success at {batch_size}. Throughput: {throughput:.1f} eps. Peak VRAM: {peak} GB")
            
            if throughput > max_throughput:
                max_throughput = throughput
                best_batch = batch_size
                drops_in_a_row = 0
            else:
                drops_in_a_row += 1
                
            # If throughput drops twice OR we hit a safe upper bound (1024 is safe for 512-len tokens on 95GB)
            if drops_in_a_row >= 2 or batch_size >= 1024:
                print(f"  -> Stopping benchmark (throughput dropped or reached safe limit of 1024).")
                break
                
            batch_size *= 2
            
        except RuntimeError as e:
            if "out of memory" in str(e).lower():
                print(f"  x OOM caught at {batch_size}. Stopping benchmark.")
                if torch.cuda.is_available(): torch.cuda.empty_cache()
                break
            else:
                raise e
                
    print(f"Optimal batch size chosen: {best_batch} (Max throughput: {max_throughput:.1f} eps)")
    return best_batch

def main():
    print(f"CUDA Available: {torch.cuda.is_available()}")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    
    print(f"Reading candidates from {INPUT_PARQUET}...")
    df = pl.read_parquet(INPUT_PARQUET)
    
    if SMOKE_TEST:
        print(f"\n🚀 RUNNING SMOKE TEST: Limiting to first {SMOKE_LIMIT} candidates")
        df = df.head(SMOKE_LIMIT)
        
    candidate_ids = df["candidate_id"].to_list()
    pl.DataFrame({"candidate_id": candidate_ids}).write_parquet(f"{OUTPUT_DIR}/metadata/candidate_ids.parquet")
    
    scopes = {
        "profile": df["profile_text"].to_list(),
        "career": df["career_text"].to_list(),
        "projects": df.get_column("projects_text").to_list() if "projects_text" in df.columns else df["profile_text"].to_list(),
        "skills": df["skills_text"].to_list(),
        "github": df.get_column("github_text").to_list() if "github_text" in df.columns else df["profile_text"].to_list(),
        "retrieval": df.get_column("retrieval_text").to_list() if "retrieval_text" in df.columns else df["profile_text"].to_list(),
    }
    ordered_scopes = sorted(scopes.keys(), key=lambda x: EMBEDDING_PRIORITY.get(x, 99))
    total = len(candidate_ids)
    
    retrieval_shas = [compute_string_hash(t) for t in scopes["retrieval"]]
    jd_text = load_jd_document()
    
    registry = {
        "generated_at": datetime.now().isoformat(),
        "versions": {
            "torch": torch.__version__,
            "sentence_transformers": sentence_transformers.__version__,
            "cuda": torch.version.cuda if torch.cuda.is_available() else "none"
        },
        "input_parquet_hash": compute_file_hash(INPUT_PARQUET),
        "is_smoke_test": SMOKE_TEST,
        "candidate_count": total,
        "embedding_priority": EMBEDDING_PRIORITY,
        "models": {}
    }
    
    embedding_statistics = {}
    
    # Structure for unified metadata
    meta_dict = {}
    for cid, r_sha in zip(candidate_ids, retrieval_shas):
        for s in ordered_scopes:
            meta_dict[(cid, s)] = {
                "candidate_id": cid,
                "scope": s,
                "retrieval_sha256": r_sha,
                "bge_norm": None,
                "e5_norm": None,
                "token_count": None,
                "truncated": None,
                "embedding_dimension": None
            }
    
    models_config = [
        ("bge", BGE_PATH, "Represent this sentence for searching relevant passages: ", "BAAI/bge-large-en-v1.5"),
        ("e5", E5_PATH, "passage: ", "intfloat/e5-large-v2")
    ]
    
    # Store embeddings temporarily for smoke test top-10 retrieval
    retrieval_embeddings = {}
    
    for model_key,model_path, prefix, model_name in models_config:
        print(f"\nLoading {model_name} onto {device}...")
        try:
            model = SentenceTransformer(model_path, device=device)
        except Exception:
            model = SentenceTransformer(model_name, device=device)
            
        opt_batch = dynamic_batch_benchmark(model, scopes["retrieval"][:512], device)
        registry["models"][model_key] = {
            "model_name": model_name,
            "path": model_path,
            "optimal_batch_size": opt_batch,
            "scopes": {}
        }
        embedding_statistics[model_key] = {}
        
        dim = model.get_sentence_embedding_dimension() if hasattr(model, 'get_sentence_embedding_dimension') else 1024
        
        manifest = {
            "model": model_name,
            "dimension": dim,
            "candidate_count": total,
            "dtype": "float32",
            "normalized": True,
            "artifacts": {}
        }
        
        # Prepare JD Text for this specific model
        if model_key == "e5":
            jd_input = f"query: {jd_text}"
        elif model_key == "bge":
            jd_input = f"Represent this query for retrieval: {jd_text}"
        else:
            jd_input = jd_text
            
        jd_emb = model.encode([jd_input], normalize_embeddings=True).astype(np.float32)
        
        for scope_name in ordered_scopes:
            texts = scopes[scope_name]
            texts = [t if t is not None else "" for t in texts]
            
            # Prepend prefix and strip whitespace to prevent empty trailing newlines
            if prefix:
                input_texts = [f"{prefix}{t.strip()}" for t in texts]
            else:
                input_texts = texts
                
            print(f"  -> {model_key.upper()} Embedding: {scope_name}")
            start_t = time.time()
            
            # Token Stats on 1000 random subset
            subset_idx = np.random.choice(total, min(1000, total), replace=False)
            subset_texts = [input_texts[i] for i in subset_idx]
            encoded = model.tokenizer(subset_texts, truncation=False, padding=False)
            lengths = [len(ids) for ids in encoded["input_ids"]]
            avg_len = sum(lengths) / max(1, len(lengths))
            pct_truncated = sum(1 for l in lengths if l > model.max_seq_length) / max(1, len(lengths)) * 100
            
            # Encode
            emb = model.encode(input_texts, batch_size=opt_batch, normalize_embeddings=True, show_progress_bar=True)
            emb = emb.astype(np.float32)
            
            duration = time.time() - start_t
            throughput = total / max(0.001, duration)
            
            # Sanity checks
            if np.isnan(emb).any() or np.isinf(emb).any():
                raise ValueError(f"NaN/Inf detected in {model_key} {scope_name} embeddings")
                
            norms = np.linalg.norm(emb, axis=1)
            if not np.allclose(norms, 1.0, atol=0.001):
                raise ValueError(f"L2 Norm check failed! Embeddings are not properly normalized.")
            
            npy_path = os.path.join(OUTPUT_DIR, model_key, f"{scope_name}.npy")
            np.save(npy_path, emb)
            manifest["artifacts"][scope_name] = f"{scope_name}.npy"
            
            # Cosine Checks
            rand_idx = np.random.choice(total, min(100, total), replace=False)
            cos_scores_jd = np.dot(emb[rand_idx], jd_emb[0])
            
            idx1 = np.random.choice(total, min(100, total), replace=False)
            idx2 = np.random.choice(total, min(100, total), replace=False)
            for i in range(len(idx1)):
                if idx1[i] == idx2[i]:
                    idx2[i] = (idx2[i] + 1) % total
            cos_scores_cand = np.sum(emb[idx1] * emb[idx2], axis=1)
            
            # Metadata update
            for i, c_id in enumerate(candidate_ids):
                row = meta_dict[(c_id, scope_name)]
                row[f"{model_key}_norm"] = float(norms[i])
                row["embedding_dimension"] = dim
            
            if model_key == "bge":
                # Fast bulk tokenization for the actual rows
                full_encoded = model.tokenizer(input_texts, truncation=False, padding=False)
                full_lengths = [len(ids) for ids in full_encoded["input_ids"]]
                for i, c_id in enumerate(candidate_ids):
                    meta_dict[(c_id, scope_name)]["token_count"] = full_lengths[i]
                    meta_dict[(c_id, scope_name)]["truncated"] = full_lengths[i] > model.max_seq_length
            
            stats = {
                "dimension": dim,
                "average_tokens": round(avg_len, 2),
                "truncated_pct": round(pct_truncated, 2),
                "throughput_eps": round(throughput, 2),
                "artifact_size_mb": round(os.path.getsize(npy_path) / (1024*1024), 2),
                "mean_norm": round(float(np.mean(norms)), 4),
                "std_norm": round(float(np.std(norms)), 4),
                "cos_jd_mean": round(float(np.mean(cos_scores_jd)), 4),
                "cos_jd_std": round(float(np.std(cos_scores_jd)), 4),
                "cos_cand_mean": round(float(np.mean(cos_scores_cand)), 4)
            }
            
            registry["models"][model_key]["scopes"][scope_name] = stats
            embedding_statistics[model_key] = embedding_statistics.get(model_key, {})
            embedding_statistics[model_key][scope_name] = stats
            
            if scope_name == "retrieval":
                retrieval_embeddings[model_key] = emb
            
        np.save(os.path.join(OUTPUT_DIR, model_key, "jd.npy"), jd_emb)
        manifest["artifacts"]["jd"] = "jd.npy"
        
        with open(os.path.join(OUTPUT_DIR, model_key, "embedding_manifest.json"), "w") as f:
            json.dump(manifest, f, indent=2)
            
        # Retrieval Smoke Test (Top 10 candidates for this model)
        print(f"\n--- {model_key.upper()} Retrieval Smoke Test ---")
        if model_key in retrieval_embeddings:
            sims = np.dot(retrieval_embeddings[model_key], jd_emb[0])
            top_10_idx = np.argsort(sims)[::-1][:10]
            for rank, idx in enumerate(top_10_idx):
                print(f"Rank {rank+1}: {candidate_ids[idx]} (Score: {sims[idx]:.4f})")
                
        del model
        torch.cuda.empty_cache()

    retrieval_metadata_records = list(meta_dict.values())
    pl.DataFrame(retrieval_metadata_records).write_parquet(f"{OUTPUT_DIR}/metadata/retrieval_metadata.parquet")
    
    with open(f"{OUTPUT_DIR}/metadata/registry.json", "w") as f:
        json.dump(registry, f, indent=2)
        
    with open(f"{OUTPUT_DIR}/metadata/statistics.json", "w") as f:
        json.dump(embedding_statistics, f, indent=2)
        
    print(f"\n✅ Phase 5 {'SMOKE TEST ' if SMOKE_TEST else ''}Complete!")

if __name__ == "__main__":
    main()
