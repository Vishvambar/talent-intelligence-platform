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

class JDSchema(BaseModel):
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
        "hard_requirements": merged_hard,
        "preferred_requirements": merged_pref,
        "negative_signals": merged_neg
    }

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
    schema, meta = router.generate(PROMPT_TECHNICAL.format(jd=jd_text), "phase01", JDSchema)
    schemas.append(schema)
    metadata_list.append(meta)
    
    print("Running Execution Lens...")
    schema, meta = router.generate(PROMPT_EXECUTION.format(jd=jd_text), "phase01", JDSchema)
    schemas.append(schema)
    metadata_list.append(meta)
    
    print("Running Culture Lens...")
    schema, meta = router.generate(PROMPT_CULTURE.format(jd=jd_text), "phase01", JDSchema)
    schemas.append(schema)
    metadata_list.append(meta)
    
    print("Merging Lenses using Median Aggregation...")
    final_output = merge_schemas(schemas)
    
    # Aggregate Diagnostics
    total_time = sum(m.get("generation_time_seconds", 0) for m in metadata_list)
    total_retries = sum(m.get("schema_retries", 0) for m in metadata_list)
    cache_hits = sum(1 for m in metadata_list if m.get("cache_hit", False))
    providers_used = list(set(m.get("provider", "unknown") for m in metadata_list))
    
    # Append Metadata
    final_output["metadata"] = {
        "phase": "phase01",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "successful_lenses": len(schemas),
        "failed_lenses": 3 - len(schemas),
        "cache_hit_rate": round(cache_hits / 3, 2),
        "generation_time_seconds": round(total_time, 2),
        "schema_retries": total_retries,
        "providers_used": providers_used
    }
    
    output_path = os.path.join(project_root, "data", "artifacts", "jd_requirements.json")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    with open(output_path, "w") as f:
        json.dump(final_output, f, indent=2)
        
    print(f"Successfully generated {output_path}")

if __name__ == "__main__":
    run()
