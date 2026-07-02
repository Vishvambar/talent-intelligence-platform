import os
import json
import pickle
import numpy as np
import polars as pl
import shap

OUTPUT_DIR = "artifacts/phase08"

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

def run_phase8d():
    print("--- PHASE 8D: Explainability & Stress Test ---")
    
    # Load Model and Data
    with open(os.path.join(OUTPUT_DIR, "lgbm_model.pkl"), "rb") as f:
        model = pickle.load(f)
        
    with open(os.path.join(OUTPUT_DIR, "train_columns.json"), "r") as f:
        feature_cols = json.load(f)["columns"]
        
    df = pl.read_parquet(os.path.join(OUTPUT_DIR, "dataset.parquet"))
    X = df.select(feature_cols).to_numpy().astype(np.float32)
    
    # ---------------------------------------------------------
    # 1. SHAP ANALYSIS
    # ---------------------------------------------------------
    print("Computing SHAP values...")
    try:
        explainer = shap.TreeExplainer(model)
        shap_values = explainer.shap_values(X)
        
        # If objective is lambdarank, shap_values might be a list (or array).
        if isinstance(shap_values, list):
            shap_values = shap_values[0]
            
        mean_abs_shap = np.abs(shap_values).mean(axis=0)
        total_importance = np.sum(mean_abs_shap)
        if total_importance == 0:
            shap_pct = np.zeros_like(mean_abs_shap)
        else:
            shap_pct = (mean_abs_shap / total_importance) * 100
        
        # Save raw SHAP values matrix with candidate_ids
        shap_df = pl.DataFrame(shap_values, schema=feature_cols).with_columns(
            pl.Series("candidate_id", df["candidate_id"])
        )
        shap_df.write_parquet(os.path.join(OUTPUT_DIR, "shap_values.parquet"))
    except Exception as e:
        print(f"SHAP Explainer failed ({e}). Falling back to native feature importance.")
        mean_abs_shap = model.feature_importances_
        total_importance = np.sum(mean_abs_shap)
        if total_importance == 0:
            shap_pct = np.zeros_like(mean_abs_shap)
        else:
            shap_pct = (mean_abs_shap / total_importance) * 100
    
    # Save Native Feature Importances
    native_importance = pl.DataFrame({
        "feature": feature_cols,
        "importance": model.feature_importances_
    }).sort("importance", descending=True)
    native_importance.write_csv(os.path.join(OUTPUT_DIR, "feature_importance.csv"))
    
    importance_df = pl.DataFrame({
        "feature": feature_cols,
        "importance": mean_abs_shap,
        "importance_pct": shap_pct
    }).sort("importance", descending=True)
    
    importance_df.write_csv(os.path.join(OUTPUT_DIR, "shap_summary.csv"))
    
    # SHAP Safety Gate
    print("\nVerifying SHAP Safety Gate...")
    try:
        with open("offline/expected_features.json", "r") as f:
            gate_requirements = json.load(f)
    except FileNotFoundError:
        gate_requirements = {
            "technical_coverage": 0.01,
            "retrieval_strength": 0.005
        }
        
    gate_failed = False
    for feat, min_pct in gate_requirements.items():
        row = importance_df.filter(pl.col("feature") == feat)
        if len(row) == 0:
            print(f"❌ FAILED: '{feat}' is missing from feature list!")
            gate_failed = True
            continue
            
        actual_pct = row["importance_pct"][0]
        if actual_pct < min_pct:
            print(f"❌ FAILED: '{feat}' contributes {actual_pct:.2f}% (Required: > {min_pct}%)")
            gate_failed = True
        else:
            print(f"✅ PASS: '{feat}' contributes {actual_pct:.2f}%")
            
    if gate_failed:
        print("\n⚠️ WARNING: The LightGBMRanker is NOT prioritizing the core engineered features.")
        print("This usually means there is a feature leakage or the teacher labels are misaligned.")
        
    print("\nVerifying Top 20 Core Feature Presence...")
    top_20_features = importance_df.head(20)["feature"].to_list()
    core_features = ["technical_coverage", "retrieval_strength"]
    
    missing_core = []
    for feat in core_features:
        if feat not in top_20_features:
            missing_core.append(feat)
            
    if missing_core:
        print(f"❌ FAILED: Top 20 is missing core features: {missing_core}")
        gate_failed = True
    else:
        print("✅ PASS: Top 20 contains all required core semantic signals.")
        
    # ---------------------------------------------------------
    # 2. STRESS TEST (NDCG, MAP, Recall)
    # ---------------------------------------------------------
    print("\nComputing Offline Leaderboard Proxy Metrics...")
    preds_df = pl.read_parquet(os.path.join(OUTPUT_DIR, "student_predictions.parquet"))
    
    teacher_relevance = preds_df["teacher_relevance"].to_numpy()
    
    # Sort for ideal
    ideal_relevances = np.sort(teacher_relevance)[::-1]
    
    # Student Sort
    student_order = preds_df.sort("student_rank")["teacher_relevance"].to_numpy()
    
    # Teacher Sort (assuming teacher_rank represents their original reasoning order)
    teacher_order = preds_df.sort("teacher_rank")["teacher_relevance"].to_numpy()
    
    # Metrics - Student
    s_ndcg_10 = ndcg_at_k(student_order, ideal_relevances, 10)
    s_ndcg_50 = ndcg_at_k(student_order, ideal_relevances, 50)
    s_ndcg_100 = ndcg_at_k(student_order, ideal_relevances, 100)
    s_map = average_precision(student_order, threshold=2.0)
    
    # Metrics - Teacher
    t_ndcg_10 = ndcg_at_k(teacher_order, ideal_relevances, 10)
    t_ndcg_50 = ndcg_at_k(teacher_order, ideal_relevances, 50)
    t_ndcg_100 = ndcg_at_k(teacher_order, ideal_relevances, 100)
    t_map = average_precision(teacher_order, threshold=2.0)
    
    print(f"Teacher NDCG@10:  {t_ndcg_10:.4f}")
    print(f"Student NDCG@10:  {s_ndcg_10:.4f}  (Loss: {t_ndcg_10 - s_ndcg_10:.4f})")
    print(f"Student NDCG@50:  {s_ndcg_50:.4f}")
    print(f"Student NDCG@100: {s_ndcg_100:.4f}")
    print(f"Student MAP:      {s_map:.4f}")
    
    # ---------------------------------------------------------
    # 3. EVALUATION REPORT
    # ---------------------------------------------------------
    report = "# Phase 8 Evaluation Report\n\n"
    
    report += "## SHAP Safety Gate\n"
    report += "Status: " + ("❌ FAILED" if gate_failed else "✅ PASSED") + "\n\n"
    report += "| Feature | Contribution | Required |\n|---|---|---|\n"
    for feat, min_pct in gate_requirements.items():
        row = importance_df.filter(pl.col("feature") == feat)
        actual_pct = row["importance_pct"][0] if len(row) > 0 else 0.0
        report += f"| {feat} | {actual_pct:.2f}% | > {min_pct}% |\n"
        
    report += "\n## Top 15 Most Important Features\n"
    for row in importance_df.head(15).iter_rows(named=True):
        report += f"- **{row['feature']}**: {row['importance_pct']:.2f}%\n"
        
    report += "\n## Offline Leaderboard Simulation\n"
    report += "| Metric | Teacher Score | Student Score | Loss |\n|---|---|---|---|\n"
    report += f"| NDCG@10 | {t_ndcg_10:.4f} | {s_ndcg_10:.4f} | {t_ndcg_10 - s_ndcg_10:.4f} |\n"
    report += f"| NDCG@50 | {t_ndcg_50:.4f} | {s_ndcg_50:.4f} | {t_ndcg_50 - s_ndcg_50:.4f} |\n"
    report += f"| NDCG@100 | {t_ndcg_100:.4f} | {s_ndcg_100:.4f} | {t_ndcg_100 - s_ndcg_100:.4f} |\n"
    report += f"| MAP | {t_map:.4f} | {s_map:.4f} | {t_map - s_map:.4f} |\n"
    
    with open(os.path.join(OUTPUT_DIR, "evaluation_report.md"), "w") as f:
        f.write(report)
        
    print("✅ Phase 8D Complete! evaluation_report.md saved.")

if __name__ == "__main__":
    run_phase8d()
