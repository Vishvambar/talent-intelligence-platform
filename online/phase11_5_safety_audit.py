import os
import polars as pl
import pandas as pd

def audit_submission():
    print("Executing Phase 11.5 Submission Safety Audit...")
    
    csv_path = "online/submission.csv"
    if not os.path.exists(csv_path):
        raise FileNotFoundError("submission.csv not found!")
        
    df = pl.read_csv(csv_path)
    
    # 0. Dtype Validation
    if df["candidate_id"].dtype != pl.Utf8:
        raise ValueError(f"❌ FAILED: candidate_id must be string (Utf8), got {df['candidate_id'].dtype}")
    if df["rank"].dtype not in [pl.Int32, pl.Int64]:
        raise ValueError(f"❌ FAILED: rank must be integer, got {df['rank'].dtype}")
    if df["score"].dtype not in [pl.Float32, pl.Float64]:
        raise ValueError(f"❌ FAILED: score must be float, got {df['score'].dtype}")
        
    # 1. Row Count
    if len(df) != 100:
        raise ValueError(f"❌ FAILED: Expected exactly 100 rows, got {len(df)}.")
        
    # 2. Unique IDs
    unique_ids = df["candidate_id"].n_unique()
    if unique_ids != 100:
        raise ValueError(f"❌ FAILED: Found duplicate candidate_ids. Unique count: {unique_ids}")
        
    # 3. Unique Ranks
    unique_ranks = df["rank"].n_unique()
    if unique_ranks != 100:
        raise ValueError(f"❌ FAILED: Found duplicate ranks. Unique count: {unique_ranks}")
        
    # 4. Strictly Monotonic Scores
    scores = df["score"].to_list()
    for i in range(1, len(scores)):
        if scores[i] >= scores[i-1]:
            raise ValueError(f"❌ FAILED: Scores are not strictly decreasing! rank {i} score {scores[i-1]} vs rank {i+1} score {scores[i]}")
            
    # 5. Null Checks
    null_counts = df.null_count()
    if sum(null_counts.row(0)) > 0:
        raise ValueError("❌ FAILED: Null values detected in submission.")
        
    # 6. Reasoning Quality
    reasonings = df["reasoning"].to_list()
    
    # Empty reasoning check
    for i, r in enumerate(reasonings):
        if not r or r.strip() == "":
            raise ValueError(f"❌ FAILED: Empty reasoning found at rank {i+1}.")
            
    # Duplicate reasoning check (Template Collapse)
    unique_reasonings = len(set(reasonings))
    dup_percent = ((100 - unique_reasonings) / 100.0) * 100
    if dup_percent > 20: # Over 20% identical reasoning is a red flag
        print(f"⚠️ WARNING: High duplicate reasoning percentage: {dup_percent}%")
    else:
        print(f"✅ Reasoning Diversity: {unique_reasonings}/100 unique explanations.")
        
    # Max length check
    max_len = max(len(r) for r in reasonings)
    print(f"✅ Max reasoning length: {max_len} characters.")
    
    # Encoding & Whitespace check
    for r in reasonings:
        try:
            r.encode('utf-8')
        except UnicodeError:
            raise ValueError("❌ FAILED: Non UTF-8 characters detected in reasoning.")
        
        if r != r.strip():
            raise ValueError("❌ FAILED: Trailing or leading whitespace detected in reasoning.")
            
    print("✅ All Phase 11.5 Safety Checks PASSED. The CSV is ready for Redrob.")

if __name__ == "__main__":
    audit_submission()
