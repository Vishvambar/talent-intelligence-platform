import json
import gzip
import math
import polars as pl
from tqdm import tqdm
from datetime import datetime
import os
import numpy as np

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

def normalize_title(title: str) -> str:
    t = str(title).lower()
    if any(x in t for x in ["vp", "vice president"]): return "VP"
    if "director" in t: return "Director"
    if "principal" in t or "distinguished" in t: return "Principal"
    if "staff" in t: return "Staff"
    if "lead" in t or "manager" in t: return "Lead"
    if "senior" in t or "sr" in t or "iii" in t: return "Senior"
    if "junior" in t or "jr" in t or " i" in t: return "Junior"
    return "Mid"

def get_yoe_bucket(yoe: float) -> str:
    if yoe <= 2: return "0-2"
    if yoe <= 5: return "3-5"
    if yoe <= 8: return "6-8"
    if yoe <= 12: return "9-12"
    if yoe <= 18: return "13-18"
    return "18+"

def compute_integrity_evidence(cand: dict) -> dict:
    profile = cand.get("profile", {})
    career = cand.get("career_history", [])
    skills = cand.get("skills", [])
    signals = cand.get("redrob_signals", {})
    
    years_exp = float(profile.get("years_of_experience", 0))
    expected_career_months = years_exp * 12
    
    anomaly_count = 0
    severity_sum = 0.0
    
    # 1. Profile Completeness
    completeness_factors = [
        bool(cand.get("headline")),
        bool(cand.get("summary")),
        len(skills) > 0,
        len(career) > 0,
        len(cand.get("education", [])) > 0,
        len(cand.get("certifications", [])) > 0,
        signals.get("github_activity_score", -1) >= 0
    ]
    profile_completeness_score = sum(completeness_factors) / len(completeness_factors)
    
    # 2. Timeline Contradictions & Overlaps
    continuous_overlap_months = 0
    maximum_overlap_months = 0
    claimed_months = 0
    
    valid_roles = []
    career_chronological = []
    
    for role in career:
        start_str = role.get("start_date", "")
        end_str = role.get("end_date", "")
        duration = role.get("duration_months", 0)
        title = role.get("title", "")
        
        if duration < 0:
            anomaly_count += 1
            severity_sum += 1.0
            
        start_dt = parse_date(start_str)
        end_dt = parse_date(end_str)
        
        if start_dt and end_dt:
            valid_roles.append((start_dt, end_dt))
            career_chronological.append({
                "start": start_dt,
                "title": normalize_title(title)
            })
            
        claimed_months += max(0, duration)
    
    # Calculate overlaps (naive pair-wise)
    for i in range(len(valid_roles)):
        for j in range(i + 1, len(valid_roles)):
            s1, e1 = valid_roles[i]
            s2, e2 = valid_roles[j]
            overlap_start = max(s1, s2)
            overlap_end = min(e1, e2)
            if overlap_start < overlap_end:
                overlap = (overlap_end.year - overlap_start.year) * 12 + (overlap_end.month - overlap_start.month)
                continuous_overlap_months += overlap
                maximum_overlap_months = max(maximum_overlap_months, overlap)
                
    if continuous_overlap_months > 0:
        anomaly_count += 1
        severity_sum += min(1.0, continuous_overlap_months / 12.0)

    # Timeline Inconsistency
    timeline_inconsistency_score = 0.0
    if expected_career_months > 0 and claimed_months > 0:
        timeline_inconsistency_score = max(claimed_months, expected_career_months) / max(1.0, min(claimed_months, expected_career_months))
    elif expected_career_months > 0 or claimed_months > 0:
        timeline_inconsistency_score = max(claimed_months, expected_career_months) / 12.0
            
    if timeline_inconsistency_score > 1.5:
        anomaly_count += 1
        severity_sum += min(1.0, (timeline_inconsistency_score - 1.0) / 3.0)
            
    # 3. Skill Duration Contradictions
    total_skill_months = 0
    expert_count = 0
    
    for skill in skills:
        dur = skill.get("duration_months", 0)
        prof = skill.get("proficiency", "").lower()
        total_skill_months += dur
        
        if dur > expected_career_months + 12:
            anomaly_count += 1
            severity_sum += max(0.0, min(1.0, dur / max(1, expected_career_months) / 3.0))
            
        if prof == "expert":
            expert_count += 1

    # Skill Density
    skill_density_score = 0.0
    if expected_career_months > 0:
        # User requested: log(1+x)
        skill_density_score = math.log1p(total_skill_months / expected_career_months)
        
    # Expert Inflation
    threshold = years_exp * 2
    if expert_count > threshold:
        anomaly_count += 1
        severity_sum += min(1.0, (expert_count - threshold) / (threshold + 1))
        
    # 4. Title Progression Velocity
    LEVELS = {
        "Junior": 1, "Mid": 2, "Senior": 3, "Lead": 4,
        "Staff": 5, "Principal": 6, "Director": 7, "VP": 8
    }
    career_chronological.sort(key=lambda x: x["start"])
    fast_promotion_penalty = 0.0
    
    if len(career_chronological) >= 2:
        first_role = career_chronological[0]
        last_role = career_chronological[-1]
        
        level_diff = LEVELS.get(last_role["title"], 2) - LEVELS.get(first_role["title"], 2)
        if level_diff > 0:
            time_diff = (last_role["start"] - first_role["start"]).days / 365.25
            if time_diff > 0:
                velocity = level_diff / time_diff
                if velocity > 1.0: # more than 1 level per year
                    fast_promotion_penalty = min(1.0, (velocity - 1.0))
                    anomaly_count += 1
                    severity_sum += fast_promotion_penalty
            
    # 5. Salary grouping raw data
    salary_range = signals.get("expected_salary_range_inr_lpa", {})
    salary_max = salary_range.get("max", 0.0)
    
    norm_title = normalize_title(profile.get("current_title", ""))
    norm_loc = str(profile.get("location", "")).split(",")[0].strip().lower()
    
    return {
        "candidate_id": cand["candidate_id"],
        "anomaly_count": anomaly_count,
        "weighted_anomaly_score": severity_sum,
        "profile_completeness_score": profile_completeness_score,
        "continuous_overlap_months": continuous_overlap_months,
        "maximum_overlap_months": maximum_overlap_months,
        "timeline_inconsistency_score": timeline_inconsistency_score,
        "skill_density_score": skill_density_score,
        "expected_career_months": expected_career_months,
        "claimed_months": claimed_months,
        "raw_salary_max": salary_max,
        "norm_title": norm_title,
        "norm_loc": norm_loc,
        "yoe_bucket": get_yoe_bucket(years_exp)
    }

def build_integrity_layer():
    print("Reading raw candidates...")
    records = []
    
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
    df_p3 = pl.read_parquet("data/artifacts/phase03/candidate_features.parquet")
    
    # We need to keep Phase 3 signals and Evidence Coverage (explicit_ratio)
    join_cols = ["candidate_id", "job_hop_count", "career_gap_months", "title_inflation_score", "duplicate_company_count", "explicit_ratio", "technology_node_count"]
    existing_cols = [c for c in join_cols if c in df_p3.columns]
    if "candidate_id" not in existing_cols:
        existing_cols.append("candidate_id")
        
    df_joined = df_new.join(df_p3.select(existing_cols), on="candidate_id", how="left")
    
    # Rename explicit_ratio to evidence_coverage
    if "explicit_ratio" in df_joined.columns:
        df_joined = df_joined.rename({"explicit_ratio": "evidence_coverage"})
    
    # --- GRAPH CONSISTENCY CHECK ---
    print("Computing Graph Consistency...")
    
    try:
        with open("config/title_depth_config.json", "r") as f:
            title_depth_config = json.load(f)
    except Exception:
        title_depth_config = {"Junior": 1, "Mid": 2, "Senior": 3, "Lead": 3, "Staff": 4, "Principal": 5, "Director": 2, "VP": 1}
    
    df_joined = df_joined.with_columns(
        pl.col("norm_title").replace(title_depth_config, default=1).cast(pl.Int32).alias("expected_tech_depth")
    )
    
    df_joined = df_joined.with_columns(
        pl.when(pl.col("technology_node_count") < pl.col("expected_tech_depth"))
        .then(pl.col("weighted_anomaly_score") + (pl.col("expected_tech_depth") - pl.col("technology_node_count")) * 0.2)
        .otherwise(pl.col("weighted_anomaly_score"))
        .alias("weighted_anomaly_score")
    )
    
    # Convert severity_sum to integrity_score
    df_joined = df_joined.with_columns(
        ((-pl.col("weighted_anomaly_score")).exp()).alias("integrity_score")
    )
    
    # --- EVIDENCE STRENGTH SCORE ---
    df_joined = df_joined.with_columns(
        ((pl.col("evidence_coverage") + pl.col("profile_completeness_score") + (pl.col("technology_node_count") / 5.0).clip(0, 1.0)) / 3.0).alias("evidence_strength_score")
    )

    # --- HIERARCHICAL SALARY GROUPS ---
    print("Computing Hierarchical Salary Groups...")
    # Level 1: Title + Location + YOE
    # Level 2: Title + YOE
    # Level 3: YOE
    # Level 4: Global
    
    sal_df = df_joined.filter(pl.col("raw_salary_max") > 0)
    
    def compute_stats(group_cols, prefix):
        return sal_df.group_by(group_cols).agg([
            pl.col("raw_salary_max").median().alias(f"{prefix}_median"),
            (pl.col("raw_salary_max").quantile(0.75) - pl.col("raw_salary_max").quantile(0.25)).alias(f"{prefix}_iqr"),
            pl.len().alias(f"{prefix}_count")
        ])
        
    lvl1 = compute_stats(["norm_title", "norm_loc", "yoe_bucket"], "l1")
    lvl2 = compute_stats(["norm_title", "yoe_bucket"], "l2")
    lvl3 = compute_stats(["yoe_bucket"], "l3")
    
    global_median = sal_df.select(pl.col("raw_salary_max").median()).item()
    global_iqr = sal_df.select(pl.col("raw_salary_max").quantile(0.75) - pl.col("raw_salary_max").quantile(0.25)).item()
    
    df_joined = df_joined.join(lvl1, on=["norm_title", "norm_loc", "yoe_bucket"], how="left")
    df_joined = df_joined.join(lvl2, on=["norm_title", "yoe_bucket"], how="left")
    df_joined = df_joined.join(lvl3, on=["yoe_bucket"], how="left")
    
    df_joined = df_joined.with_columns([
        pl.when(pl.col("l1_count") >= 30).then(pl.col("l1_median"))
          .when(pl.col("l2_count") >= 30).then(pl.col("l2_median"))
          .when(pl.col("l3_count") >= 30).then(pl.col("l3_median"))
          .otherwise(pl.lit(global_median)).alias("expected_salary"),
          
        pl.when(pl.col("l1_count") >= 30).then(pl.col("l1_iqr"))
          .when(pl.col("l2_count") >= 30).then(pl.col("l2_iqr"))
          .when(pl.col("l3_count") >= 30).then(pl.col("l3_iqr"))
          .otherwise(pl.lit(global_iqr)).alias("expected_iqr")
    ])
    
    df_joined = df_joined.with_columns(
        (pl.col("raw_salary_max") - pl.col("expected_salary")).alias("salary_deviation")
    )
    
    # Simple percentile approximation using CDF of normal distribution, or just rank based on deviation
    # Actually, simpler: we can use Polars `rank` over the salary groups, but we don't need exact percentile for the audit.
    # We will just compute the normal CDF using deviation / IQR as a proxy for Z-score.
    # For a robust estimate, deviation / (IQR / 1.349) is approx Z-score.
    
    df_joined = df_joined.with_columns(
        pl.when(pl.col("expected_iqr") > 0)
          .then(pl.col("salary_deviation") / pl.col("expected_iqr"))
          .otherwise(0.0).alias("salary_outlier_score")
    )
    
    valid_salaries = df_joined.filter(pl.col("raw_salary_max") > 0)
    valid_count = valid_salaries.height
    
    if valid_count > 0:
        ranks = valid_salaries.select([
            pl.col("candidate_id"),
            (pl.col("salary_deviation").rank(method="average") / valid_count * 100.0).alias("salary_percentile")
        ])
        df_joined = df_joined.join(ranks, on="candidate_id", how="left")
        df_joined = df_joined.with_columns(pl.col("salary_percentile").fill_null(50.0))
    else:
        df_joined = df_joined.with_columns(pl.lit(50.0).alias("salary_percentile"))
    
    # Clean up temp columns
    drop_cols = ["l1_median", "l1_iqr", "l1_count", "l2_median", "l2_iqr", "l2_count", "l3_median", "l3_iqr", "l3_count", "expected_iqr", "norm_title", "norm_loc", "yoe_bucket"]
    df_joined = df_joined.drop(drop_cols)
    
    # Fill nulls
    df_joined = df_joined.fill_null(0.0)
    
    os.makedirs("data/artifacts/phase04", exist_ok=True)
            
    print("Writing candidate_trust_features.parquet...")
    df_joined.write_parquet("data/artifacts/phase04/candidate_trust_features.parquet")
    df_joined.write_parquet("data/artifacts/phase04/candidate_integrity.parquet")
    
    # Save thresholds
    thresholds = {
        "global_salary_median": global_median,
        "global_salary_iqr": global_iqr,
        "timeline_inconsistency_threshold": 1.5,
        "fast_promotion_years_threshold": 2.0
    }
    with open("data/artifacts/phase04/integrity_thresholds.json", "w") as f:
        json.dump(thresholds, f, indent=2)
    
    # Generate Audit Report
    print("Generating phase04_integrity_audit.json...")
    audit = {}
    
    # 95th / 99th percentiles
    metrics = ["continuous_overlap_months", "skill_density_score", "timeline_inconsistency_score", "salary_outlier_score", "integrity_score"]
    for col in metrics:
        audit[f"mean_{col}"] = df_joined.select(pl.col(col).mean()).item()
        audit[f"p95_{col}"] = df_joined.select(pl.col(col).quantile(0.95)).item()
        audit[f"p99_{col}"] = df_joined.select(pl.col(col).quantile(0.99)).item()
        
    audit["missing_salary_percentage"] = df_joined.filter(pl.col("raw_salary_max") == 0).height / max(1, df_joined.height) * 100
        
    # Top 20 Riskiest Candidates (Lowest Integrity Score)
    top_20 = df_joined.sort("integrity_score", descending=False).head(20)
    top_20_list = []
    for row in top_20.to_dicts():
        record = {
            "candidate_id": row["candidate_id"],
            "integrity_score": round(row["integrity_score"], 3),
            "anomaly_count": row["anomaly_count"],
            "continuous_overlap_months": row["continuous_overlap_months"],
            "skill_density_score": round(row["skill_density_score"], 2),
            "timeline_inconsistency_score": round(row["timeline_inconsistency_score"], 2),
            "salary_outlier_score": round(row.get("salary_outlier_score", 0.0), 2)
        }
        top_20_list.append(record)
        
    audit["top_20_riskiest_candidates"] = top_20_list
    
    with open("data/artifacts/phase04/phase04_integrity_audit.json", "w", encoding="utf-8") as f:
        json.dump(audit, f, indent=2)
        
    feature_stats = {}
    for col in df_joined.columns:
        if col != "candidate_id" and df_joined[col].dtype in [pl.Float64, pl.Float32, pl.Int64, pl.Int32]:
            feature_stats[col] = {
                "mean": df_joined.select(pl.col(col).mean()).item(),
                "std": df_joined.select(pl.col(col).std()).item(),
                "min": df_joined.select(pl.col(col).min()).item(),
                "max": df_joined.select(pl.col(col).max()).item()
            }
            
    with open("data/artifacts/phase04/feature_statistics.json", "w", encoding="utf-8") as f:
        json.dump(feature_stats, f, indent=2)
        
    print(f"Phase 4 complete. {len(df_joined)} candidates processed.")

if __name__ == "__main__":
    build_integrity_layer()
