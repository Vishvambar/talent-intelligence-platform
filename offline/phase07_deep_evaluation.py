import os
import sys
import json
import time
import hashlib
import re
import gc
from datetime import datetime
import numpy as np
import polars as pl
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from scipy.stats import spearmanr, entropy
from collections import Counter

# ==============================================================================
# KAGGLE PATH CONFIGURATION
# ==============================================================================
MODEL_PATH = "/kaggle/input/qwen2.5-32b-instruct-awq/transformers/default/1" 

PHASE01_ARTIFACTS_DIR = "/kaggle/working/artifacts/phase01"
PHASE06_ARTIFACTS_DIR = "/kaggle/working/artifacts/phase06"
TEXTS_PATH = "/kaggle/input/redrob-candidate-data/candidate_texts.parquet"
OUTPUT_DIR = "/kaggle/working/phase07"

PAIRWISE_POOL_SIZE = 100
VALIDATION_SAMPLES = 50
MAX_EVIDENCE_TOKENS = 1200
MAX_RETRIES = 3
PRIORITIZATION_POOL_SIZE = 1000
MAX_EVIDENCE_TOKENS = 1000
MAX_RETRIES = 3

# Local Fallbacks
if not os.path.exists(PHASE06_ARTIFACTS_DIR):
    PHASE01_ARTIFACTS_DIR = "data/artifacts/phase01"
    PHASE06_ARTIFACTS_DIR = "data/artifacts/phase6"
    TEXTS_PATH = "data/artifacts/phase03/candidate_texts.parquet"
    OUTPUT_DIR = "phase_7_output"

os.makedirs(OUTPUT_DIR, exist_ok=True)

tokenizer = None
model = None

# ==============================================================================
# 1. INTELLIGENCE CARD BUILDER & CONSTRAINTS
# ==============================================================================
def load_jd_context():
    try:
        with open(os.path.join(PHASE01_ARTIFACTS_DIR, "jd_requirements.json"), "r") as f:
            jd = json.load(f)
    except Exception as e:
        print(f"Error loading JD: {e}. Using mock weights.")
        return {"technical_fit": 0.4, "behavioral_fit": 0.3, "business_fit": 0.2, "execution_fit": 0.1}, "=== RECRUITER CONSTRAINTS ===\nNone", {}
        
    hiring_intent = jd.get("hiring_intent", {})
    def sum_weights(p_dict): return sum(v.get("priority_weight", 0.0) for v in p_dict.values())
        
    w_tech = sum_weights(hiring_intent.get("technical_priorities", {}))
    w_behav = sum_weights(hiring_intent.get("behavioral_priorities", {}))
    w_biz = sum_weights(hiring_intent.get("business_priorities", {}))
    w_impl = sum_weights(hiring_intent.get("implicit_priorities", {}))
    
    total = w_tech + w_behav + w_biz + w_impl
    if total == 0: total = 1.0
    
    calibration_weights = {
        "technical_fit": w_tech / total,
        "behavioral_fit": w_behav / total,
        "business_fit": w_biz / total,
        "execution_fit": w_impl / total
    }
    
    rmm = jd.get("recruiter_mental_model", {})
    deal_breakers = rmm.get("deal_breakers", [])
    tradeoffs = rmm.get("tradeoffs", {})
    rules = rmm.get("decision_rules", [])
    philosophy = jd.get("hiring_philosophy", {})
    
    formatted_rules = []
    for r in rules:
        if isinstance(r, dict): formatted_rules.append(f"Prefer {r.get('preferred')} over {r.get('over')} ({r.get('confidence_reason')})")
        else: formatted_rules.append(str(r))
            
    formatted_tradeoffs = [f"{k}: {v}" for k, v in tradeoffs.items()]
    sorted_phil = sorted(philosophy.items(), key=lambda x: x[1], reverse=True)[:5]
    formatted_phil = [f"{k} ({v})" for k, v in sorted_phil]
    
    constraints_text = f"""=== RECRUITER CONSTRAINTS ===
Philosophy Drivers: {', '.join(formatted_phil)}
Deal Breakers:
{chr(10).join('- ' + db for db in deal_breakers)}
Tradeoffs:
{chr(10).join('- ' + t for t in formatted_tradeoffs)}
Decision Rules:
{chr(10).join('- ' + r for r in formatted_rules)}
"""
    
    eval_constants = jd.get("teacher_prompt_context", {}).get("evaluation_weights", {})
    feature_weights = {
        "integrity": eval_constants.get("integrity", 0.10),
        "evidence": eval_constants.get("evidence", 0.05),
        "graph": eval_constants.get("graph", 0.05),
        "technical_coverage": eval_constants.get("technical_coverage", 0.10),
        "dense_consensus": eval_constants.get("dense_consensus", 0.05)
    }
    
    return calibration_weights, constraints_text, feature_weights

def build_intelligence_card(c):
    exp = c.get("retrieval_explanation", {})
    if isinstance(exp, str):
        try: exp = json.loads(exp)
        except: exp = {}
        
    g_nodes = c.get('graph_node_count', 0)
    g_edges = c.get('graph_edge_count', 0)
    g_metric = (g_edges / max(g_nodes, 1)) + c.get('graph_size_proxy', 0)
        
    return f"""=== CANDIDATE INTELLIGENCE ===
Years Experience: {c.get('years_exp', 0)}
Avg Tenure: {c.get('avg_tenure', 0):.1f}
Technical Coverage: {c.get('technical_coverage', 0):.2f}
Business Coverage: {c.get('business_coverage', 0):.2f}
Integrity Score: {c.get('integrity_score', 0):.2f}
Evidence Confidence: {c.get('evidence_strength_score', 0):.2f}
Graph Richness: {g_metric:.1f}
Top Missing Skills: {', '.join(exp.get('missing_signals', ['None']))}
Retrieved By: {', '.join(exp.get('supporting_channels', []))}
Matched Priorities: {', '.join(exp.get('matched_priorities', []))}
"""

def safe_truncate_evidence(text, max_tokens):
    if not tokenizer: return text[:max_tokens*3]
    tokens = tokenizer.encode(text)
    if len(tokens) <= max_tokens: return text
    return tokenizer.decode(tokens[:max_tokens], skip_special_tokens=True) + "\n...[TRUNCATED FOR RELEVANCE]..."

# ==============================================================================
# 2. PROMPT TEMPLATES & SCHEMAS
# ==============================================================================
BASE_SYSTEM = "You are a Senior AI Engineering Recruiter. You output ONLY valid JSON. You never output markdown blocks or conversational text. DO NOT use <think> blocks. Output the JSON response immediately. You evaluate rigorously based on constraints."

SCHEMA_STR = """{
  "technical_fit": <0-100>,
  "technical_confidence": <0.0-1.0>,
  "behavioral_fit": <0-100>,
  "behavioral_confidence": <0.0-1.0>,
  "business_fit": <0-100>,
  "business_confidence": <0.0-1.0>,
  "execution_fit": <0-100>,
  "execution_confidence": <0.0-1.0>,
  "leadership_fit": <0-100>,
  "leadership_confidence": <0.0-1.0>,
  "risk_adjustment": <-50 to 0>,
  "missing_signals": ["<signal>"],
  "strongest_strengths": [{"strength": "<name>", "evidence": "<quote>"}],
  "strongest_concerns": [{"concern": "<name>", "evidence": "<quote>"}],
  "reasoning": "<1-2 sentence rationale>"
}"""

def prompt_variant(variant, constraints, card, evidence):
    base_prompt = ""
    if variant == "A":
        base_prompt = f"{constraints}\n{card}\n=== RELEVANT EVIDENCE ===\n{evidence}\n\nTask: Evaluate candidate fit against constraints. Penalize deal breakers in risk_adjustment."
    elif variant == "B":
        base_prompt = f"Review candidate against our hiring constraints.\n{constraints}\n\nSignals:\n{card}\n\nEvidence:\n{evidence}\n\nReturn valid JSON evaluating fit. Use risk_adjustment for anti-patterns."
    else: # C
        base_prompt = f"Target Role Evaluation.\n{constraints}\n{card}\n\nEvidence:\n{evidence}\n\nOutput JSON ONLY judging against Recruiter Constraints."
    return f"{base_prompt}\nSchema:\n{SCHEMA_STR}"

PAIRWISE_PROMPT = """You are evaluating two candidates for the same role. Compare their Intelligence Cards and specific strengths.
You MUST follow the Recruiter Constraints heavily.
{constraints}

Candidate A:
{card_a}

Candidate B:
{card_b}

Output exactly this JSON:
{{
  "winner": "<A or B>",
  "reason": "<1 sentence rationale>"
}}"""

# ==============================================================================
# 3. DYNAMIC BATCH & LLM ENGINE
# ==============================================================================
def init_model():
    global tokenizer, model
    if model is not None:
        print("\n✅ Model already loaded in VRAM (Reusing existing instance).")
        return
        
    print(f"\nLoading tokenizer from {MODEL_PATH}...")
    try:
        tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH)
        if tokenizer.pad_token is None: tokenizer.pad_token = tokenizer.eos_token
        tokenizer.padding_side = "left"
        
        print("Loading model into VRAM (AWQ)...")
        t0 = time.time()
        model = AutoModelForCausalLM.from_pretrained(MODEL_PATH, device_map="auto", low_cpu_mem_usage=True)
        print(f"✅ Model loaded in {time.time() - t0:.1f}s")
    except Exception as e:
        print(f"Model load error: {e}. Using mock engine for local testing.")

def dynamic_batch_finder(test_prompts):
    if not model: return 2
    best_batch, best_tp = 1, 0
    print("\n--- DYNAMIC BATCH SIZE FINDER ---")
    for bsz in [1, 2, 4, 8, 12, 16, 24, 32, 48, 64]:
        print(f"Testing Batch Size {bsz}...")
        torch.cuda.empty_cache(); gc.collect()
        try:
            t0 = time.time()
            _ = _generate_raw(test_prompts[:bsz], bsz)
            tp = len(test_prompts[:bsz]) / (time.time() - t0)
            print(f"  -> Success! Throughput: {tp:.2f} cands/sec")
            if tp > best_tp:
                best_tp = tp
                best_batch = bsz
        except torch.cuda.OutOfMemoryError:
            print(f"  -> OOM at batch size {bsz}. Stopping scale-up.")
            break
    print(f"✅ Optimal Batch Size: {best_batch}\n")
    return best_batch

def _generate_raw(prompts, batch_size):
    if not model: return ['{"technical_fit": 80, "technical_confidence": 0.9, "behavioral_fit": 75, "behavioral_confidence": 0.8, "business_fit": 70, "business_confidence": 0.8, "execution_fit": 85, "execution_confidence": 0.9, "leadership_fit": 60, "leadership_confidence": 0.7, "risk_adjustment": -5, "missing_signals": ["None"], "strongest_strengths": [{"strength": "Python", "evidence": "X"}], "strongest_concerns": [{"concern": "Tenure", "evidence": "Y"}], "reasoning": "Mock"}'] * len(prompts)
    
    results = []
    for i in range(0, len(prompts), batch_size):
        batch = prompts[i:i+batch_size]
        formatted = [tokenizer.apply_chat_template([{"role": "system", "content": BASE_SYSTEM}, {"role": "user", "content": p}], tokenize=False, add_generation_prompt=True) for p in batch]
        inputs = tokenizer(formatted, return_tensors="pt", padding=True, truncation=True, max_length=3000).to(model.device)
        
        with torch.no_grad():
            output_ids = model.generate(**inputs, max_new_tokens=1000, do_sample=False, pad_token_id=tokenizer.eos_token_id)
        
        prompt_len = inputs["input_ids"].shape[1]
        for j in range(len(batch)):
            results.append(tokenizer.decode(output_ids[j][prompt_len:], skip_special_tokens=True))
            
        del inputs, output_ids
        torch.cuda.empty_cache(); gc.collect()
    return results

def extract_json(text):
    text_clean = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    match = re.search(r"\{.*\}", text_clean, re.DOTALL)
    if match:
        try: return json.loads(match.group())
        except: pass
    return None

def generate_with_retries(prompts, batch_size):
    final_results = [None] * len(prompts)
    pending_indices = list(range(len(prompts)))
    
    for attempt in range(MAX_RETRIES):
        if not pending_indices: break
        if attempt > 0: print(f"  -> Retry loop {attempt} for {len(pending_indices)} failed parses...")
        
        current_prompts = [prompts[i] for i in pending_indices]
        raw_outputs = _generate_raw(current_prompts, batch_size)
        
        still_pending = []
        for idx, raw in zip(pending_indices, raw_outputs):
            parsed = extract_json(raw)
            if parsed:
                final_results[idx] = {"raw": raw, "json": parsed}
            else:
                still_pending.append(idx)
                if attempt == 0 and idx == pending_indices[0]:
                    print(f"\n[DEBUG] Raw failing output from Qwen:\n{raw}\n")
        pending_indices = still_pending
        
    return final_results

# ==============================================================================
# 4. VALIDATION GATE (STRICT SPEARMAN & ENTROPY)
# ==============================================================================
def validation_gate(candidates, constraints, best_batch):
    print("\n--- VALIDATION GATE (Strict 0.95 Spearman & Rationale Checks) ---")
    cands = candidates[:VALIDATION_SAMPLES]
    
    prompts_A, prompts_B, prompts_C = [], [], []
    for c in cands:
        card = build_intelligence_card(c)
        evid = safe_truncate_evidence(c.get("retrieval_text", ""), MAX_EVIDENCE_TOKENS)
        prompts_A.append(prompt_variant("A", constraints, card, evid))
        prompts_B.append(prompt_variant("B", constraints, card, evid))
        prompts_C.append(prompt_variant("C", constraints, card, evid))
        
    res_A = generate_with_retries(prompts_A, best_batch)
    res_B = generate_with_retries(prompts_B, best_batch)
    res_C = generate_with_retries(prompts_C, best_batch)
    
    tech_A, tech_B, tech_C, rationales = [], [], [], []
    for a, b, c_res in zip(res_A, res_B, res_C):
        if a and b and c_res and "technical_fit" in a["json"] and "technical_fit" in b["json"] and "technical_fit" in c_res["json"]:
            tech_A.append(a["json"]["technical_fit"])
            tech_B.append(b["json"]["technical_fit"])
            tech_C.append(c_res["json"]["technical_fit"])
            rationales.append(a["json"].get("reasoning", ""))
            
    if len(tech_A) < 10:
        print("❌ VALIDATION FAILED: Too many JSON extraction failures.")
        return False
        
    s_ab, _ = spearmanr(tech_A, tech_B)
    s_ac, _ = spearmanr(tech_A, tech_C)
    s_bc, _ = spearmanr(tech_B, tech_C)
    
    ent_A = entropy(np.bincount(np.array(tech_A).astype(int))[np.bincount(np.array(tech_A).astype(int)) > 0] / len(tech_A))
    
    counts = Counter(rationales)
    max_dup = counts.most_common(1)[0][1] if rationales else 0
    dup_percent = (max_dup / len(rationales)) * 100 if rationales else 100
    
    print(f"Spearman A-B: {s_ab:.3f} | A-C: {s_ac:.3f} | B-C: {s_bc:.3f}")
    print(f"Score Entropy: {ent_A:.3f} | Max Duplicate Reasoning: {dup_percent:.1f}%")
    
    if s_ab >= 0.95 and s_ac >= 0.95 and dup_percent < 30.0:
        print("✅ VALIDATION PASSED: Teacher is highly robust and diverse.")
        return True
    else:
        print("⚠️ CRITICAL WARNING: Teacher drift or template collapse detected. Aborting run!")
        sys.exit(1)

# ==============================================================================
# 5. PHASE 7B & 7C: CALIBRATION AND PAIRWISE RANKING
# ==============================================================================

def merge_sort_llm(bucket, constraints):
    if len(bucket) <= 1:
        return bucket
    mid = len(bucket) // 2
    left = merge_sort_llm(bucket[:mid], constraints)
    right = merge_sort_llm(bucket[mid:], constraints)
    
    result = []
    i, j = 0, 0
    while i < len(left) and j < len(right):
        eval_left = json.loads(left[i].get('recruiter_evaluation', '{}'))
        eval_right = json.loads(right[j].get('recruiter_evaluation', '{}'))
        
        p_prompt = PAIRWISE_PROMPT.format(
            constraints=constraints,
            card_a=build_intelligence_card(left[i]) + f"\nStrengths: {eval_left.get('strongest_strengths',[])}",
            card_b=build_intelligence_card(right[j]) + f"\nStrengths: {eval_right.get('strongest_strengths',[])}"
        )
        
        res = _generate_raw([p_prompt], 1)[0]
        j_res = extract_json(res)
        
        # A wins => A goes first
        if j_res and j_res.get("winner") == "B":
            result.append(right[j])
            j += 1
        else:
            result.append(left[i])
            i += 1
            
    result.extend(left[i:])
    result.extend(right[j:])
    return result

def normalize(series):
    arr = np.array(series, dtype=float)
    _min, _max = np.nanmin(arr), np.nanmax(arr)
    if _max == _min: return np.zeros_like(arr)
    return (arr - _min) / (_max - _min)

def phase6_5_prioritization(candidates, calib_weights):
    print(f"\n--- PHASE 6.5: DETERMINISTIC CANDIDATE PRIORITIZATION (Top {PRIORITIZATION_POOL_SIZE}) ---")
    
    rrf = [c.get("rrf_score", 0) for c in candidates]
    d_rrf = [c.get("dense_rrf_score", 0) for c in candidates]
    r_votes = [c.get("retrieval_votes", 0) for c in candidates]
    r_div = [c.get("retrieval_diversity", 0) for c in candidates]
    
    n_rrf = normalize(rrf)
    n_drrf = normalize(d_rrf)
    n_rvotes = normalize(r_votes)
    n_rdiv = normalize(r_div)
    
    prioritized_pool, eliminated_pool = [], []
    
    w_tech, w_behav = calib_weights.get("technical_fit", 0.4), calib_weights.get("behavioral_fit", 0.3)
    w_biz, w_impl = calib_weights.get("business_fit", 0.2), calib_weights.get("execution_fit", 0.1)
    
    for i, c in enumerate(candidates):
        retrieval_strength = (0.40 * n_rrf[i]) + (0.25 * n_drrf[i]) + (0.20 * n_rvotes[i]) + (0.15 * n_rdiv[i])
        
        comp_ret = 0.35 * retrieval_strength
        comp_tech = w_tech * c.get("technical_coverage", 0)
        comp_behav = w_behav * c.get("behavioral_coverage", 0)
        comp_biz = w_biz * c.get("business_coverage", 0)
        comp_impl = w_impl * c.get("implicit_coverage", 0)
        comp_evid = 0.15 * c.get("evidence_strength_score", 0)
        comp_integ = 0.10 * c.get("integrity_score", 0)
        comp_dens = 0.10 * c.get("dense_consensus_score", 0)
        
        priority_score = comp_ret + comp_tech + comp_behav + comp_biz + comp_impl + comp_evid + comp_integ + comp_dens
        
        c["priority_score"] = float(priority_score)
        c["retrieval_strength"] = float(retrieval_strength)
        c["priority_breakdown"] = {
            "retrieval": float(comp_ret), "technical": float(comp_tech), "behavioral": float(comp_behav),
            "business": float(comp_biz), "implicit": float(comp_impl), "evidence": float(comp_evid),
            "integrity": float(comp_integ), "dense_consensus": float(comp_dens)
        }
        
        if retrieval_strength < 0.15:
            c["elimination_reason"] = "Low retrieval strength (< 0.15)"
            eliminated_pool.append(c)
        else:
            prioritized_pool.append(c)
            
    prioritized_pool.sort(key=lambda x: x["priority_score"], reverse=True)
    
    for rank, c in enumerate(prioritized_pool):
        c["priority_rank"] = rank + 1
        if rank >= PRIORITIZATION_POOL_SIZE:
            c["elimination_reason"] = f"Ranked {rank+1} (Below Top 1000 cutoff)"
            eliminated_pool.append(c)
            
    final_pool = prioritized_pool[:PRIORITIZATION_POOL_SIZE]
    
    audit = {
        "input_count": len(candidates),
        "output_count": len(final_pool),
        "eliminated_count": len(eliminated_pool),
        "mean_priority_score": float(np.mean([c["priority_score"] for c in final_pool])),
        "top_1000_threshold": final_pool[-1]["priority_score"] if final_pool else 0
    }
    with open(os.path.join(OUTPUT_DIR, "phase06_5_prioritization.json"), "w") as f: json.dump(audit, f, indent=2)
        
    try:
        pl.DataFrame([{"candidate_id": c.get("candidate_id"), "priority_score": c.get("priority_score"), "retrieval_strength": c.get("retrieval_strength"), "elimination_reason": c.get("elimination_reason")} for c in eliminated_pool]).write_csv(os.path.join(OUTPUT_DIR, "phase06_5_eliminations.csv"))
    except: pass
        
    return final_pool

def execute_phase7():
    print("=== REDROB PHASE 7: RECRUITER DECISION ENGINE ===")
    
    calib_weights, constraints, feature_weights = load_jd_context()
    df_pool = pl.read_parquet(os.path.join(PHASE06_ARTIFACTS_DIR, "retrieval_pool.parquet"))
    df_texts = pl.read_parquet(TEXTS_PATH)
    candidates = df_pool.join(df_texts, on="candidate_id", how="left").to_dicts()
    
    candidates = phase6_5_prioritization(candidates, calib_weights)
    
    init_model()
    
    test_prompts = [prompt_variant("A", constraints, build_intelligence_card(c), safe_truncate_evidence(c.get("retrieval_text", ""), MAX_EVIDENCE_TOKENS)) for c in candidates[:64]]
    best_batch = dynamic_batch_finder(test_prompts)
    
    validation_gate(candidates, constraints, best_batch)
    
    # PHASE 7A: REASONING
    print("\n--- PHASE 7A: RECRUITER REASONING ---")
    eval_prompts = [prompt_variant("A", constraints, build_intelligence_card(c), safe_truncate_evidence(c.get("retrieval_text", ""), MAX_EVIDENCE_TOKENS)) for c in candidates]
    
    start_t = time.time()
    results = generate_with_retries(eval_prompts, best_batch)
    print(f"Reasoning completed in {time.time() - start_t:.1f}s")
    
    # PHASE 7B: CALIBRATION
    print("\n--- PHASE 7B: CALIBRATION (Holistic Feature Fusion) ---")
    final_output, valid_evals = [], []
    
    for c, prompt, res in zip(candidates, eval_prompts, results):
        if not res: continue
        jd = res["json"]
        
        t_tech = jd.get("technical_fit", 0) * jd.get("technical_confidence", 1.0)
        t_behav = jd.get("behavioral_fit", 0) * jd.get("behavioral_confidence", 1.0)
        t_biz = jd.get("business_fit", 0) * jd.get("business_confidence", 1.0)
        t_exec = jd.get("execution_fit", 0) * jd.get("execution_confidence", 1.0)
        risk = jd.get("risk_adjustment", 0)
        
        integ = c.get("integrity_score", 0) * 100
        evid = c.get("evidence_strength_score", 0) * 100
        g_nodes = c.get('graph_node_count', 0)
        g_edges = c.get('graph_edge_count', 0)
        gd = ((g_edges / max(g_nodes, 1)) + c.get('graph_size_proxy', 0)) * 100
        
        t_cov = c.get("technical_coverage", 0) * 100
        d_con = c.get("dense_consensus_score", 0) * 100
        
        calibrated_score = (
            (calib_weights["technical_fit"] * t_tech) +
            (calib_weights["behavioral_fit"] * t_behav) +
            (calib_weights["business_fit"] * t_biz) +
            (calib_weights["execution_fit"] * t_exec) +
            (feature_weights["integrity"] * integ) + 
            (feature_weights["evidence"] * evid) + 
            (feature_weights["graph"] * gd) +
            (feature_weights["technical_coverage"] * t_cov) + 
            (feature_weights["dense_consensus"] * d_con)
        ) + risk
        
        reasoning_hash = hashlib.sha256(f"{prompt}{jd.get('reasoning','')}{json.dumps(jd)}".encode()).hexdigest()
        
        row = c.copy()
        row["calibrated_score"] = float(calibrated_score)
        row["recruiter_evaluation"] = json.dumps(jd)
        row["teacher_reasoning_hash"] = reasoning_hash
        final_output.append(row)
        valid_evals.append(jd)
        
    df_calib = pl.DataFrame(final_output).sort("calibrated_score", descending=True)
    df_calib.write_parquet(os.path.join(OUTPUT_DIR, "calibrated_labels_full.parquet"))
    
    # Calibration Audit
    audit = {
        "mean_technical": float(np.mean([e.get("technical_fit",0) for e in valid_evals])),
        "std_technical": float(np.std([e.get("technical_fit",0) for e in valid_evals])),
        "mean_business": float(np.mean([e.get("business_fit",0) for e in valid_evals])),
        "mean_risk": float(np.mean([e.get("risk_adjustment",0) for e in valid_evals])),
        "mean_technical_confidence": float(np.mean([e.get("technical_confidence",0) for e in valid_evals]))
    }
    with open(os.path.join(OUTPUT_DIR, "phase07_calibration.json"), "w") as f: json.dump(audit, f, indent=2)
        
    # PHASE 7C: PAIRWISE RANKING (Tournament MergeSort)
    print(f"\n--- PHASE 7C: FINAL RANKING (Global Pairwise MergeSort Top {PAIRWISE_POOL_SIZE}) ---")
    top_cands = df_calib.head(PAIRWISE_POOL_SIZE).to_dicts()
    
    if not model or len(top_cands) < 2:
        final_ranked_pool = top_cands
    else:
        print(f"  -> Running Global MergeSort on Top {len(top_cands)} candidates (approx {int(len(top_cands) * np.log2(len(top_cands)))} comparisons)...")
        final_ranked_pool = merge_sort_llm(top_cands, constraints)
        
    for i, c in enumerate(final_ranked_pool): c["final_rank"] = i + 1
        
    df_final = pl.DataFrame(final_ranked_pool)
    df_final.write_parquet(os.path.join(OUTPUT_DIR, "redrob_final_ranking.parquet"))
    
    try:
        df_report = df_final.select(["final_rank", "candidate_id", "calibrated_score", "technical_coverage", "evidence_strength_score", "recruiter_evaluation", "teacher_reasoning_hash"])
        df_report.write_csv(os.path.join(OUTPUT_DIR, "redrob_top_100_report.csv"))
    except: pass
    
    print("\n✅ Phase 7 Complete! Final Ranked Artifacts saved.")

if __name__ == "__main__":
    execute_phase7()
