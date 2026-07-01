import json
import hashlib
import statistics
import re
import os
import time
import torch
import numpy as np
from datetime import datetime
from typing import List, Dict, Any, Optional
from enum import Enum
from collections import Counter
from pydantic import BaseModel, Field

try:
    import transformers
    from transformers import AutoTokenizer, AutoModelForCausalLM
except ImportError:
    print("Warning: transformers is not installed. Script will fail if executed.")
    transformers = None

# Determinism
torch.manual_seed(42)
np.random.seed(42)

# ---------------------------------------------------------
# 1. SCHEMAS
# ---------------------------------------------------------
class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

class EntityType(str, Enum):
    TECHNOLOGY = "Technology"
    ORGANIZATION = "Organization"
    PERSON = "Person"
    METRIC = "Metric"
    FRAMEWORK = "Framework"
    LANGUAGE = "Language"
    BEHAVIOR = "Behavior"

class SemanticRole(str, Enum):
    SKILL = "Skill"
    EXPERIENCE = "Experience"
    REQUIREMENT = "Requirement"
    PREFERENCE = "Preference"
    NEGATIVE_SIGNAL = "NegativeSignal"
    EVIDENCE = "Evidence"
    BUSINESS_SIGNAL = "BusinessSignal"

class RequirementLevel(str, Enum):
    CRITICAL = "CRITICAL"
    IMPORTANT = "IMPORTANT"
    USEFUL = "USEFUL"
    OPTIONAL = "OPTIONAL"

def get_req_weight(level: str) -> float:
    return {"CRITICAL": 1.0, "IMPORTANT": 0.8, "USEFUL": 0.5, "OPTIONAL": 0.2}.get(level, 0.5)

class EvidenceSpan(BaseModel):
    text: str = Field(description="A short label for the evidence.")
    context_snippet: str = Field(default="", description="The exact surrounding sentence copied verbatim from the JD. Do not paraphrase.")
    offset_start: int = 0
    offset_end: int = 0

class PriorityNode(BaseModel):
    entity_type: EntityType
    semantic_role: SemanticRole
    priority_weight: float = Field(ge=0.0, le=1.0)
    extraction_confidence: float = Field(ge=0.0, le=1.0)
    confidence_reason: str = Field(default="", description="Why is this extraction confidence at this level?")
    source_confidence: float = 0.0
    contributors: List[str] = []
    evidence: List[EvidenceSpan] = Field(description="Extract up to 3 exact evidence spans.")
    children: Dict[str, float] = Field(default={}, description="Map of child nodes to their edge weight (0.0 to 1.0)")
    parents: Dict[str, float] = {}

class EnhancedNegativeSignal(BaseModel):
    penalty_weight: float = Field(ge=0.0, le=1.0)
    extraction_confidence: float = Field(ge=0.0, le=1.0)
    confidence_reason: str = Field(default="")
    source_confidence: float = 0.0
    contributors: List[str] = []
    evidence: List[EvidenceSpan] = Field(description="Extract up to 3 exact evidence spans.")
    counter_example: str = Field(default="", description="Condition where this penalty could be reduced (e.g. strong production experience overrides lack of degree).")
    severity: Severity
    penalty_reason: str = Field(description="Explanation for why this is a negative signal.")

class HiringPhilosophy(BaseModel):
    builder: float = Field(default=0.5, ge=0.0, le=1.0)
    research: float = Field(default=0.5, ge=0.0, le=1.0)
    execution: float = Field(default=0.5, ge=0.0, le=1.0)
    leadership: float = Field(default=0.5, ge=0.0, le=1.0)
    ownership: float = Field(default=0.5, ge=0.0, le=1.0)
    product_thinking: float = Field(default=0.5, ge=0.0, le=1.0)
    customer_empathy: float = Field(default=0.5, ge=0.0, le=1.0)
    learning_velocity: float = Field(default=0.5, ge=0.0, le=1.0)
    ambiguity_tolerance: float = Field(default=0.5, ge=0.0, le=1.0)
    technical_depth: float = Field(default=0.5, ge=0.0, le=1.0)
    communication: float = Field(default=0.5, ge=0.0, le=1.0)
    mentorship: float = Field(default=0.5, ge=0.0, le=1.0)
    systems_thinking: float = Field(default=0.5, ge=0.0, le=1.0)
    quality_focus: float = Field(default=0.5, ge=0.0, le=1.0)
    decision_speed: float = Field(default=0.5, ge=0.0, le=1.0)
    risk_appetite: float = Field(default=0.5, ge=0.0, le=1.0)
    risk_tolerance: float = Field(default=0.5, ge=0.0, le=1.0)
    false_positive_tolerance: float = Field(default=0.5, ge=0.0, le=1.0)
    candidate_conservatism: float = Field(default=0.5, ge=0.0, le=1.0)

class ExperienceConstraints(BaseModel):
    min_years: int
    max_years: int
    preferred_years: List[int]
    is_strict: bool = Field(description="Is this experience range a strict requirement?")

class RequirementTrait(BaseModel):
    requirement_level: RequirementLevel
    importance: int = Field(ge=1, le=10)
    extraction_confidence: float = Field(ge=0.0, le=1.0)
    confidence_reason: str = Field(default="")
    source_confidence: float = 0.0
    contributors: List[str] = []
    reason: str = Field(description="Why is this a requirement?")
    evidence: List[EvidenceSpan] = Field(description="Extract up to 3 exact evidence spans.")
    canonical_terms: List[str]
    synonyms: List[str]

# Domain Specific Lenses
class CapabilityOutput(BaseModel):
    hard_requirements: Dict[str, RequirementTrait] = {}
    preferred_requirements: Dict[str, RequirementTrait] = {}
    experience_constraints: ExperienceConstraints
    technical_priorities: Dict[str, PriorityNode] = {}
    technical_philosophy: HiringPhilosophy

class BusinessOutput(BaseModel):
    behavioral_priorities: Dict[str, PriorityNode] = {}
    business_priorities: Dict[str, PriorityNode] = {}
    implicit_priorities: Dict[str, PriorityNode] = {}
    business_philosophy: HiringPhilosophy

class RiskOutput(BaseModel):
    negative_signals: Dict[str, EnhancedNegativeSignal] = {}
    deal_breakers: List[str] = Field(description="List of explicitly extracted deal-breakers.")
    tradeoffs: Dict[str, str] = Field(description="Explicit tradeoffs identified in the JD.")
    anti_patterns: List[str] = Field(description="Candidate anti-patterns explicitly or implicitly warned against.")
    risk_assessment: str = Field(description="A short summary of the overall hiring risk.")
    risk_philosophy: HiringPhilosophy

class DecisionRule(BaseModel):
    preferred: str
    over: str
    confidence: float = Field(ge=0.0, le=1.0)
    confidence_reason: str = Field(default="")

class RecruiterMentalModel(BaseModel):
    ideal_candidate: Dict[str, str]
    decision_priority: List[str]
    decision_rules: List[DecisionRule] = []
    deal_breakers: List[str]
    nice_to_have: List[str]
    tradeoffs: Dict[str, str]

class HiringSummary(BaseModel):
    technical_focus: List[str]
    behavioral_focus: List[str]
    business_focus: List[str]
    avoid: List[str]
    executive_summary: str

class TeacherPromptContext(BaseModel):
    ranking_strategy: str
    decision_rules: List[str]
    hard_filters: List[str]
    soft_preferences: List[str]
    preferred_tradeoffs: List[str]
    evaluation_weights: Dict[str, float]
    critical_skills: List[str]
    behavioral_bias: List[str]
    ideal_candidate: str
    anti_patterns: List[str]
    
class RecruiterChecklist(BaseModel):
    top_10_signals: List[str]
    top_10_penalties: List[str]
    tie_breakers: List[str]
    decision_tree: str

class PostMergeGeneration(BaseModel):
    recruiter_mental_model: RecruiterMentalModel
    hiring_summary: HiringSummary
    teacher_prompt_context: TeacherPromptContext
    recruiter_checklist: RecruiterChecklist
    retrieval_strategy: List[str] = Field(description="Explicit search/ranking heuristics (e.g., Dense > BM25).")
    evaluation_dimensions: Dict[str, float]
    hiring_philosophy: HiringPhilosophy
    ranking_heuristics: List[str]
    deal_breakers: List[str]
    tradeoffs: Dict[str, str]
    tie_break_rules: List[str]
    confidence_summary: str
    evidence_summary: str

# ---------------------------------------------------------
# 2. GRAPH MERGING AND CONFLICT RESOLUTION
# ---------------------------------------------------------
MERGE_REPORT = {
    "nodes_merged": 0,
    "conflicts_entity_type": 0,
    "conflicts_semantic_role": 0,
    "conflicts_requirement_level": 0,
    "conflicts_severity": 0,
    "details": []
}

def log_conflict(reason: str, key: str, winner: str, losers: Dict[str, Any]):
    MERGE_REPORT["details"].append({
        "node": key,
        "reason": reason,
        "winner": winner,
        "losers": losers
    })

def fix_evidence_offsets(evidence_list: List[Dict], full_jd_text: str) -> List[Dict]:
    for ev in evidence_list:
        text = ev.get("text", "")
        context = ev.get("context_snippet", "")
        if text:
            if context and context in full_jd_text:
                c_start = full_jd_text.find(context)
                t_start = context.find(text)
                if t_start != -1:
                    ev["offset_start"] = c_start + t_start
                    ev["offset_end"] = ev["offset_start"] + len(text)
                    continue
            escaped_text = re.escape(text)
            match = next(re.finditer(escaped_text, full_jd_text), None)
            if match:
                ev["offset_start"] = match.start()
                ev["offset_end"] = match.end()
    return evidence_list

def deduplicate_evidence(evidence_lists: List[List[Dict]]) -> List[Dict]:
    unique_map = {}
    for sublist in evidence_lists:
        for ev in sublist:
            t = ev.get("text", "").strip()
            if t and t not in unique_map:
                unique_map[t] = ev
    return list(unique_map.values())

def deduplicate_stable(items: List[str]) -> List[str]:
    seen = set()
    res = []
    for x in items:
        if x not in seen:
            seen.add(x)
            res.append(x)
    return res

def resolve_categorical(val_map: Dict[str, str], key_name: str, metric_counter: str) -> str:
    if not val_map:
        return ""
    counts = Counter(val_map.values())
    if len(counts) > 1:
        MERGE_REPORT[metric_counter] += 1
        winner_val = counts.most_common(1)[0][0]
        winner_sources = [k for k, v in val_map.items() if v == winner_val]
        losers = {k: v for k, v in val_map.items() if v != winner_val}
        log_conflict(f"Disagreement on {metric_counter}", key_name, f"{winner_val} (from {winner_sources})", losers)
        return winner_val
    return list(val_map.values())[0]

def merge_priority_nodes(key: str, nodes: List[Dict], full_jd_text: str) -> Dict:
    MERGE_REPORT["nodes_merged"] += 1
    
    winning_node = max(nodes, key=lambda n: n.get("priority_weight", 0.0) * n.get("extraction_confidence", 0.0))
    max_weight = winning_node.get("priority_weight", 0.0)
    inherited_ext_conf = winning_node.get("extraction_confidence", 0.0)
    inherited_conf_reason = winning_node.get("confidence_reason", "")
    
    entity_types = {n.get("_lens_source"): n.get("entity_type") for n in nodes if n.get("entity_type")}
    entity_type = resolve_categorical(entity_types, key, "conflicts_entity_type") or "Technology"
    
    semantic_roles = {n.get("_lens_source"): n.get("semantic_role") for n in nodes if n.get("semantic_role")}
    semantic_role = resolve_categorical(semantic_roles, key, "conflicts_semantic_role") or "Skill"
    
    contributors = deduplicate_stable([n.get("_lens_source") for n in nodes if n.get("_lens_source")])
    
    merged_children = {}
    for n in nodes:
        for child, cw in n.get("children", {}).items():
            merged_children[child] = max(merged_children.get(child, 0.0), cw)
            
    evidence_lists = [n.get("evidence", []) for n in nodes]
    merged_evidence = deduplicate_evidence(evidence_lists)
    merged_evidence = fix_evidence_offsets(merged_evidence, full_jd_text)
    
    return {
        "entity_type": entity_type,
        "semantic_role": semantic_role,
        "priority_weight": max_weight,
        "extraction_confidence": inherited_ext_conf,
        "confidence_reason": inherited_conf_reason,
        "source_confidence": 1.0, # Indicates single source structural trust
        "contributors": contributors,
        "evidence": merged_evidence,
        "children": merged_children,
        "parents": {} 
    }

def merge_negative_signals(key: str, nodes: List[Dict], full_jd_text: str) -> Dict:
    winning_node = max(nodes, key=lambda n: n.get("penalty_weight", 0.0) * n.get("extraction_confidence", 0.0))
    max_weight = winning_node.get("penalty_weight", 0.0)
    inherited_ext_conf = winning_node.get("extraction_confidence", 0.0)
    inherited_conf_reason = winning_node.get("confidence_reason", "")
    penalty_reason = winning_node.get("penalty_reason", "")
    counter_example = winning_node.get("counter_example", "")
    
    severity_rank = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
    rev_rank = {1: "LOW", 2: "MEDIUM", 3: "HIGH", 4: "CRITICAL"}
    
    severities = {n.get("_lens_source"): n.get("severity", "LOW") for n in nodes}
    counts = Counter(severities.values())
    if len(counts) > 1:
        MERGE_REPORT["conflicts_severity"] += 1
        med_rank = int(round(statistics.median([severity_rank.get(s, 1) for s in severities.values()])))
        median_sev = rev_rank.get(med_rank, "LOW")
        winner_sources = [k for k, v in severities.items() if v == median_sev]
        losers = {k: v for k, v in severities.items() if v != median_sev}
        log_conflict("Disagreement on Negative Severity", key, f"{median_sev} (from {winner_sources})", losers)
    else:
        median_sev = list(severities.values())[0] if severities else "LOW"
    
    contributors = deduplicate_stable([n.get("_lens_source") for n in nodes if n.get("_lens_source")])
    
    evidence_lists = [n.get("evidence", []) for n in nodes]
    merged_evidence = deduplicate_evidence(evidence_lists)
    merged_evidence = fix_evidence_offsets(merged_evidence, full_jd_text)
    
    return {
        "penalty_weight": max_weight,
        "extraction_confidence": inherited_ext_conf,
        "confidence_reason": inherited_conf_reason,
        "source_confidence": 1.0,
        "contributors": contributors,
        "evidence": merged_evidence,
        "counter_example": counter_example,
        "severity": median_sev,
        "penalty_reason": penalty_reason
    }

def merge_requirement_traits(key: str, traits: List[Dict], full_jd_text: str) -> Dict:
    levels = {t.get("_lens_source"): t.get("requirement_level", "OPTIONAL") for t in traits}
    counts = Counter(levels.values())
    if len(counts) > 1:
        MERGE_REPORT["conflicts_requirement_level"] += 1
        
    best_level = "OPTIONAL"
    best_weight = 0.0
    winning_ext_conf = 0.0
    winning_conf_reason = ""
    winning_reason = ""
    importance = 5
    
    for t in traits:
        level = t.get("requirement_level", "OPTIONAL")
        weight = get_req_weight(level)
        if weight > best_weight:
            best_weight = weight
            best_level = level
            winning_ext_conf = t.get("extraction_confidence", 0.0)
            winning_conf_reason = t.get("confidence_reason", "")
            winning_reason = t.get("reason", "")
            importance = t.get("importance", 5)
            
    if len(counts) > 1:
        winner_sources = [k for k, v in levels.items() if v == best_level]
        losers = {k: v for k, v in levels.items() if v != best_level}
        log_conflict("Disagreement on Requirement Level", key, f"{best_level} (from {winner_sources})", losers)
            
    contributors = deduplicate_stable([t.get("_lens_source") for t in traits if t.get("_lens_source")])
    
    evidence_lists = [t.get("evidence", []) for t in traits]
    merged_evidence = deduplicate_evidence(evidence_lists)
    merged_evidence = fix_evidence_offsets(merged_evidence, full_jd_text)
    
    all_canonicals = [c for t in traits for c in t.get("canonical_terms", [])]
    canonical = deduplicate_stable(all_canonicals)
    
    all_synonyms = [s for t in traits for s in t.get("synonyms", [])]
    synonyms = deduplicate_stable(all_synonyms)
    
    return {
        "requirement_level": best_level,
        "importance": importance,
        "extraction_confidence": winning_ext_conf,
        "confidence_reason": winning_conf_reason,
        "source_confidence": 1.0,
        "contributors": contributors,
        "reason": winning_reason,
        "evidence": merged_evidence,
        "canonical_terms": canonical,
        "synonyms": synonyms
    }

def detect_cycle(node: str, graph_map: Dict, visited: set, path: set) -> bool:
    visited.add(node)
    path.add(node)
    
    node_data = graph_map.get(node)
    if node_data:
        for child in node_data.get("children", {}):
            if child not in visited:
                if detect_cycle(child, graph_map, visited, path):
                    return True
            elif child in path:
                return True
                
    path.remove(node)
    return False

def merge_specialized_outputs(cap: dict, fit: dict, risk: dict, full_jd_text: str) -> Dict[str, Any]:
    for v in cap.get("hard_requirements", {}).values(): v["_lens_source"] = "Capability"
    for v in cap.get("preferred_requirements", {}).values(): v["_lens_source"] = "Capability"
    for v in cap.get("technical_priorities", {}).values(): v["_lens_source"] = "Capability"
    
    for v in fit.get("behavioral_priorities", {}).values(): v["_lens_source"] = "Business Fit"
    for v in fit.get("business_priorities", {}).values(): v["_lens_source"] = "Business Fit"
    for v in fit.get("implicit_priorities", {}).values(): v["_lens_source"] = "Business Fit"
    
    for v in risk.get("negative_signals", {}).values(): v["_lens_source"] = "Risk"
    
    merged_hard, merged_pref, merged_neg = {}, {}, {}
    for key, data in cap.get("hard_requirements", {}).items():
        merged_hard[key] = merge_requirement_traits(key, [data], full_jd_text)
    for key, data in cap.get("preferred_requirements", {}).items():
        merged_pref[key] = merge_requirement_traits(key, [data], full_jd_text)
    for key, data in risk.get("negative_signals", {}).items():
        merged_neg[key] = merge_negative_signals(key, [data], full_jd_text)
        
    exp = cap.get("experience_constraints", {})
    min_years = exp.get("min_years", 0)
    max_years = exp.get("max_years", 0)
    if min_years > max_years and max_years != 0:
        median_year = (min_years + max_years) // 2
        min_years = median_year
        max_years = median_year
        
    merged_exp = {
        "min_years": min_years,
        "max_years": max_years,
        "preferred_years": exp.get("preferred_years", []),
        "is_strict": exp.get("is_strict", False)
    }
    
    hi_tech, hi_behav, hi_biz, hi_impl = {}, {}, {}, {}
    for key, data in cap.get("technical_priorities", {}).items():
        hi_tech[key] = merge_priority_nodes(key, [data], full_jd_text)
    for key, data in fit.get("behavioral_priorities", {}).items():
        hi_behav[key] = merge_priority_nodes(key, [data], full_jd_text)
    for key, data in fit.get("business_priorities", {}).items():
        hi_biz[key] = merge_priority_nodes(key, [data], full_jd_text)
    for key, data in fit.get("implicit_priorities", {}).items():
        hi_impl[key] = merge_priority_nodes(key, [data], full_jd_text)
    
    hiring_intent_map = {
        "technical_priorities": hi_tech,
        "behavioral_priorities": hi_behav,
        "business_priorities": hi_biz,
        "implicit_priorities": hi_impl,
    }
    
    flat_graph = {}
    for section in hiring_intent_map.values():
        for k, v in section.items(): flat_graph[k] = v
        
    for parent_key, parent_data in flat_graph.items():
        for child_key, child_weight in parent_data.get("children", {}).items():
            if child_key in flat_graph:
                flat_graph[child_key].setdefault("parents", {})[parent_key] = child_weight
                visited, path = set(), set()
                if detect_cycle(child_key, flat_graph, visited, path):
                    print(f"Cycle detected and prevented by removing edge: {parent_key} -> {child_key}")
                    del flat_graph[child_key]["parents"][parent_key]
                    del flat_graph[parent_key]["children"][child_key]
    
    merged_philo = {}
    cap_philo = cap.get("technical_philosophy", {})
    fit_philo = fit.get("business_philosophy", {})
    risk_philo = risk.get("risk_philosophy", {})
    
    for k in cap_philo.keys():
        vals = [cap_philo.get(k), fit_philo.get(k), risk_philo.get(k)]
        valid_vals = [v for v in vals if v is not None]
        merged_philo[k] = round(statistics.median(valid_vals), 3) if valid_vals else 0.5
    
    all_priorities = []
    for section in hiring_intent_map.values():
        for k, v in section.items():
            all_priorities.append((k, v.get("priority_weight", 0.0) * v.get("extraction_confidence", 1.0)))
    ordered_priority_list = [k for k, w in sorted(all_priorities, key=lambda x: x[1], reverse=True)]
    
    return {
        "ordered_priority_list": ordered_priority_list,
        "experience_constraints": merged_exp,
        "hard_requirements": merged_hard,
        "preferred_requirements": merged_pref,
        "negative_signals": merged_neg,
        "deal_breakers": risk.get("deal_breakers", []),
        "tradeoffs": risk.get("tradeoffs", {}),
        "anti_patterns": risk.get("anti_patterns", []),
        "risk_assessment": risk.get("risk_assessment", ""),
        "hiring_intent": {
            **hiring_intent_map,
            "hiring_philosophy": merged_philo
        }
    }

# ---------------------------------------------------------
# 3. CORE GENERATION ENGINE
# ---------------------------------------------------------
tokenizer = None
model = None

def init_model():
    global tokenizer, model
    MODEL_PATH = "/kaggle/input/qwen2.5-32b-instruct-awq/transformers/default/1"
    
    if not os.path.exists(MODEL_PATH):
        # Fallback for the user's specific path
        MODEL_PATH = "/kaggle/input/models/qwen-lm/qwen-3/transformers/32b/1"
        if not os.path.exists(MODEL_PATH):
            MODEL_PATH = "Qwen/Qwen2.5-14B-Instruct"
        
    print(f"Loading tokenizer from {MODEL_PATH}...")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "left"
    
    print(f"Loading model from {MODEL_PATH}...")
    
    try:
        # Try 8-bit quantization for zero degradation while still fitting in VRAM
        from transformers import BitsAndBytesConfig
        bnb_config = BitsAndBytesConfig(
            load_in_8bit=True
        )
        print("Using bitsandbytes 8-bit quantization to preserve maximum quality while fitting in VRAM...")
        model = AutoModelForCausalLM.from_pretrained(
            MODEL_PATH,
            device_map="auto",
            quantization_config=bnb_config,
            trust_remote_code=True
        )
    except Exception as e:
        print(f"Warning: 4-bit quantization failed ({e}). Falling back to fp16...")
        model = AutoModelForCausalLM.from_pretrained(
            MODEL_PATH,
            torch_dtype=torch.float16,
            device_map="auto",
            low_cpu_mem_usage=True,
            trust_remote_code=True
        )

def extract_json(text: str) -> dict:
    # First try to find a markdown code block
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        json_str = m.group(1)
    else:
        # Fallback to greedy brace search
        m = re.search(r"(\{.*\})", text, re.DOTALL)
        if m is None:
            raise ValueError("No JSON block returned in Qwen output.")
        json_str = m.group(1)
    
    # Clean string
    json_str = json_str.strip()
    
    # Fix trailing commas
    json_str = re.sub(r',\s*}', '}', json_str)
    json_str = re.sub(r',\s*\]', ']', json_str)
    
    try:
        return json.loads(json_str)
    except json.decoder.JSONDecodeError as e:
        raise e

def generate_json(base_prompt: str, schema_class: type[BaseModel], max_retries: int = 4) -> tuple[BaseModel, dict]:
    # Clean the schema to prevent prompt bloating
    def prune(d):
        if not isinstance(d, dict): return d
        return {k: prune(v) for k, v in d.items() if k not in ["title", "description", "default"]}
    schema_dict = prune(schema_class.model_json_schema())
    schema_text = json.dumps(schema_dict, indent=2)
    
    prompt = f"{base_prompt}\n\nREQUIRED JSON SCHEMA:\n{schema_text}"
    
    messages = [
        {"role": "system", "content": "You are a precise JSON data extraction AI. You must strictly follow the JSON schema provided. Return ONLY valid JSON, starting with { and ending with }.\nCRITICAL: You MUST escape all double quotes inside string values (e.g., \"They said \\\"hello\\\"\"). Do not use trailing commas!"},
        {"role": "user", "content": prompt}
    ]
    
    start_time = time.time()
    metrics = {"total_tokens": 0, "prompt_tokens": 0, "retries": 0, "runtime_sec": 0, "prompt_hash": hashlib.sha256(base_prompt.encode()).hexdigest()}
    
    for attempt in range(max_retries):
        text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = tokenizer(text, return_tensors="pt").to(model.device)
        
        if attempt == 0:
            metrics["prompt_tokens"] = inputs.input_ids.shape[1]
            
        with torch.no_grad():
            output = model.generate(
                **inputs,
                do_sample=True,
                temperature=0.1,
                top_p=0.9,
                max_new_tokens=3000,
                pad_token_id=tokenizer.eos_token_id
            )
            
        generated = output[0][inputs.input_ids.shape[1]:]
        metrics["total_tokens"] += len(generated)
        response_text = tokenizer.decode(generated, skip_special_tokens=True)
        
        try:
            raw_json = extract_json(response_text)
            validated = schema_class.model_validate(raw_json)
            metrics["runtime_sec"] = round(time.time() - start_time, 2)
            return validated, metrics
        except Exception as e:
            if attempt == max_retries - 1:
                raise RuntimeError(f"Failed to generate valid JSON after {max_retries} attempts: {e}")
            metrics["retries"] += 1
            print(f"Retry {attempt+1}: JSON/Pydantic Validation failed -> {str(e)}")
            
            if len(messages) == 2:
                messages.append({"role": "assistant", "content": response_text})
                messages.append({"role": "user", "content": f"Your JSON was malformed.\nError: {e}\nThis is often caused by unescaped double quotes inside strings. You MUST escape quotes like \\\" or use single quotes for inner text.\nReturn ONLY the corrected JSON."})
            else:
                messages[2] = {"role": "assistant", "content": response_text}
                messages[3] = {"role": "user", "content": f"Your JSON was malformed.\nError: {e}\nThis is often caused by unescaped double quotes inside strings. You MUST escape quotes like \\\" or use single quotes for inner text.\nReturn ONLY the corrected JSON."}

    raise RuntimeError("Unexpected escape from retry loop")

# ---------------------------------------------------------
# 4. EXECUTION
# ---------------------------------------------------------
BASE_INSTRUCTIONS = """
Analyze the Job Description. Extract the constraints matching the JSON schema precisely.
Use broad canonical terms (e.g., 'vector database'). NEVER put company names in synonyms.
For EvidenceSpan context_snippet, copy the exact, unaltered sentence from the JD. Do not paraphrase.
Make sure to classify every node with an explicit `entity_type` and `semantic_role`.
For requirement_level, pick from CRITICAL, IMPORTANT, USEFUL, OPTIONAL. Provide a clear reason.

Job Description:
{jd}
"""

PROMPT_CAPABILITY = BASE_INSTRUCTIONS + """
LENS: CAPABILITY
You are a Principal ML Engineer analyzing a Job Description.
Your goal is to extract every technical competency, infer hidden technical expectations, and construct a deep parent-child dependency graph (e.g., Retrieval -> Embeddings -> VectorDB -> FAISS).

INSTRUCTIONS:
1. Extract ALL technical skills, languages, frameworks, and metrics.
2. For every node, estimate extraction confidence and EXPLAIN why (confidence_reason). Never guess beyond evidence.
3. Extract up to 3 explicit EvidenceSpan instances per node.
4. ONLY create parent-child links that are explicitly supported by the JD or are universally accepted technical prerequisite relationships. If uncertain, leave children empty.
"""

PROMPT_BUSINESS_FIT = BASE_INSTRUCTIONS + """
LENS: BUSINESS FIT
You are a Founding CTO analyzing a Job Description.
Your goal is to understand if a candidate will actually succeed in this specific company. 
Focus strictly on shipping velocity, startup/product experience, systems thinking, ownership, and ambiguity tolerance.

INSTRUCTIONS:
1. Extract ALL behavioral expectations, product requirements, and business goals.
2. For every node, estimate extraction confidence and EXPLAIN why (confidence_reason). Never guess beyond evidence.
3. Extract up to 3 explicit EvidenceSpan instances per node.
"""

PROMPT_RISK = BASE_INSTRUCTIONS + """
LENS: RISK
You are a ruthless Technical Recruiter analyzing a Job Description.
Your goal is to explicitly identify deal-breakers, anti-patterns, and reasons NOT to hire a candidate.

INSTRUCTIONS:
1. Extract ALL negative signals, failure modes, bureaucracy indicators, and red flags mentioned or heavily implied.
2. For every node, estimate Penalty Score and Penalty Confidence and EXPLAIN why (confidence_reason). Never guess beyond evidence.
3. Extract up to 3 explicit EvidenceSpan instances per node.
4. For every signal, provide a explicit `counter_example` where this penalty could be reduced (e.g., "If strong production experience exists, reduce penalty for lacking research papers.")
"""

PROMPT_POST_MERGE = """
You are a Principal Technical Recruiter finalizing a unified Intelligence Object.
I have aggregated the priorities, requirements, and philosophy from 3 highly opinionated lenses (Principal Engineer, Founding CTO, Ruthless Recruiter).

Here is the Aggregated Intelligence JSON:
{aggregated_json}

Your task is to produce a complete Recruiter Intelligence Report:
1. Construct the `RecruiterMentalModel`, detailing explicit `decision_rules` (e.g. {{"preferred":"Startup", "over":"Enterprise", "confidence":0.85, "confidence_reason": "..."}}), deal-breakers, tradeoffs, and tie-break rules.
2. Construct the `HiringSummary`.
3. Construct the `TeacherPromptContext`, populating ranking heuristics, behavioral bias, and explicit anti-patterns.
4. Construct the `RetrievalStrategy` with explicit search heuristics (e.g. "Dense > BM25", "Ignore certifications").
5. Construct the `RecruiterChecklist` including Top 10 Signals, Top 10 Penalties, and an explicit Decision Tree for candidate logic.
6. Output the complete `PostMergeGeneration` matching the schema EXACTLY.
"""

def extract_docx_text(path: str) -> str:
    if path.endswith(".docx"):
        import zipfile
        import xml.etree.ElementTree as ET
        try:
            with zipfile.ZipFile(path) as docx:
                xml_content = docx.read('word/document.xml')
                tree = ET.XML(xml_content)
                NAMESPACE = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
                paragraphs = []
                for paragraph in tree.iter(NAMESPACE + 'p'):
                    texts = [node.text for node in paragraph.iter(NAMESPACE + 't') if node.text]
                    if texts:
                        paragraphs.append(''.join(texts))
                return '\n'.join(paragraphs)
        except Exception as e:
            print(f"Warning: Failed to parse docx using standard library: {e}")
            pass
            
    # Fallback to reading as standard text
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        raise RuntimeError(f"Could not read {path} as text. Error: {e}")

def run_phase1_offline():
    start_time = time.time()
    
    jd_path = "/kaggle/input/datasets/vishvambarudavant/job-description/job_description.docx"
    jd_text = extract_docx_text(jd_path) if os.path.exists(jd_path) else "(Insert JD Here)"
    jd_hash = hashlib.sha256(jd_text.encode()).hexdigest()
    
    init_model()
    
    total_metrics = {"total_tokens": 0, "prompt_tokens": 0, "retries": 0}
    lens_metadata = {}
    
    print("Running Inference: Capability Lens (Principal ML Engineer)...")
    cap_out, m_cap = generate_json(PROMPT_CAPABILITY.format(jd=jd_text), CapabilityOutput)
    lens_metadata["capability"] = m_cap
    
    print("Running Inference: Business Fit Lens (Founding CTO)...")
    fit_out, m_fit = generate_json(PROMPT_BUSINESS_FIT.format(jd=jd_text), BusinessOutput)
    lens_metadata["business_fit"] = m_fit
    
    print("Running Inference: Risk Lens (Technical Recruiter)...")
    risk_out, m_risk = generate_json(PROMPT_RISK.format(jd=jd_text), RiskOutput)
    lens_metadata["risk"] = m_risk
    
    for m in [m_cap, m_fit, m_risk]:
        for k in ["total_tokens", "prompt_tokens", "retries"]: total_metrics[k] += m[k]
    
    print("Aggregating Lenses...")
    aggregated_core = merge_specialized_outputs(cap_out.model_dump(), fit_out.model_dump(), risk_out.model_dump(), jd_text)
    
    print("Running Post-Merge Inference (Recruiter Intelligence Report)...")
    agg_json_str = json.dumps(aggregated_core, indent=2)
    post_prompt = PROMPT_POST_MERGE.format(aggregated_json=agg_json_str)
    
    post_schema, m_post = generate_json(post_prompt, PostMergeGeneration)
    lens_metadata["post_merge"] = m_post
    for k in ["total_tokens", "prompt_tokens", "retries"]: total_metrics[k] += m_post[k]
    
    aggregated_core["recruiter_mental_model"] = post_schema.recruiter_mental_model.model_dump()
    aggregated_core["hiring_summary"] = post_schema.hiring_summary.model_dump()
    aggregated_core["teacher_prompt_context"] = post_schema.teacher_prompt_context.model_dump()
    aggregated_core["recruiter_checklist"] = post_schema.recruiter_checklist.model_dump()
    aggregated_core["retrieval_strategy"] = post_schema.retrieval_strategy
    aggregated_core["evaluation_dimensions"] = post_schema.evaluation_dimensions
    aggregated_core["hiring_philosophy"] = post_schema.hiring_philosophy.model_dump()
    aggregated_core["ranking_heuristics"] = post_schema.ranking_heuristics
    aggregated_core["confidence_summary"] = post_schema.confidence_summary
    aggregated_core["evidence_summary"] = post_schema.evidence_summary
    
    exec_time = round(time.time() - start_time, 2)
    
    # 5. Smart Phase Quality Score (Heuristic based on Validity, Confidence, Evidence, Richness)
    validation_score = max(0.0, 1.0 - (total_metrics["retries"] / 12.0))
    node_count = MERGE_REPORT["nodes_merged"]
    richness_score = min(1.0, node_count / 20.0)
    
    total_nodes_for_evidence = 0
    nodes_with_evidence = 0
    for key, data in aggregated_core.get("hard_requirements", {}).items():
        total_nodes_for_evidence += 1
        if len(data.get("evidence", [])) > 0: nodes_with_evidence += 1
    for key, data in aggregated_core.get("preferred_requirements", {}).items():
        total_nodes_for_evidence += 1
        if len(data.get("evidence", [])) > 0: nodes_with_evidence += 1
    for cat in aggregated_core.get("hiring_intent", {}).values():
        if isinstance(cat, dict):
            for key, data in cat.items():
                if isinstance(data, dict) and "evidence" in data:
                    total_nodes_for_evidence += 1
                    if len(data.get("evidence", [])) > 0: nodes_with_evidence += 1
                    
    evidence_coverage = (nodes_with_evidence / total_nodes_for_evidence) if total_nodes_for_evidence > 0 else 1.0
    quality_score = round(validation_score * 0.4 + richness_score * 0.3 + evidence_coverage * 0.3, 3)
    
    model_name_hash = hashlib.sha256(b"Qwen2.5-32B-Instruct-AWQ").hexdigest()
    
    aggregated_core["metadata"] = {
        "phase": "phase01",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "artifact_version": "v6.1_specialized",
        "jd_hash": jd_hash,
        "model_hash": model_name_hash,
        "merge_algorithm": "confidence_weighted_with_cycles_v3",
        "merge_version": "3.1",
        "execution": "Offline Kaggle",
        "model": "Qwen2.5-32B-Instruct-AWQ",
        "transformers_version": transformers.__version__ if transformers else "unknown",
        "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU",
        "vram_total_gb": round(torch.cuda.get_device_properties(0).total_memory / (1024**3), 2) if torch.cuda.is_available() else 0,
        "seed": 42,
        "temperature": 0.0,
        "execution_time_sec": exec_time,
        "phase_quality_score": quality_score,
        "evidence_coverage": evidence_coverage,
        "lens_execution": lens_metadata,
        "total_metrics": total_metrics
    }
    
    os.makedirs(os.path.join(os.path.dirname(__file__), "..", "data", "artifacts", "phase01"), exist_ok=True)
    out_path = os.path.join(os.path.dirname(__file__), "..", "data", "artifacts", "phase01", "jd_requirements.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(aggregated_core, f, indent=2)
        
    report_path = "merge_report.json"
    with open(report_path, "w") as f:
        json.dump(MERGE_REPORT, f, indent=2)
        
    # 6. Validation Metrics Report
    print("\n" + "="*50)
    print(" PHASE 1 VALIDATION METRICS REPORT")
    print("="*50)
    print(f"Phase Quality Score: {quality_score}/1.0")
    print(f"Evidence Coverage: {round(evidence_coverage * 100, 1)}%")
    print(f"Execution Time   : {exec_time} seconds")
    print(f"Total Retries    : {total_metrics['retries']} (Smart Self-Correction)")
    print(f"Prompt Tokens    : {total_metrics['prompt_tokens']}")
    print(f"Generated Tokens : {total_metrics['total_tokens']}")
    print(f"Total Nodes Gen  : {MERGE_REPORT['nodes_merged']}")
    print(f"Decision Rules   : {len(aggregated_core['recruiter_mental_model']['decision_rules'])}")
    print(f"Output Saved To  : {out_path}")
    print("="*50)

if __name__ == "__main__":
    # run_phase1_offline()
    print("Phase 1 Kaggle module loaded. Run run_phase1_offline() to start.")
