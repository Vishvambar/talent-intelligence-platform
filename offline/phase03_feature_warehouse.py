import os
import json
import gzip
import re
from datetime import datetime
from tqdm import tqdm
import polars as pl
import pandas as pd

# Safely import the Phase 2 graph generator
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from offline.phase02_ontology_engine import compute_candidate_graph_features

# Directories
RAW_DATA_PATH = "data/raw/candidates.jsonl"
ARTIFACTS_DIR = "data/artifacts"
PHASE03_DIR = os.path.join(ARTIFACTS_DIR, "phase03")
os.makedirs(PHASE03_DIR, exist_ok=True)
CHECKPOINTS_DIR = os.path.join(PHASE03_DIR, "checkpoints")
os.makedirs(CHECKPOINTS_DIR, exist_ok=True)

FEATURES_PARQUET = os.path.join(PHASE03_DIR, "candidate_features.parquet")
TEXTS_PARQUET = os.path.join(PHASE03_DIR, "candidate_texts.parquet")
GRAPH_PARQUET = os.path.join(PHASE03_DIR, "candidate_graph.parquet")
REGISTRY_JSON = os.path.join(PHASE03_DIR, "feature_registry.json")
STATS_JSON = os.path.join(PHASE03_DIR, "feature_stats.json")

# Define Company Signals
CONSULTING_SIGNALS = [
    "consulting", "outsourcing", "services", "infosys", "wipro",
    "tcs", "cognizant", "accenture", "capgemini", "ibm services",
    "agency", "staffing", "it services"
]
PRODUCT_SIGNALS = [
    "saas", "product", "platform", "software", "app",
    "marketplace", "fintech", "edtech", "healthtech"
]

def count_jsonl_rows(path: str) -> int:
    print(f"Counting raw JSONL rows in {path}...")
    count = 0
    open_func = gzip.open if path.endswith('.gz') else open
    with open_func(path, 'rt', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                count += 1
    print(f"Total raw rows: {count}")
    return count

def stream_candidates(path: str, batch_size: int = 5000):
    batch = []
    open_func = gzip.open if path.endswith('.gz') else open
    with open_func(path, 'rt', encoding='utf-8') as f:
        for line in f:
            line_str = line.strip()
            if line_str:
                batch.append((line_str, json.loads(line_str)))
                if len(batch) == batch_size:
                    yield batch
                    batch = []
    if batch:
        yield batch

def extract_candidate_features(raw_line: str, cand: dict) -> tuple:
    profile = cand.get("profile", {})
    career = cand.get("career_history", [])
    skills = cand.get("skills", [])
    signals = cand.get("redrob_signals", {})
    education = cand.get("education", [])

    candidate_id = str(cand.get("candidate_id", "unknown"))

    # --- Text Aggregates (For Text Parquet) ---
    headline = str(profile.get("headline", ""))
    summary = str(profile.get("summary", ""))
    profile_text = f"{headline} {summary}"
    skills_text = " ".join([s.get("name", "") if isinstance(s, dict) else str(s) for s in skills])
    
    # Career text
    career_parts = []
    for r in career:
        career_parts.append(f"{r.get('title', '')} at {r.get('company', '')}: {r.get('description', '')}")
    career_text = " ".join(career_parts)
    
    # Education text
    education_text = " ".join([f"{str(e.get('degree', ''))} {str(e.get('field', ''))} {str(e.get('institution', ''))}" for e in education])
    
    # Projects text
    projects_text = " ".join([f"{str(p.get('name', ''))} {str(p.get('description', ''))}" for p in cand.get("projects", [])])
    
    # Github text
    github_text = " ".join([str(repo.get("description", "")) for repo in signals.get("github_repos", []) if isinstance(repo, dict)])
    
    retrieval_text = f"{profile_text} {skills_text} {career_text} {education_text} {projects_text} {github_text}"
    bm25_text = retrieval_text
    
    text_row = {
        "candidate_id": candidate_id,
        "profile_text": profile_text,
        "skills_text": skills_text,
        "career_text": career_text,
        "education_text": education_text,
        "projects_text": projects_text,
        "github_text": github_text,
        "retrieval_text": retrieval_text,
        "bm25_text": bm25_text,
        "raw_candidate_json": raw_line
    }

    # --- Numeric Features (For Feature Parquet) ---
    
    # Experience
    prof_years = float(profile.get("years_of_experience", 0))
    career_years = sum(r.get("duration_months", 0) for r in career) / 12.0
    years_exp = max(prof_years, career_years)
    
    tenures = [r.get("duration_months", 0) / 12.0 for r in career if r.get("duration_months")]
    avg_tenure = sum(tenures) / len(tenures) if tenures else 0.0

    # Integrity
    career_role_count = float(len(career))
    job_hop_count = sum(1 for t in tenures if t < 1.0)
    
    seen_companies = set()
    dup_comp = 0
    for r in career:
        comp = str(r.get("company", "")).lower()
        if comp:
            if comp in seen_companies:
                dup_comp += 1
            seen_companies.add(comp)
    duplicate_company_count = float(dup_comp)
    
    # Parse dates and sort chronologically
    def parse_date(d_str):
        if not d_str: return None
        try: return datetime.strptime(d_str, "%Y-%m-%d")
        except ValueError:
            try: return datetime.strptime(d_str, "%Y-%m")
            except ValueError: return None
            
    sorted_career = sorted(career, key=lambda x: parse_date(str(x.get("start_date", ""))) or datetime.min)
    
    # Career Gap Months
    career_gap_months = 0.0
    max_end_date = None
    today = datetime.now()
    
    for r in sorted_career:
        s_date = parse_date(str(r.get("start_date", "")))
        e_date = parse_date(str(r.get("end_date", "")))
        
        if r.get("is_current") or r.get("end_date") is None:
            e_date = today
            
        if s_date and max_end_date:
            if s_date > max_end_date:
                gap = (s_date.year - max_end_date.year) * 12 + (s_date.month - max_end_date.month)
                if gap > 0:
                    career_gap_months += gap
                    
        if e_date:
            if max_end_date is None or e_date > max_end_date:
                max_end_date = e_date

    # Title parsing
    leadership_kw = ["lead", "manager", "director", "head", "principal", "staff", "vp", "founder"]
    leadership_count = float(sum(1 for r in career if any(kw in str(r.get("title", "")).lower() for kw in leadership_kw)))
    
    # Title Inflation Score
    title_inflation_score = (leadership_count / max(1.0, career_role_count)) * (1.0 / max(1.0, years_exp))

    # Promotion Count
    TITLE_LEVELS = {
        "intern": 0, "analyst": 1, "associate": 1, "engineer": 2, "developer": 2,
        "senior": 3, "lead": 4, "staff": 5, "principal": 6, 
        "manager": 6, "director": 7, "vp": 8, "head": 8, "founder": 9
    }
    def get_title_level(title_str):
        title_lower = str(title_str).lower()
        best_level = -1
        for kw, level in TITLE_LEVELS.items():
            if kw in title_lower:
                best_level = max(best_level, level)
        return best_level

    promotion_count = 0.0
    company_roles = {}
    for r in sorted_career:
        comp = str(r.get("company", "")).lower().strip()
        if not comp: continue
        level = get_title_level(r.get("title", ""))
        
        if comp not in company_roles:
            company_roles[comp] = [level]
        else:
            prev_levels = company_roles[comp]
            # Must be strictly greater than max previous level at the same company
            if level > max(prev_levels) and level != -1:
                promotion_count += 1.0
            company_roles[comp].append(level)

    # Technical (Ontology)
    ontology_scores, graph_edges = compute_candidate_graph_features(retrieval_text, candidate_id)
    
    # Career (Company Types)
    product_score = 0.0
    for role in career:
        industry = str(role.get("industry", "")).lower()
        company = str(role.get("company", "")).lower()
        text = industry + " " + company
        is_consulting = any(kw in text for kw in CONSULTING_SIGNALS)
        is_product = any(kw in text for kw in PRODUCT_SIGNALS)
        if is_product and not is_consulting:
            product_score += 1.0
        elif not is_consulting:
            product_score += 0.5
    product_company_score = min(1.0, product_score / max(1, len(career)))
    consulting_score = 1.0 - product_company_score
    
    startup_score = 1.0 if "startup" in career_text.lower() or "founder" in career_text.lower() else 0.0

    # Education (Clamped to max 0.3)
    tier_map = {"tier_1": 0.3, "tier_2": 0.2, "tier_3": 0.1, "tier_4": 0.05}
    edu_tiers = [tier_map.get(str(e.get("tier", "tier_4")).lower(), 0.0) for e in education]
    education_tier_score = max(edu_tiers) if edu_tiers else 0.0

    # Behavioral
    github_raw = signals.get("github_activity_score", -1)
    if github_raw == -1:
        github_score_imputed = 40.0
        github_missing = 1.0
    else:
        github_score_imputed = float(github_raw)
        github_missing = 0.0

    assessment_scores = signals.get("skill_assessment_scores", {})
    if isinstance(assessment_scores, dict) and assessment_scores:
        assessment_score = float(sum(assessment_scores.values()) / len(assessment_scores))
    else:
        assessment_score = 0.0

    feature_row = {
        "candidate_id": candidate_id,
        "career_role_count": float(career_role_count),
        "years_exp": float(years_exp),
        "avg_tenure": float(avg_tenure),
        "promotion_count": float(promotion_count),
        "leadership_count": float(leadership_count),
        "job_hop_count": float(job_hop_count),
        "duplicate_company_count": float(duplicate_company_count),
        "career_gap_months": float(career_gap_months),
        "title_inflation_score": float(title_inflation_score),
        "product_company_score": float(product_company_score),
        "consulting_score": float(consulting_score),
        "startup_score": float(startup_score),
        "education_tier_score": float(education_tier_score),
        "github_score_imputed": float(github_score_imputed),
        "github_missing": float(github_missing),
        "assessment_score": float(assessment_score),
        "ontology_version": "v3.0",
        "graph_version": "v4.0",
        "phase2_version": "v2.1",
        "feature_schema_version": "v5.0",
        "feature_generator_version": "v1.0"
    }
    
    # Merge ontology scores
    for k, v in ontology_scores.items():
        if k.endswith("_score") or k.endswith("_matches") or k.endswith("_count") or k.endswith("_ratio") or k.endswith("_weight"):
            feature_row[k] = float(v)

    return feature_row, text_row, graph_edges

def build_feature_warehouse():
    print("Starting Phase 3: Feature Warehouse Generation...")
    
    # 1. Dynamically count rows
    raw_count = count_jsonl_rows(RAW_DATA_PATH)
    
    # 2. Process in chunks
    chunk_idx = 0
    all_feature_files = []
    all_text_files = []
    all_graph_files = []
    
    for batch in tqdm(stream_candidates(RAW_DATA_PATH), total=raw_count // 5000 + 1):
        chunk_features = []
        chunk_texts = []
        chunk_graphs = []
        
        for raw_line, cand in batch:
            try:
                f_row, t_row, g_edges = extract_candidate_features(raw_line, cand)
                chunk_features.append(f_row)
                chunk_texts.append(t_row)
                chunk_graphs.extend(g_edges)
            except Exception as e:
                print(f"Error extracting features for candidate {cand.get('candidate_id', 'unknown')}: {e}")
        
        # Save chunk
        chunk_idx += 1
        
        f_df = pl.DataFrame(chunk_features)
        t_df = pl.DataFrame(chunk_texts)
        g_df = pl.DataFrame(chunk_graphs) if chunk_graphs else pl.DataFrame({"candidate_id": [], "parent": [], "child": [], "edge_weight": [], "depth": [], "origin": []})
        
        f_path = os.path.join(CHECKPOINTS_DIR, f"features_part_{chunk_idx:03d}.parquet")
        t_path = os.path.join(CHECKPOINTS_DIR, f"texts_part_{chunk_idx:03d}.parquet")
        g_path = os.path.join(CHECKPOINTS_DIR, f"graphs_part_{chunk_idx:03d}.parquet")
        
        f_df.write_parquet(f_path)
        t_df.write_parquet(t_path)
        g_df.write_parquet(g_path)
        
        all_feature_files.append(f_path)
        all_text_files.append(t_path)
        all_graph_files.append(g_path)
        
    # 3. Merge Chunks
    print("Merging chunks into final Parquet artifacts...")
    final_features_df = pl.concat([pl.read_parquet(f) for f in all_feature_files])
    final_texts_df = pl.concat([pl.read_parquet(f) for f in all_text_files])
    final_graphs_df = pl.concat([pl.read_parquet(f) for f in all_graph_files])
    
    final_features_df.write_parquet(FEATURES_PARQUET)
    final_texts_df.write_parquet(TEXTS_PARQUET)
    final_graphs_df.write_parquet(GRAPH_PARQUET)
    
    print(f"Saved {len(final_features_df)} features to {FEATURES_PARQUET}")
    print(f"Saved {len(final_texts_df)} texts to {TEXTS_PARQUET}")
    print(f"Saved {len(final_graphs_df)} edges to {GRAPH_PARQUET}")
    
    # 4. Generate Registry & Stats
    print("Generating Feature Registry and Statistics...")
    
    # Registry
    registry = {col: str(dtype) for col, dtype in zip(final_features_df.columns, final_features_df.dtypes)}
    with open(REGISTRY_JSON, "w") as f:
        json.dump(registry, f, indent=2)
        
    # Stats
    numeric_cols = [col for col, dtype in registry.items() if "Float" in dtype or "Int" in dtype]
    stats = {}
    pd_df = final_features_df.select(numeric_cols).to_pandas()
    
    for col in numeric_cols:
        col_series = pd_df[col]
        stats[col] = {
            "mean": float(col_series.mean()),
            "std": float(col_series.std()),
            "min": float(col_series.min()),
            "max": float(col_series.max())
        }
    with open(STATS_JSON, "w") as f:
        json.dump(stats, f, indent=2)
        
    # 5. V12 Verification Checklist
    print("Running V12 Verification Checklist...")
    
    # Shape Audit
    assert len(final_features_df) == raw_count, f"Shape Audit Failed: {len(final_features_df)} != {raw_count}"
    assert len(final_texts_df) == raw_count, f"Text Shape Audit Failed: {len(final_texts_df)} != {raw_count}"
    
    # Null Audit
    for col in numeric_cols:
        nulls = final_features_df.get_column(col).null_count()
        assert nulls == 0, f"Null Audit Failed: {col} has {nulls} nulls"
        
    # ID Uniqueness
    n_unique = final_features_df.get_column("candidate_id").n_unique()
    assert n_unique == raw_count, f"ID Uniqueness Failed: {n_unique} != {raw_count}"
    
    # Ontology Coverage Audit
    retrieval_mean = stats.get("retrieval_score", {}).get("mean", 0.0)
    ownership_mean = stats.get("ownership_score", {}).get("mean", 0.0)
    
    if retrieval_mean == 0.0 or ownership_mean == 0.0:
        print("Warning: Ontology Coverage Audit found strict 0.0 means for key ontology scores.")
    if retrieval_mean == 1.0 or ownership_mean == 1.0:
        print("Warning: Ontology Coverage Audit found strict 1.0 means for key ontology scores.")
        
    print("V12 Verification Checklist Passed!")

if __name__ == "__main__":
    build_feature_warehouse()
