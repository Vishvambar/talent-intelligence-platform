import os
import sys
import json
import statistics
from datetime import datetime
from typing import List, Dict, Any
from pydantic import BaseModel, Field
import docx

# Ensure we can import shared module from project root
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shared.llm.router import LLMRouter

# ==============================================================================
# CANONICAL MAPPINGS
# ==============================================================================

CANONICAL_REQUIREMENTS = {
    "evaluation_frameworks": [
        "ranking_evaluation",
        "search_evaluation"
    ],
    "llm_fine_tuning": [
        "llm_finetuning",
        "parameter_efficient_finetuning"
    ],
    "embeddings_retrieval": [
        "dense_retrieval",
        "vector_search"
    ],
    "product_engineering_background": [
        "scrappy_product_engineering_attitude",
        "scrappy_product_engineering",
        "product_company_experience"
    ],
    "domain_experience": [
        "marketplace_experience"
    ]
}

CANONICAL_NEGATIVES = {
    "consulting_only_background": [
        "it_services_only",
        "consulting_only_experience",
        "system_integrator_experience"
    ],
    "non_coding_engineers": [
        "non_coding_architects",
        "hands_off_leadership",
        "hands_off_architect",
        "non_coding_leads"
    ],
    "langchain_only_experience": [
        "shallow_ai_experience",
        "wrapper_development",
        "toy_ai_projects"
    ],
    "title_chasers": [
        "job_hopping",
        "frequent_switchers"
    ],
    "non_nlp_domains": [
        "unrelated_ai_domains",
        "computer_vision_only"
    ],
    "framework_enthusiasts": [
        "tutorial_driven_ai"
    ],
    "pure_research_background": [
        "academic_only",
        "pure_research_focus"
    ]
}

# ==============================================================================
# SCHEMAS
# ==============================================================================

class RequirementTrait(BaseModel):
    required: bool
    importance: int = Field(ge=1, le=10)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: List[str]
    canonical_terms: List[str]
    synonyms: List[str]

class NegativeSignal(BaseModel):
    penalty_strength: int = Field(ge=1, le=10)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: List[str]
    canonical_terms: List[str]
    synonyms: List[str]

class JDDimensions(BaseModel):
    technical_depth: int = Field(ge=1, le=10)
    retrieval_expertise: int = Field(ge=1, le=10)
    evaluation_expertise: int = Field(ge=1, le=10)
    startup_builder: int = Field(ge=1, le=10)
    founding_team_fit: int = Field(ge=1, le=10)
    research_focus: int = Field(ge=1, le=10)
    consulting_fit: int = Field(ge=1, le=10)

class ExperienceConstraints(BaseModel):
    min_years: int
    max_years: int
    preferred_years: List[int]

class JDSchema(BaseModel):
    jd_dimensions: JDDimensions
    experience_constraints: ExperienceConstraints
    hard_requirements: Dict[str, RequirementTrait]
    preferred_requirements: Dict[str, RequirementTrait]
    negative_signals: Dict[str, NegativeSignal]

# ==============================================================================
# PROMPTS
# ==============================================================================

BASE_INSTRUCTIONS = """
You are a Principal Technical Recruiter analyzing a Job Description.
Extract the constraints matching the Pydantic schema precisely.
Extract ALL constraints you find. Use broad canonical terms (e.g., 'vector database').
NEVER put company names in synonyms (e.g. do not use 'TCS', use 'IT Services').

Also score the overall JD along the specified `jd_dimensions` from 1 to 10 based on how strongly the JD emphasizes each aspect.

Job Description:
{jd}
"""

PROMPT_TECHNICAL = BASE_INSTRUCTIONS + """
LENS: TECHNICAL
Focus strictly on engineering constraints:
- ML frameworks, Vector Databases, Embeddings, Evaluation systems, Code Quality, Architectures.
Ignore cultural or purely execution traits.
"""

PROMPT_EXECUTION = BASE_INSTRUCTIONS + """
LENS: EXECUTION & PRODUCT
Focus strictly on shipping velocity, startup/product experience, and execution.
Look for signals like "shipped working ranker in a week", "real users", "production experience".
Identify negative signals like "research-only", "academic labs".
"""

PROMPT_CULTURE = BASE_INSTRUCTIONS + """
LENS: CULTURE & ALIGNMENT
Focus strictly on behavioral signals:
Ownership, async-first, writing culture, fast failure, title-chasers, framework enthusiasts.
"""

# ==============================================================================
# MERGING LOGIC
# ==============================================================================

def merge_traits(traits: List[RequirementTrait]) -> RequirementTrait:
    required = sum(t.required for t in traits) > len(traits) / 2
    importance = int(statistics.median([t.importance for t in traits]))
    confidence = round(statistics.median([t.confidence for t in traits]), 3)
    
    evidence = list(set([e for t in traits for e in t.evidence]))
    canonical_terms = list(set([c for t in traits for c in t.canonical_terms]))
    synonyms = list(set([s for t in traits for s in t.synonyms]))
    
    return RequirementTrait(
        required=required,
        importance=importance,
        confidence=confidence,
        evidence=evidence,
        canonical_terms=canonical_terms,
        synonyms=synonyms
    )

def merge_negative_signals(signals: List[NegativeSignal]) -> NegativeSignal:
    penalty = int(statistics.median([s.penalty_strength for s in signals]))
    confidence = round(statistics.median([s.confidence for s in signals]), 3)
    
    evidence = list(set([e for s in signals for e in s.evidence]))
    canonical_terms = list(set([c for s in signals for c in s.canonical_terms]))
    synonyms = list(set([s for s in signals for s in s.synonyms]))
    
    return NegativeSignal(
        penalty_strength=penalty,
        confidence=confidence,
        evidence=evidence,
        canonical_terms=canonical_terms,
        synonyms=synonyms
    )

def merge_schemas(schemas: List[JDSchema]) -> Dict[str, Any]:
    merged_dimensions = {
        "technical_depth": int(statistics.median([s.jd_dimensions.technical_depth for s in schemas])),
        "retrieval_expertise": int(statistics.median([s.jd_dimensions.retrieval_expertise for s in schemas])),
        "evaluation_expertise": int(statistics.median([s.jd_dimensions.evaluation_expertise for s in schemas])),
        "startup_builder": int(statistics.median([s.jd_dimensions.startup_builder for s in schemas])),
        "founding_team_fit": int(statistics.median([s.jd_dimensions.founding_team_fit for s in schemas])),
        "research_focus": int(statistics.median([s.jd_dimensions.research_focus for s in schemas])),
        "consulting_fit": int(statistics.median([s.jd_dimensions.consulting_fit for s in schemas]))
    }
    
    # Merge experience constraints
    all_preferred_years = []
    for s in schemas:
        all_preferred_years.extend(s.experience_constraints.preferred_years)
        
    merged_experience = {
        "min_years": int(statistics.median([s.experience_constraints.min_years for s in schemas])),
        "max_years": int(statistics.median([s.experience_constraints.max_years for s in schemas])),
        "preferred_years": sorted(list(set(all_preferred_years)))
    }

    all_hard_keys = set(k for s in schemas for k in s.hard_requirements.keys())
    all_pref_keys = set(k for s in schemas for k in s.preferred_requirements.keys())
    all_neg_keys = set(k for s in schemas for k in s.negative_signals.keys())
    
    merged_hard = {}
    for key in all_hard_keys:
        traits = [s.hard_requirements[key] for s in schemas if key in s.hard_requirements]
        merged_hard[key] = merge_traits(traits).model_dump()
        
    merged_pref = {}
    for key in all_pref_keys:
        traits = [s.preferred_requirements[key] for s in schemas if key in s.preferred_requirements]
        merged_pref[key] = merge_traits(traits).model_dump()
        
    merged_neg = {}
    for key in all_neg_keys:
        signals = [s.negative_signals[key] for s in schemas if key in s.negative_signals]
        merged_neg[key] = merge_negative_signals(signals).model_dump()
        
    return {
        "jd_dimensions": merged_dimensions,
        "experience_constraints": merged_experience,
        "hard_requirements": merged_hard,
        "preferred_requirements": merged_pref,
        "negative_signals": merged_neg
    }

# ==============================================================================
# CANONICALIZATION LOGIC
# ==============================================================================

def canonicalize_key(key: str, mapping: dict) -> str:
    for canonical, aliases in mapping.items():
        if key == canonical or key in aliases:
            return canonical
    return key

def merge_requirement_traits_canonical(traits_list: list) -> dict:
    required = sum(1 for t in traits_list if t.get("required", False)) > len(traits_list) / 2
    importance = max(t.get("importance", 0) for t in traits_list)
    confidence = statistics.median([t.get("confidence", 0.0) for t in traits_list])
    
    evidence = list(set([e for t in traits_list for e in t.get("evidence", [])]))
    canonical_terms = list(set([c for t in traits_list for c in t.get("canonical_terms", [])]))
    synonyms = list(set([s for t in traits_list for s in t.get("synonyms", [])]))
    
    return {
        "required": required,
        "importance": importance,
        "confidence": round(confidence, 3),
        "evidence": evidence,
        "canonical_terms": canonical_terms,
        "synonyms": synonyms
    }

def merge_negative_signals_canonical(signals_list: list) -> dict:
    penalty = max(s.get("penalty_strength", 0) for s in signals_list)
    confidence = statistics.median([s.get("confidence", 0.0) for s in signals_list])
    
    evidence = list(set([e for s in signals_list for e in s.get("evidence", [])]))
    canonical_terms = list(set([c for s in signals_list for c in s.get("canonical_terms", [])]))
    synonyms = list(set([s for s in signals_list for s in s.get("synonyms", [])]))
    
    return {
        "penalty_strength": penalty,
        "confidence": round(confidence, 3),
        "evidence": evidence,
        "canonical_terms": canonical_terms,
        "synonyms": synonyms
    }

def process_canonical_section(section: dict, mapping: dict, is_negative: bool) -> tuple[dict, list]:
    grouped = {}
    for raw_key, value in section.items():
        canon_key = canonicalize_key(raw_key, mapping)
        if canon_key not in grouped:
            grouped[canon_key] = []
        grouped[canon_key].append((raw_key, value))
        
    canonicalized_section = {}
    merged_info = []
    for canon_key, items in grouped.items():
        raw_keys = [k for k, v in items]
        values = [v for k, v in items]
        
        if len(raw_keys) > 1:
            merged_info.append({
                "canonical": canon_key,
                "merged": [k for k in raw_keys if k != canon_key]
            })
            
        if is_negative:
            canonicalized_section[canon_key] = merge_negative_signals_canonical(values)
        else:
            canonicalized_section[canon_key] = merge_requirement_traits_canonical(values)
            
    return canonicalized_section, merged_info

# ==============================================================================
# MAIN ENGINE
# ==============================================================================

def extract_docx_text(path: str) -> str:
    try:
        doc = docx.Document(path)
        return "\n".join([p.text for p in doc.paragraphs])
    except Exception as e:
        print(f"Failed to read {path}: {e}")
        # Fallback to .txt if docx parsing fails entirely in non-standard environments
        txt_path = path + ".txt"
        if os.path.exists(txt_path):
            with open(txt_path, "r", encoding="utf-8") as f:
                return f.read()
        raise e

def run():
    print("Starting Phase 1: JD Intelligence Engine...")
    
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    jd_path = os.path.join(project_root, "data", "raw", "job_description.docx")
    jd_text = extract_docx_text(jd_path)
    
    router = LLMRouter()
    schemas = []
    metadata_list = []
    
    print("Running Technical Lens...")
    try:
        schema, meta = router.generate(PROMPT_TECHNICAL.format(jd=jd_text), "phase01", JDSchema)
        schemas.append(schema)
        metadata_list.append(meta)
    except Exception as e:
        print(f"Technical Lens failed: {e}")
    
    print("Running Execution Lens...")
    try:
        schema, meta = router.generate(PROMPT_EXECUTION.format(jd=jd_text), "phase01", JDSchema)
        schemas.append(schema)
        metadata_list.append(meta)
    except Exception as e:
        print(f"Execution Lens failed: {e}")
    
    print("Running Culture Lens...")
    try:
        schema, meta = router.generate(PROMPT_CULTURE.format(jd=jd_text), "phase01", JDSchema)
        schemas.append(schema)
        metadata_list.append(meta)
    except Exception as e:
        print(f"Culture Lens failed: {e}")
        
    if not schemas:
        print("All lenses failed to generate a schema. Aborting Phase 1.")
        return
    
    print("Merging Lenses using Median Aggregation...")
    raw_output = merge_schemas(schemas)
    
    print("Running Semantic Canonicalization...")
    original_hard = len(raw_output.get("hard_requirements", {}))
    original_pref = len(raw_output.get("preferred_requirements", {}))
    original_neg = len(raw_output.get("negative_signals", {}))
    
    raw_output["hard_requirements"], hard_merged = process_canonical_section(raw_output.get("hard_requirements", {}), CANONICAL_REQUIREMENTS, False)
    raw_output["preferred_requirements"], pref_merged = process_canonical_section(raw_output.get("preferred_requirements", {}), CANONICAL_REQUIREMENTS, False)
    raw_output["negative_signals"], neg_merged = process_canonical_section(raw_output.get("negative_signals", {}), CANONICAL_NEGATIVES, True)
    
    all_merged_info = hard_merged + pref_merged + neg_merged
    
    final_hard = len(raw_output["hard_requirements"])
    final_pref = len(raw_output["preferred_requirements"])
    final_neg = len(raw_output["negative_signals"])
    duplicates_removed = (original_hard + original_pref + original_neg) - (final_hard + final_pref + final_neg)
    
    print(f"Canonicalization complete. Duplicates removed: {duplicates_removed}")
    
    # Aggregate Diagnostics
    total_time = sum(m.get("generation_time_seconds", 0) for m in metadata_list)
    total_retries = sum(m.get("schema_retries", 0) for m in metadata_list)
    cache_hits = sum(1 for m in metadata_list if m.get("cache_hit", False))
    providers_used = list(set(m.get("provider", "unknown") for m in metadata_list))
    
    # Append Metadata
    raw_output["metadata"] = {
        "phase": "phase01",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "successful_lenses": len(schemas),
        "failed_lenses": 3 - len(schemas),
        "cache_hit_rate": round(cache_hits / 3, 2),
        "generation_time_seconds": round(total_time, 2),
        "schema_retries": total_retries,
        "providers_used": providers_used,
        "semantic_canonicalization": {
            "status": "success",
            "duplicates_removed": duplicates_removed,
            "merged_concepts": all_merged_info
        }
    }
    
    output_path = os.path.join(project_root, "data", "artifacts", "jd_requirements.json")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    with open(output_path, "w") as f:
        json.dump(raw_output, f, indent=2)
        
    print(f"Successfully generated {output_path}")

if __name__ == "__main__":
    run()
