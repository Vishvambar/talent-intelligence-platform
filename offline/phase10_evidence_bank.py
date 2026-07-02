import os
import json
import hashlib
import numpy as np
import polars as pl
from tqdm import tqdm

# ==============================================================================
# CONFIGURATION
# ==============================================================================
PHASE03_ARTIFACTS = "data/artifacts/phase03"
PHASE04_ARTIFACTS = "data/artifacts/phase04"
OUTPUT_DIR = "artifacts/phase10"
CONFIG_PATH = "offline/phase10_config.json"

def load_config():
    try:
        with open(CONFIG_PATH, "r") as f:
            print(f"Loaded configuration from {CONFIG_PATH}")
            return json.load(f)
    except FileNotFoundError:
        print("Using fallback configuration (file not found)")
        return {
            "gap_threshold": 0.20,
            "jd_weights": {
                "retrieval_score": 0.30,
                "vector_db_score": 0.25,
                "evaluation_score": 0.25,
                "ml_score": 0.10,
                "embedding_score": 0.10
            }
        }

CONFIG = load_config()

# Human-readable mapping for ontology features
FEATURE_LABELS = {
    "retrieval_score": "Retrieval Systems (RAG)",
    "vector_db_score": "Vector Databases",
    "evaluation_score": "Evaluation Pipelines (NDCG/MAP)",
    "ml_score": "Machine Learning",
    "embedding_score": "Dense Embeddings",
    "llm_score": "Large Language Models"
}

def compute_hash(payload: dict) -> str:
    # Deterministic hash of the core evidence payload
    s = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def generate_evidence_components(row: dict) -> dict:
    cid = row.get("candidate_id")
    
    # 1. SUMMARY COMPONENTS (Dynamic Domain & Seniority)
    y_exp = float(row.get("years_exp", 0.0))
    
    # Dynamic Domain Inference
    scores = {
        "Retrieval/Search": float(row.get("retrieval_score", 0.0)),
        "ML/AI": float(row.get("ml_score", 0.0)),
        "Vector/Data Systems": float(row.get("vector_db_score", 0.0)),
        "Backend/AI Engineering": 0.1  # Base default
    }
    sorted_domains = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    if sorted_domains[0][1] - sorted_domains[1][1] < 0.05 and sorted_domains[1][1] > 0.2:
        primary_domain = f"{sorted_domains[0][0]} & {sorted_domains[1][0]}"
    else:
        primary_domain = sorted_domains[0][0]
    
    # Seniority Bands
    seniority = "Junior"
    if y_exp >= CONFIG.get("seniority_thresholds", {}).get("senior_max", 8.0):
        seniority = "Principal"
    elif y_exp >= CONFIG.get("seniority_thresholds", {}).get("mid_max", 5.0):
        seniority = "Senior"
    elif y_exp >= CONFIG.get("seniority_thresholds", {}).get("junior_max", 2.0):
        seniority = "Mid-Level"
        
    startup_thresh = CONFIG.get("company_weights", {}).get("startup_threshold", 0.5)
    consulting_thresh = CONFIG.get("company_weights", {}).get("consulting_threshold", 0.5)
    
    company_type = "Enterprise"
    if float(row.get("startup_score", 0.0)) > startup_thresh:
        company_type = "Startup"
    elif float(row.get("consulting_score", 0.0)) > consulting_thresh:
        company_type = "Consulting"
        
    summary = {
        "primary_domain": primary_domain,
        "experience_years": y_exp,
        "company_type": company_type,
        "seniority": seniority
    }
    
    # 2. STRENGTHS & GAPS
    strengths = []
    gaps = []
    
    jd_weights = CONFIG["jd_weights"]
    gap_threshold = CONFIG["gap_threshold"]
    
    # Add Phase 6 Coverage Metrics as High-Value Strengths
    tech_cov = float(row.get("technical_coverage", 0.0))
    if tech_cov >= 0.70:
        strengths.append({
            "label": f"Matched {int(tech_cov * 100)}% technical priorities",
            "score": tech_cov,
            "render_priority": tech_cov * 1.5,
            "feature_name": "technical_coverage"
        })
        
    biz_cov = float(row.get("business_coverage", 0.0))
    if biz_cov >= 0.70:
        strengths.append({
            "label": f"Matched {int(biz_cov * 100)}% business priorities",
            "score": biz_cov,
            "render_priority": biz_cov * 1.2,
            "feature_name": "business_coverage"
        })
        
    beh_cov = float(row.get("behavioral_coverage", 0.0))
    if beh_cov >= 0.70:
        strengths.append({
            "label": f"Matched {int(beh_cov * 100)}% behavioral priorities",
            "score": beh_cov,
            "render_priority": beh_cov * 1.2,
            "feature_name": "behavioral_coverage"
        })
        
    for feat, label in FEATURE_LABELS.items():
        score = float(row.get(feat, 0.0))
        weight = jd_weights.get(feat, 0.10)
        
        if score >= 0.70:
            # High strength
            render_priority = weight * score * 1.0  # High confidence if score is high
            strengths.append({
                "label": label,
                "score": score,
                "render_priority": render_priority,
                "feature_name": feat
            })
        elif score < gap_threshold:
            # Gap
            render_priority = weight * (1.0 - score)  # High priority if it's a critical missing feature
            gaps.append({
                "label": label,
                "score": score,
                "render_priority": render_priority,
                "feature_name": feat
            })
            
    # Sort by render priority descending
    strengths = sorted(strengths, key=lambda x: x["render_priority"], reverse=True)
    gaps = sorted(gaps, key=lambda x: x["render_priority"], reverse=True)
    
    # 3. RISKS & INTEGRITY
    risks = []
    r_thresh = CONFIG.get("risk_thresholds", {})
    
    # Phase 4 Integrity Score
    integrity_score = float(row.get("integrity_score", 1.0))
    if integrity_score < r_thresh.get("integrity_score_min", 0.60):
        risks.append({
            "label": "Low Evidence Consistency / Integrity",
            "score": integrity_score,
            "render_priority": (1.0 - integrity_score) * 1.5
        })
    
    # Timeline anomaly risk (from Phase 4 if available)
    anomaly_score = float(row.get("anomaly_severity", 0.0))
    if anomaly_score > r_thresh.get("anomaly_severity_max", 0.40):
        risks.append({
            "label": "Timeline Anomalies",
            "score": anomaly_score,
            "render_priority": anomaly_score * 0.9
        })
        
    # Github Missing
    if float(row.get("github_missing", 0.0)) == 1.0:
        risks.append({
            "label": "Missing GitHub/Portfolio Data",
            "score": 1.0,
            "render_priority": 0.5
        })
        
    # High Consulting Background
    consulting_score = float(row.get("consulting_score", 0.0))
    if consulting_score > r_thresh.get("consulting_score_max", 0.80):
        risks.append({
            "label": "Heavy Consulting Background",
            "score": consulting_score,
            "render_priority": consulting_score * 0.6
        })
        
    # Seniority Mismatch
    years_exp = float(row.get("years_exp", 0.0))
    if years_exp < r_thresh.get("years_exp_min", 3.0):
        risks.append({
            "label": "Seniority Mismatch",
            "score": 1.0,
            "render_priority": 0.8
        })
        
    risks = sorted(risks, key=lambda x: x["render_priority"], reverse=True)
    for r in risks:
        if r["render_priority"] >= 0.8:
            r["severity"] = "High"
        elif r["render_priority"] >= 0.4:
            r["severity"] = "Medium"
        else:
            r["severity"] = "Low"
    
    # 4. SUPPORTING EVIDENCE (Structured)
    evidence = []
    promos = float(row.get("promotion_count", 0.0))
    if promos >= 1:
        evidence.append({
            "type": "promotion",
            "label": "Leadership Growth",
            "value": f"{int(promos)} promotions",
            "grounding_confidence": min(1.0, 0.70 + (promos * 0.10)),
            "source": "career_history",
            "feature_name": "promotion_count"
        })
        
    edu_tier = float(row.get("education_tier_score", 0.0))
    if edu_tier >= 0.7:
        evidence.append({
            "type": "education",
            "label": "Strong Educational Foundation",
            "value": "Tier-1/2 Institution",
            "grounding_confidence": edu_tier,
            "source": "education",
            "feature_name": "education_tier_score"
        })
        
    if float(row.get("founding_team_score", 0.0)) > 0.5:
        evidence.append({
            "type": "experience",
            "label": "Startup Velocity",
            "value": "Founding/Early Team Experience",
            "grounding_confidence": float(row.get("founding_team_score", 0.0)),
            "source": "career_history",
            "feature_name": "founding_team_score"
        })
        
    # Compute overall grounding confidence
    ev_strength = float(row.get("evidence_strength_score", 0.0))
    if evidence:
        evidence_confidences = [e["grounding_confidence"] for e in evidence]
        overall_confidence = np.mean(evidence_confidences)
    else:
        # Fallback to Phase 4 evidence_strength_score or technical_coverage
        overall_confidence = ev_strength if ev_strength > 0 else float(row.get("technical_coverage", 0.50))
    
    # Base Payload
    payload = {
        "candidate_id": cid,
        "summary_components": summary,
        "strengths": strengths,
        "gaps": gaps,
        "risks": risks,
        "supporting_evidence": evidence,
        "grounding_confidence": round(float(overall_confidence), 3)
    }
    
    # 5. METADATA
    payload["metadata"] = {
        "reasoning_hash": compute_hash(payload),
        "template_version": CONFIG.get("template_version", "v1.2"),
        "ontology_version": CONFIG.get("ontology_version", "v2.0")
    }
    
    return payload

def build_evidence_bank():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    print("Loading candidate features...")
    # Load primary features
    try:
        df = pl.read_parquet(os.path.join(PHASE03_ARTIFACTS, "candidate_features.parquet"))
    except FileNotFoundError:
        print("candidate_features.parquet not found. Please ensure Phase 3 has run.")
        return
        
    # Attempt to load Career Features (Phase 3.5) and Integrity Features (Phase 4)
    # We use a left join to ensure we keep all 100k candidates
    try:
        career_df = pl.read_parquet(os.path.join(PHASE03_ARTIFACTS, "career_features.parquet"))
        df = df.join(career_df, on="candidate_id", how="left")
        print("Joined Career Features.")
    except FileNotFoundError:
        print("career_features.parquet not found, continuing without Phase 3.5 signals.")
        
    try:
        integrity_df = pl.read_parquet(os.path.join(PHASE04_ARTIFACTS, "integrity_features.parquet"))
        df = df.join(integrity_df, on="candidate_id", how="left")
        print("Joined Integrity Features.")
    except FileNotFoundError:
        print("integrity_features.parquet not found, continuing without Phase 4 signals.")
        
    # Fill missing values gracefully
    df = df.fill_null(0.0)
    
    print(f"Generating Evidence Bank for {len(df)} candidates...")
    
    evidence_records = []
    
    # We iter over rows as dicts for simple processing
    # In a truly massive dataset, we'd use pure Polars exprs, but for 100k
    # dict iteration in Python takes ~3-5 seconds which is well within Kaggle offline bounds.
    row_dicts = df.to_dicts()
    
    stats = {
        "total_processed": 0,
        "avg_evidence_count": 0.0,
        "avg_grounding_confidence": 0.0,
        "avg_strengths_per_candidate": 0.0,
        "avg_gaps_per_candidate": 0.0,
        "avg_risks_per_candidate": 0.0,
        "pct_no_evidence": 0.0,
        "pct_gt3_evidence": 0.0,
        "top_strengths": {},
        "top_gaps": {},
        "top_risks": {}
    }
    
    evidence_counts = []
    strength_counts = []
    gap_counts = []
    risk_counts = []
    confidences = []
    
    for row in tqdm(row_dicts, desc="Synthesizing Evidence"):
        evidence = generate_evidence_components(row)
        # Store structured columns natively
        evidence_records.append({
            "candidate_id": row["candidate_id"],
            "summary": json.dumps(evidence["summary_components"]),
            "strengths": json.dumps(evidence["strengths"]),
            "gaps": json.dumps(evidence["gaps"]),
            "risks": json.dumps(evidence["risks"]),
            "supporting_evidence": json.dumps(evidence["supporting_evidence"]),
            "metadata": json.dumps(evidence["metadata"]),
            "grounding_confidence": evidence["grounding_confidence"]
        })
        
        # Accumulate Stats
        stats["total_processed"] += 1
        num_evidence = len(evidence["supporting_evidence"])
        evidence_counts.append(num_evidence)
        strength_counts.append(len(evidence["strengths"]))
        gap_counts.append(len(evidence["gaps"]))
        risk_counts.append(len(evidence["risks"]))
        confidences.append(evidence["grounding_confidence"])
        
        if evidence["strengths"]:
            top_s = evidence["strengths"][0]["label"]
            stats["top_strengths"][top_s] = stats["top_strengths"].get(top_s, 0) + 1
            
        if evidence["gaps"]:
            top_g = evidence["gaps"][0]["label"]
            stats["top_gaps"][top_g] = stats["top_gaps"].get(top_g, 0) + 1
            
        if evidence["risks"]:
            top_r = evidence["risks"][0]["label"]
            stats["top_risks"][top_r] = stats["top_risks"].get(top_r, 0) + 1
            
    # Finalize Stats
    total = stats["total_processed"]
    stats["avg_evidence_count"] = float(np.mean(evidence_counts))
    stats["avg_grounding_confidence"] = float(np.mean(confidences))
    stats["avg_strengths_per_candidate"] = float(np.mean(strength_counts))
    stats["avg_gaps_per_candidate"] = float(np.mean(gap_counts))
    stats["avg_risks_per_candidate"] = float(np.mean(risk_counts))
    
    no_ev = sum(1 for c in evidence_counts if c == 0)
    gt3_ev = sum(1 for c in evidence_counts if c > 3)
    stats["pct_no_evidence"] = round((no_ev / total) * 100, 1) if total > 0 else 0.0
    stats["pct_gt3_evidence"] = round((gt3_ev / total) * 100, 1) if total > 0 else 0.0
    
    stats["template_version"] = "v1.1"
    stats["ontology_version"] = "v2.0"
    
    # Save Artifacts
    print("Saving Evidence Bank...")
    out_df = pl.DataFrame(evidence_records)
    out_path = os.path.join(OUTPUT_DIR, "evidence_bank.parquet")
    out_df.write_parquet(out_path)
    
    stats_path = os.path.join(OUTPUT_DIR, "phase10_statistics.json")
    with open(stats_path, "w") as f:
        json.dump(stats, f, indent=2)
        
    print(f"✅ Phase 10 Complete! Evidence Bank saved to {out_path}")
    print(f"📊 Statistics saved to {stats_path}")

if __name__ == "__main__":
    build_evidence_bank()
