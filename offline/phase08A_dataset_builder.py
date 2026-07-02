import os
import polars as pl
import numpy as np

# ==============================================================================
# CONFIGURATION
# ==============================================================================
PHASE06_ARTIFACTS = "artifacts/phase06"
PHASE07_ARTIFACTS = "artifacts/phase07"
OUTPUT_DIR = "artifacts/phase08"

# We drop all strings, IDs, and reasoning artifacts before training
LEAKAGE_FEATURES = [
    "candidate_id", "rrf_rank", "priority_rank", "final_rank", 
    "teacher_rank", "teacher_reasoning_hash", "retrieval_explanation", 
    "recruiter_evaluation", "reasoning", "elimination_reason",
    "priority_breakdown",
    # Legacy Phase 7 string columns just in case
    "teacher_reasoning", "teacher_hash", "json",
    "graph_size_proxy", # Removed because it dominates tree growth without representing recruiter reasoning.
    "graph_edge_count", # Secondary leak uncovered after removing size proxy
    "graph_node_count", # Tertiary leak to preemptively remove
    "priority_score",   # Quaternary leak (heuristic label anchor for teacher)
    "salary_percentile", # Often acts as a shortcut proxy for seniority
    "years_exp"         # Another strong proxy that bypasses skills analysis
]

import json

def load_relevance_bins():
    try:
        with open("offline/teacher_grade_config.json", "r") as f:
            config = json.load(f)
            return {int(k): v for k, v in config.items()}
    except FileNotFoundError:
        return {10: 4, 50: 3, 200: 2, 500: 1}

RELEVANCE_BINS = load_relevance_bins()

def build_dataset():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    # 1. Load Data
    print("Loading retrieval pool and calibrated labels...")
    try:
        pool_df = pl.read_parquet(os.path.join(PHASE06_ARTIFACTS, "retrieval_pool.parquet"))
        labels_df = pl.read_parquet(os.path.join(PHASE07_ARTIFACTS, "calibrated_labels_full.parquet"))
    except Exception as e:
        print(f"Error loading files: {e}")
        print("Waiting for Phase 7 to complete and provide these files.")
        return
        
    # 2. Join features with labels
    # Inner join so we only train on candidates the teacher actually scored (the top 1000)
    labels_df_subset = labels_df.select([c for c in labels_df.columns if c not in pool_df.columns or c == "candidate_id"])
    df = pool_df.join(labels_df_subset, on="candidate_id", how="inner")
    print(f"Joined dataset size: {len(df)} candidates")
    
    # 3. Derive teacher_relevance
    # The labels_df is already sorted by calibrated_score descending in Phase 7
    df = df.sort("calibrated_score", descending=True)
    
    # Create relevance grades based on configuration dictionary
    relevance_col = []
    for rank in range(len(df)):
        r = rank + 1
        grade = 0
        for threshold in sorted(RELEVANCE_BINS.keys()):
            if r <= threshold:
                grade = RELEVANCE_BINS[threshold]
                break
        relevance_col.append(grade)
        
    # Rename calibrated_score to teacher_score
    df = df.rename({"calibrated_score": "teacher_score"})
    
    df = df.with_columns(
        pl.Series("teacher_rank", np.arange(1, len(df) + 1)),
        pl.Series("teacher_relevance", relevance_col),
        pl.Series("teacher_percentile", 100.0 * (len(df) - np.arange(1, len(df) + 1)) / len(df))
    )
    
    # 4. Feature Leakage Audit
    # We must explicitly keep `candidate_id`, `teacher_rank`, and `teacher_relevance` 
    # for the next phases, but we must flag them so LightGBM ignores them during training.
    # The actual dropping of strings happens here.
    # Dynamically find raw dense scores to remove (force use of aggregates)
    raw_dense = [c for c in labels_df.columns if c.startswith("bge_") or c.startswith("e5_")]
    leakage_cols = LEAKAGE_FEATURES + raw_dense
    
    columns_to_drop = [c for c in df.columns if c in leakage_cols and c not in ["candidate_id", "teacher_rank"]]
    
    # Also drop any String columns automatically
    string_cols = [col_name for col_name, dtype in zip(df.columns, df.dtypes) if dtype == pl.String]
    columns_to_drop.extend([c for c in string_cols if c != "candidate_id"])
    
    columns_to_drop = list(set(columns_to_drop))
    
    if columns_to_drop:
        print(f"Feature Leakage Audit: Dropping {len(columns_to_drop)} columns: {columns_to_drop}")
        df = df.drop(columns_to_drop)
        
    # 5. Near-Zero Variance Pruning
    numeric_cols = [c for c, d in zip(df.columns, df.dtypes) if d.is_numeric() and c not in ["candidate_id", "teacher_rank", "teacher_relevance", "teacher_score", "teacher_percentile"]]
    zero_var_cols = []
    for c in numeric_cols:
        std_val = df[c].std()
        if std_val is None or std_val < 1e-4:
            zero_var_cols.append(c)
    
    if zero_var_cols:
        df = df.drop(zero_var_cols)
        
    # 6. Highly Correlated Feature Pruning (Pearson > 0.995)
    remaining_numeric = [c for c in df.columns if c in numeric_cols and c not in zero_var_cols]
    correlation_df = df.select(remaining_numeric).to_pandas().corr().abs()
    
    upper = correlation_df.where(np.triu(np.ones(correlation_df.shape), k=1).astype(bool))
    highly_correlated = [column for column in upper.columns if any(upper[column] > 0.995)]
    
    if highly_correlated:
        df = df.drop(highly_correlated)
        
    # Save correlation matrix
    correlation_df.to_csv(os.path.join(OUTPUT_DIR, "feature_correlation.csv"))
    
    print("\n--- PRUNING REPORT ---")
    print(f"Original features   : {len(pool_df.columns)}")
    print(f"Duplicate removed   : {len(labels_df.columns) - len(labels_df_subset.columns)}")
    print(f"Leakage/String drops: {len(columns_to_drop)}")
    print(f"Zero variance       : {len(zero_var_cols)}")
    print(f"Correlation removed : {len(highly_correlated)}")
    
    final_features_count = len([c for c in df.columns if c not in ["candidate_id", "teacher_rank", "teacher_relevance", "teacher_score", "teacher_percentile"]])
    print(f"Final features      : {final_features_count}")
    print("----------------------\n")
        
    # Verify that every remaining feature is numeric
    assert all(dtype.is_numeric() for col, dtype in zip(df.columns, df.dtypes) if col != "candidate_id"), "Non-numeric columns detected in dataset after leakage audit!"
        
    # Save the prepared dataset (used for training)
    out_path = os.path.join(OUTPUT_DIR, "dataset.parquet")
    df.write_parquet(out_path)
    
    # Save the pure inference dataset (used by Phase 11 online)
    # Strip ALL teacher logic, keep only candidate_id + features
    inference_drop = ["teacher_score", "teacher_rank", "teacher_relevance", "teacher_percentile"]
    inference_cols = [c for c in df.columns if c not in inference_drop]
    inf_df = df.select(inference_cols)
    inf_path = os.path.join(OUTPUT_DIR, "inference_features.parquet")
    inf_df.write_parquet(inf_path)
    
    print(f"✅ Phase 8A Complete! Dataset saved to {out_path}")
    print(f"✅ Inference features saved to {inf_path}")

if __name__ == "__main__":
    build_dataset()
