import json
import gzip
import polars as pl
from tqdm import tqdm
from datetime import datetime

SENIOR_TITLES = [
    "principal", "staff", "senior staff", "distinguished",
    "vp of engineering", "cto", "director of engineering", "vp", "director"
]

def parse_date(date_str: str) -> datetime:
    """Safely parse YYYY-MM dates."""
    if not date_str or date_str.lower() == "present":
        return datetime.now()
    try:
        return datetime.strptime(date_str[:7], "%Y-%m")
    except ValueError:
        return None

def compute_integrity_evidence(cand: dict) -> dict:
    profile = cand.get("profile", {})
    career = cand.get("career_history", [])
    skills = cand.get("skills", [])
    signals = cand.get("redrob_signals", {})
    
    years_exp = float(profile.get("years_of_experience", 0))
    career_months = years_exp * 12
    
    anomaly_count = 0
    severity_sum = 0.0
    max_severity = 0.0
    
    # 1. Profile Completeness
    completeness_factors = [
        bool(cand.get("headline")),
        bool(cand.get("summary")),
        len(skills) > 0,
        len(career) > 0,
        len(cand.get("education", [])) > 0
    ]
    profile_completeness_score = sum(completeness_factors) / len(completeness_factors)
    
    # 2. Timeline Contradictions & Overlaps
    overlap_months = 0
    total_role_durations = 0
    earliest_start = None
    latest_end = None
    
    valid_roles = []
    for role in career:
        start_str = role.get("start_date", "")
        end_str = role.get("end_date", "")
        duration = role.get("duration_months", 0)
        
        if duration < 0:
            anomaly_count += 1
            severity = 1.0
            severity_sum += severity
            max_severity = max(max_severity, severity)
            
        start_dt = parse_date(start_str)
        end_dt = parse_date(end_str)
        
        if start_dt and end_dt:
            # Date vs Duration mismatch
            computed_months = (end_dt.year - start_dt.year) * 12 + (end_dt.month - start_dt.month)
            if abs(computed_months - duration) > 6:
                anomaly_count += 1
                severity = 0.4
                severity_sum += severity
                max_severity = max(max_severity, severity)
                
            if earliest_start is None or start_dt < earliest_start:
                earliest_start = start_dt
            if latest_end is None or end_dt > latest_end:
                latest_end = end_dt
                
            valid_roles.append((start_dt, end_dt))
            
        total_role_durations += max(0, duration)
    
    # Calculate overlaps (naive pair-wise)
    for i in range(len(valid_roles)):
        for j in range(i + 1, len(valid_roles)):
            s1, e1 = valid_roles[i]
            s2, e2 = valid_roles[j]
            overlap_start = max(s1, s2)
            overlap_end = min(e1, e2)
            if overlap_start < overlap_end:
                overlap = (overlap_end.year - overlap_start.year) * 12 + (overlap_end.month - overlap_start.month)
                overlap_months += overlap
                
    if overlap_months > 0:
        anomaly_count += 1
        severity = min(1.0, overlap_months / 12.0) # max severity if > 12 months overlap
        severity_sum += severity
        max_severity = max(max_severity, severity)

    # Timeline Inconsistency
    timeline_inconsistency_score = 0.0
    if earliest_start and latest_end and earliest_start < latest_end:
        actual_calendar_months = (latest_end.year - earliest_start.year) * 12 + (latest_end.month - earliest_start.month)
        if actual_calendar_months > 0:
            timeline_inconsistency_score = total_role_durations / actual_calendar_months
            
    if timeline_inconsistency_score > 1.5:
        anomaly_count += 1
        severity = min(1.0, (timeline_inconsistency_score - 1.0) / 3.0)
        severity_sum += severity
        max_severity = max(max_severity, severity)
            
    # 3. Skill Duration Contradictions
    total_skill_months = 0
    expert_count = 0
    endorsement_anomaly_count = 0
    skill_duration_contradiction_count = 0
    max_skill_duration_excess_months = 0
    
    for skill in skills:
        dur = skill.get("duration_months", 0)
        prof = skill.get("proficiency", "").lower()
        endorsements = skill.get("endorsements", 0)
        
        total_skill_months += dur
        
        if dur > career_months + 12:
            anomaly_count += 1
            ratio = dur / max(1, career_months)
            severity = max(0.0, min(1.0, ratio / 3.0))
            severity_sum += severity
            max_severity = max(max_severity, severity)
            
            skill_duration_contradiction_count += 1
            excess = dur - career_months
            max_skill_duration_excess_months = max(max_skill_duration_excess_months, excess)
            
        if prof == "expert":
            expert_count += 1
            
        if prof in ["beginner", "novice"] and endorsements > 500:
            anomaly_count += 1
            severity = 0.5
            severity_sum += severity
            max_severity = max(max_severity, severity)
            endorsement_anomaly_count += 1

    # Skill Density
    skill_density_score = 0.0
    if career_months > 0:
        skill_density_score = total_skill_months / career_months
        
    # Expert Inflation
    threshold = years_exp * 2
    if expert_count > threshold:
        anomaly_count += 1
        severity = min(1.0, (expert_count - threshold) / (threshold + 1))
        severity_sum += severity
        max_severity = max(max_severity, severity)
        
    # 4. Seniority Velocity
    seniority_velocity_score = 0.0
    for role in career:
        title = role.get("title", "").lower()
        if any(t in title for t in SENIOR_TITLES) and years_exp < 3:
            anomaly_count += 1
            severity = 0.7
            severity_sum += severity
            max_severity = max(max_severity, severity)
            # Rough proxy for velocity: 1.0 means reached VP in 0 years, 0.0 means normal.
            seniority_velocity_score = max(0.0, 1.0 - (years_exp / 3.0))
            
    # 5. Salary (Just extract for now, compute outlier later)
    salary_range = signals.get("expected_salary_range_inr_lpa", {})
    salary_max = salary_range.get("max", 0.0)
    
    if salary_max == 0:
         anomaly_count += 1
         severity = 0.1
         severity_sum += severity
         max_severity = max(max_severity, severity)
         
    return {
        "candidate_id": cand["candidate_id"],
        "anomaly_count": anomaly_count,
        "max_severity": max_severity,
        "severity_sum": severity_sum,
        "profile_completeness_score": profile_completeness_score,
        "overlap_months": overlap_months,
        "timeline_inconsistency_score": timeline_inconsistency_score,
        "skill_density_score": skill_density_score,
        "seniority_velocity_score": seniority_velocity_score,
        "skill_duration_contradiction_count": skill_duration_contradiction_count,
        "max_skill_duration_excess_months": max_skill_duration_excess_months,
        "raw_salary_max": salary_max
    }

def build_integrity_layer():
    print("Reading raw candidates...")
    records = []
    
    # Handle both compressed and uncompressed for robustness
    path = "data/raw/candidates.jsonl"
    open_func = gzip.open if path.endswith(".gz") else open
    try:
        with open_func(path, "rt", encoding="utf-8") as f:
            for line in tqdm(f, total=100000, desc="Extracting Evidence"):
                cand = json.loads(line)
                records.append(compute_integrity_evidence(cand))
    except FileNotFoundError:
        path = "data/raw/candidates.jsonl.gz"
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for line in tqdm(f, desc="Extracting Evidence"):
                cand = json.loads(line)
                records.append(compute_integrity_evidence(cand))
                
    df_new = pl.DataFrame(records)
    
    # Read Phase 3 features
    print("Joining with Phase 3 structural features...")
    df_p3 = pl.read_parquet("data/artifacts/candidate_features.parquet")
    
    # We need to keep: job_hop_count, career_gap_months, title_inflation_score, duplicate_company_count
    join_cols = ["candidate_id", "job_hop_count", "career_gap_months", "title_inflation_score", "duplicate_company_count"]
    # Only select columns that actually exist in Phase 3
    existing_cols = [c for c in join_cols if c in df_p3.columns]
    if "candidate_id" not in existing_cols:
        existing_cols.append("candidate_id")
        
    df_joined = df_new.join(df_p3.select(existing_cols), on="candidate_id", how="left")
    
    # Compute Salary Outlier Score (Z-Score of non-zero salaries)
    print("Computing dynamic salary outliers...")
    salary_mean = df_joined.filter(pl.col("raw_salary_max") > 0).select(pl.col("raw_salary_max").mean()).item()
    salary_std = df_joined.filter(pl.col("raw_salary_max") > 0).select(pl.col("raw_salary_max").std()).item()
    
    if salary_std > 0:
        df_joined = df_joined.with_columns(
            pl.when(pl.col("raw_salary_max") > 0)
            .then((pl.col("raw_salary_max") - salary_mean) / salary_std)
            .otherwise(0.0)
            .alias("salary_outlier_score")
        )
    else:
        df_joined = df_joined.with_columns(pl.lit(0.0).alias("salary_outlier_score"))
        
    # Drop raw salary
    df_joined = df_joined.drop("raw_salary_max")
    
    # Fill nulls for Phase 3 columns just in case
    for col in existing_cols:
        if col != "candidate_id":
            df_joined = df_joined.with_columns(pl.col(col).fill_null(0.0))
            
    print("Writing candidate_integrity.parquet...")
    df_joined.write_parquet("data/artifacts/candidate_integrity.parquet")
    
    # Generate Audit Report
    print("Generating phase04_integrity_audit.json...")
    audit = {}
    
    for col in ["overlap_months", "skill_density_score", "timeline_inconsistency_score", "salary_outlier_score"]:
        audit[f"mean_{col}"] = df_joined.select(pl.col(col).mean()).item()
        audit[f"max_{col}"] = df_joined.select(pl.col(col).max()).item()
        
    if "job_hop_count" in df_joined.columns:
        audit["mean_job_hops"] = df_joined.select(pl.col("job_hop_count").mean()).item()
        audit["mean_gap_months"] = df_joined.select(pl.col("career_gap_months").mean()).item()
        
    # Top 20 Riskiest Candidates
    top_20 = df_joined.sort("severity_sum", descending=True).head(20)
    top_20_list = []
    for row in top_20.to_dicts():
        # Clean up output to make it readable
        record = {
            "candidate_id": row["candidate_id"],
            "severity_sum": round(row["severity_sum"], 2),
            "anomaly_count": row["anomaly_count"],
            "max_severity": round(row["max_severity"], 2),
            "overlap_months": row["overlap_months"],
            "skill_density_score": round(row["skill_density_score"], 2),
            "timeline_inconsistency_score": round(row["timeline_inconsistency_score"], 2),
            "salary_outlier_score": round(row.get("salary_outlier_score", 0.0), 2)
        }
        if "title_inflation_score" in row:
            record["title_inflation_score"] = round(row["title_inflation_score"], 2)
        top_20_list.append(record)
        
    audit["top_20_riskiest_candidates"] = top_20_list
    
    with open("data/artifacts/phase04_integrity_audit.json", "w", encoding="utf-8") as f:
        json.dump(audit, f, indent=2)
        
    print(f"Phase 4 complete. {len(df_joined)} candidates processed.")

if __name__ == "__main__":
    build_integrity_layer()
