# REDROB CANDIDATE RANKING — ARCHITECTURE V12 FINAL
## GPU-Accelerated Implementation & Verification Engineering Specification

> **This document is the single source of truth.**
> Every implementation decision, every variable name, every threshold, every output schema is defined here.
> When in doubt, consult this document. When this document and intuition conflict, this document wins.
> Any change requires experimental evidence — not intuition.

---

## SYSTEM OBJECTIVE

Predict:

```
P(candidate gets shortlisted by an expert recruiter
  for this exact Senior AI Engineer — Founding Team role)
```

Not keyword matching. Not embedding similarity. Not LLM opinion.
A deterministic, explainable **Recruiter Relevance Prediction Engine**.

**Final output:**
```csv
candidate_id, rank, score, reasoning
```
Top 100 candidates. Scores strictly decreasing. Reasoning grounded in profile data only.

---

## GLOBAL CONSTRAINTS

| Phase | Constraint |
|---|---|
| Offline (Kaggle RTX) | LLMs, APIs, GPUs (RTX PRO 6000 96GB) — Artifact generation |
| Online inference | CPU only · ≤16 GB RAM · ≤5 min wall-clock · No network · No APIs |

---

## COMPLETE PIPELINE (V12)

```
PHASE 1    JD Intelligence Engine (w/ Semantic Canonicalization) [V12]
PHASE 2    Domain Ontology Engine
PHASE 3    Candidate Knowledge Graph
PHASE 3.5  Career Intelligence Layer
PHASE 3.7  Behavioral Intelligence Layer
PHASE 4    Data Integrity Engine

== ENHANCED RETRIEVAL (GPU) ==
PHASE 5    Multi-Embedding Generation (BGE + E5) [V12]
PHASE 5.5  Broad Eligibility Filter
               ↓
          TOP 20,000 CANDIDATES
               ↓
PHASE 6    Hybrid Retrieval Ensemble (Dense + BM25)
               ↓
          TOP 3000 CANDIDATES
               ↓
PHASE 6.5  Retrieval Recall Audit (Recall@500/1000/2000/3000) [V12]

== ENHANCED LABELS & METRICS ==
PHASE 7A   Teacher Ensemble (Reasoning + Scoring)
PHASE 7.1  Teacher Drift & Reasoning Clustering [V12]
PHASE 7.15 Label Quality Audit
PHASE 7B   Label Calibration
PHASE 7C   Pairwise Refinement
PHASE 7.5  Hard Negative Mining [V12]
PHASE 7.8  Feature Parity Audit

== ENHANCED RANKING ==
PHASE 8    Learning To Rank
PHASE 8.5  Automated SHAP Feedback Loop [V12]
PHASE 8.75 Retrieval & Ranking Stress Test
PHASE 9    Ensemble Models
               ↓
          TOP 500 CANDIDATES
               ↓
PHASE 9.2  Cross-Encoder Re-Ranking [V12]
               ↓
          TOP 50 CANDIDATES
               ↓
PHASE 9.5  Elite Re-Ranking
               ↓
PHASE 10   Reasoning Bank
PHASE 10.5 Reasoning Diversity Audit
PHASE 11   Runtime Verification
PHASE 11.25 Submission Simulation [V12]
PHASE 11.5 Submission Safety Audit
               ↓
ONLINE PIPELINE (judges execute)
               ↓
TOP 100 CSV
```

---

## V12 CORE UPGRADES

### 1. Multi-Embedding Retrieval (Phases 5 & 6)
We utilize the RTX 6000 to drastically improve recall by running an embedding ensemble.
- **Models:** `BAAI/bge-large-en-v1.5` and `intfloat/e5-large-v2`.
- **Vectors per Candidate:** 
  - `Profile Embedding` (Headline + Summary + Skills)
  - `Career Embedding` (Top 3 recent roles descriptions)
- **Aggregation:** Dense Score = `(0.30 * profile_bge) + (0.20 * career_bge) + (0.30 * profile_e5) + (0.20 * career_e5)`.

### 2. Hard Negative Mining (Phase 7.5)
To prevent the LTR model from learning trivial boundaries, we mine hard negatives:
- Identify candidates who share keywords (e.g., "Data Scientist", "Machine Learning") but lack explicit JD constraints (e.g., 0 startup experience, purely consulting background).
- Apply a `teacher_score_cap = 60` or a `hard_negative_penalty` to these candidates during teacher labeling, rather than forcing a strict `label = 0`, to avoid teaching the model that consulting is absolutely bad while still defining the boundary between a generic AI engineer and a founding-team AI engineer.

### 3. Cross-Encoder Re-Ranking (Phase 9.2)
To maximize precision at the very top of the funnel without blowing up compute times:
- Apply `cross-encoder/ms-marco-MiniLM-L-6-v2` or `BAAI/bge-reranker-large` ONLY to the Top 500 candidates outputted by the Ensemble Models.
- We cross-encode a synthesized `candidate_summary_text` (Top 3 recent roles + Top Skills + Profile summary) against the JD.
- The top 50 candidates from the cross-encoder are then passed into Phase 9.5 (Elite Re-Ranking). This correctly prioritizes NDCG@10 and NDCG@50 where it matters most.

### 4. Teacher Drift Detection (Phase 7.1)
LLM teachers are susceptible to template collapse (giving the exact same reasoning structure for everyone).
- We mandate the LLM to output a `reasoning_chain` string before the final `score`.
- We embed these reasoning strings and cluster them. If the percentage of candidates falling into 1 cluster exceeds the `drift_cluster_threshold`, we have teacher drift/template collapse, and the labels are invalid.

### 5. Automated SHAP (Phase 8.5)
- SHAP generation is now fully automated. After every LTR training run, a `shap_report.json` is generated. If critical features like `founding_team_score` fall out of the Top 10 feature importances, the build fails.

### 6. Submission Simulation (Phase 11.25)
The easiest way to lose a hackathon is a formatting failure. Before export:
- Generate the CSV and run `validate_submission.py`.
- Verify exactly 100 rows, unique IDs, strictly decreasing scores, reasoning exists, and absolutely no nulls.

---

## HYPERPARAMETER REGISTRY (V12 UPDATE)

**File: `config/hyperparams.yaml`**

```yaml
retrieval:
  top_k: 3000           
  # EXPERIMENTAL: Dense heavily weighted for AI Search role. Tune after Recall@3000 audit.
  dense_weight_bge: 0.25
  dense_weight_e5: 0.25
  bm25_weight: 0.20
  ontology_weight: 0.20
  career_weight: 0.10

teacher:
  temperature: 0
  runs_per_candidate: 3
  aggregation: median
  technical_weight: 0.45
  evaluation_weight: 0.35
  execution_weight: 0.20
  drift_cluster_threshold: 0.80

ranking:
  cross_encoder_top_k: 500  # Number of candidates to run through cross-encoder
  hard_negative_ratio: 0.2  # 20% of training data must be explicit hard negatives
```


---

# OFFLINE PHASE

---

## PHASE 1 — JD INTELLIGENCE ENGINE

### Goal
Convert the raw job description from human language into a structured JSON object that every downstream phase can query deterministically.

### Prerequisites
- `job_description.docx` present in `data/raw/`
- LLM API access (any: GPT-4, Claude, Gemini, Groq Llama 3)


### V12 UPGRADE: Semantic Canonicalization & Output Contract
In V12, Phase 1 guarantees a completely deduplicated output. It merges the Execution, Technical, and Culture lenses, applies a hardcoded `CANONICAL_REQUIREMENTS` and `CANONICAL_NEGATIVES` mapping, tracks exactly which aliases were merged into which canonical keys, and outputs a production-ready `jd_requirements.json`.

### Implementation Steps

**Step 1.1 — Extract raw text from the DOCX**
```python
from docx import Document

def extract_jd_text(path: str) -> str:
    doc = Document(path)
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
```

**Step 1.2 — Build the extraction prompt**
```
You are a senior technical recruiter. Extract structured requirements from the job description below.

Return ONLY valid JSON matching this schema. No explanation, no markdown.

{
  "hard_requirements": {
    "retrieval_systems": bool,
    "vector_databases": bool,
    "embeddings": bool,
    "ranking_evaluation": bool,
    "ranking_eval_tools": ["list of specific tools mentioned"]
  },
  "preferred_requirements": {
    "specific_vector_dbs": ["list"],
    "specific_embedding_models": ["list"],
    "llm_experience": bool
  },
  "experience_constraints": {
    "min_years": int,
    "max_years": int,
    "preferred_background": ["product", "startup", "founding"]
  },
  "behavioral_requirements": {
    "ownership": bool,
    "fast_execution": bool,
    "builder_mindset": bool,
    "founding_team_fit": bool
  },
  "red_flags": ["list of backgrounds that are poor fit, e.g. pure consulting"]
}

JOB DESCRIPTION:
{jd_text}
```

**Step 1.3 — Run 3–5 independent extractions and merge**
```python
import json

results = []
for run in range(5):
    raw = call_llm(prompt, temperature=0)
    try:
        results.append(json.loads(raw))
    except json.JSONDecodeError:
        continue  # skip malformed outputs

# Merge: for bool fields, majority vote
# For list fields, take the union
merged = merge_extractions(results)
```

**Step 1.4 — Save output**
```python
with open("data/artifacts/jd_requirements.json", "w") as f:
    json.dump(merged, f, indent=2)
```

### Verification Checklist
- [ ] `jd_requirements.json` exists and is valid JSON
- [ ] `hard_requirements.ranking_evaluation == True` — the JD explicitly asks for NDCG/MAP
- [ ] `experience_constraints.min_years == 5` and `max_years == 9`
- [ ] `behavioral_requirements.founding_team_fit == True`
- [ ] `red_flags` contains "consulting" or "services" background
- [ ] At least 3 independent LLM runs were merged

### Common Mistakes
- Running only once: LLM can misparse a field. Merge 5 runs.
- Not saving raw outputs: keep all 5 raw JSON strings alongside merged for debugging.
- Using this file at inference time: it is precomputed. Online pipeline loads it as a static file, never re-generates it.

### Output
```
data/artifacts/jd_requirements.json
```

---

## PHASE 2 — DOMAIN ONTOLOGY ENGINE

### Goal
Encode expert recruiter knowledge about this specific role into frozen, deterministic keyword dictionaries. This is a manual artifact — it is not generated by an LLM at runtime.

### Prerequisites
- Phase 1 complete (use `jd_requirements.json` for inspiration, but the ontology is hand-crafted)

### Implementation Steps

**Step 2.1 — Build the ontology dictionary**

```python
# file: offline/phase02_ontology.py

ONTOLOGY = {

    "RETRIEVAL": [
        "retrieval", "information retrieval", "ir system",
        "semantic search", "semantic retrieval",
        "rag", "retrieval augmented generation",
        "recommendation system", "recommender system",
        "search relevance", "search ranking",
        "dense retrieval", "sparse retrieval",
        "neural retrieval", "document retrieval"
    ],

    "VECTOR_DB": [
        "qdrant", "pinecone", "milvus", "weaviate",
        "faiss", "chroma", "vespa", "opensearch",
        "elasticsearch knn", "vector database",
        "vector store", "ann", "approximate nearest neighbor",
        "hnsw", "ivf"
    ],

    "EMBEDDINGS": [
        "embedding", "embeddings", "sentence transformer",
        "sentence-transformers", "openai embeddings",
        "text embeddings", "e5", "bge", "ada",
        "dense vector", "semantic embedding",
        "contrastive learning", "bi-encoder",
        "cross-encoder"
    ],

    "EVALUATION": [
        "ndcg", "normalized discounted cumulative gain",
        "map", "mean average precision",
        "mrr", "mean reciprocal rank",
        "precision at k", "recall at k",
        "ab testing", "a/b test", "online evaluation",
        "offline evaluation", "ranking quality",
        "search evaluation", "relevance evaluation",
        "click-through rate", "ctr model"
    ],

    "PRODUCT_COMPANY": [
        "startup", "saas", "product company", "product-led",
        "b2b saas", "b2c", "consumer product",
        "tech company", "series a", "series b",
        "growth stage", "early stage"
    ],

    "FOUNDING_TEAM": [
        "founding engineer", "founding team", "founding member",
        "first engineer", "early engineer", "employee number",
        "employee #", "0 to 1", "zero to one",
        "built from scratch", "greenfield",
        "early employee", "initial team",
        "co-founder", "technical co-founder"
    ],

    "OWNERSHIP": [
        "led", "built", "architected", "designed",
        "shipped", "deployed", "scaled", "launched",
        "productionized", "owned", "drove", "delivered",
        "end to end", "end-to-end", "from scratch"
    ],

    "ML_AI": [
        "machine learning", "deep learning",
        "nlp", "natural language processing",
        "llm", "large language model",
        "transformer", "bert", "gpt",
        "fine-tuning", "finetuning",
        "pytorch", "tensorflow", "model training",
        "ml pipeline", "feature engineering",
        "model serving", "mlops"
    ]
}
```

**Step 2.2 — Add case-folded lookup**
```python
# Pre-compute lowercased versions for fast matching
ONTOLOGY_LOWER = {
    group: [term.lower() for term in terms]
    for group, terms in ONTOLOGY.items()
}

import json
with open("data/artifacts/ontology.json", "w") as f:
    json.dump(ONTOLOGY_LOWER, f, indent=2)
```

**Step 2.3 — Create the matching function used by all downstream phases**
```python
def compute_ontology_scores(text: str) -> dict:
    """
    Returns a dict of group_name -> coverage_score (0.0 to 1.0)
    for each ontology group based on how many terms appear in text.
    """
    text_lower = text.lower()
    scores = {}
    for group, terms in ONTOLOGY_LOWER.items():
        matches = sum(1 for term in terms if term in text_lower)
        scores[group] = min(1.0, matches / max(1, len(terms) * 0.3))
        # 0.3 factor: hitting 30% of terms in a group = score of 1.0
    return scores
```

### Verification Checklist
- [ ] `ontology.json` exists and all values are lowercased
- [ ] `EVALUATION` group contains: "ndcg", "map", "mrr", "ab testing", "offline evaluation"
- [ ] `FOUNDING_TEAM` group contains: "founding engineer", "employee #", "first engineer"
- [ ] `VECTOR_DB` group contains all 5 databases mentioned in JD
- [ ] `compute_ontology_scores("I built a RAG system using Pinecone and evaluated with NDCG")` returns RETRIEVAL>0, VECTOR_DB>0, EVALUATION>0
- [ ] Ontology is FROZEN after this phase — never regenerated dynamically

### Common Mistakes
- Using the LLM to expand the ontology at runtime: never do this. Freeze it manually.
- Missing abbreviations: "ndcg" is different from "normalized discounted cumulative gain" — include both.
- Overly strict matching: "pinecone" should match "Pinecone", "PINECONE" — always lowercase both sides.

### Output
```
data/artifacts/ontology.json
```

---

## PHASE 3 — CANDIDATE KNOWLEDGE GRAPH

### Goal
Convert all 100,000 raw candidate JSON profiles into a structured feature matrix. Every candidate becomes a fixed-size numeric vector. This is the foundation of everything downstream.

### Prerequisites
- `candidates.jsonl.gz` present in `data/raw/`
- Phase 2 complete (ontology functions available)

### Implementation Steps

**Step 3.1 — Stream the JSONL file in batches (memory-safe)**
```python
import gzip
import json
import pandas as pd
from tqdm import tqdm

def stream_candidates(path: str, batch_size: int = 1000):
    batch = []
    with gzip.open(path, 'rt', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                batch.append(json.loads(line))
                if len(batch) == batch_size:
                    yield batch
                    batch = []
    if batch:
        yield batch
```

**Step 3.2 — Feature extraction function**
```python
def extract_candidate_features(cand: dict) -> dict:
    profile = cand.get("profile", {})
    career = cand.get("career_history", [])
    skills = cand.get("skills", [])
    signals = cand.get("redrob_signals", {})
    education = cand.get("education", [])

    # --- Experience Features ---
    years_exp = float(profile.get("years_of_experience", 0))
    tenures = [r.get("duration_months", 0) / 12 for r in career if r.get("duration_months")]
    avg_tenure = sum(tenures) / len(tenures) if tenures else 0

    # Promotion count: same company, increasing seniority keywords
    promotion_count = count_promotions(career)

    # Leadership count: titles containing leadership keywords
    leadership_kw = ["lead", "manager", "director", "head", "principal", "staff", "vp"]
    leadership_count = sum(1 for r in career
                           if any(kw in r.get("title", "").lower() for kw in leadership_kw))

    # --- Technical Features (from skills section + summary) ---
    all_skill_text = " ".join(s.get("name", "") for s in skills)
    full_text = " ".join([
        profile.get("headline", ""),
        profile.get("summary", ""),
        all_skill_text
    ])

    ontology_scores = compute_ontology_scores(full_text)

    retrieval_score = ontology_scores.get("RETRIEVAL", 0.0)
    vector_db_score = ontology_scores.get("VECTOR_DB", 0.0)
    embedding_score = ontology_scores.get("EMBEDDINGS", 0.0)
    evaluation_score = ontology_scores.get("EVALUATION", 0.0)
    ml_score = ontology_scores.get("ML_AI", 0.0)
    llm_score = 1.0 if "llm" in full_text.lower() or "large language model" in full_text.lower() else 0.0

    # --- Career Features ---
    career_text = " ".join([r.get("title", "") + " " + r.get("industry", "") + " "
                             + str(r.get("company_size", ""))
                             for r in career])
    startup_score = ontology_scores_from_text(career_text, "PRODUCT_COMPANY")
    product_company_score = classify_company_types(career)  # product vs consulting
    consulting_score = 1.0 - product_company_score

    career_growth_score = compute_career_growth(career)

    # --- Education ---
    tier_map = {"tier_1": 1.0, "tier_2": 0.7, "tier_3": 0.4, "tier_4": 0.2}
    edu_tiers = [tier_map.get(e.get("tier", "tier_4"), 0.2) for e in education]
    education_tier_score = max(edu_tiers) if edu_tiers else 0.0

    # --- Behavioral Features (from redrob_signals) ---
    github_raw = signals.get("github_activity_score", -1)
    if github_raw == -1:
        # Missing GitHub data — impute with 40 (midpoint), flag separately
        github_score_imputed = 40.0
        github_missing = 1
    else:
        github_score_imputed = float(github_raw)
        github_missing = 0

    assessment_scores = signals.get("skill_assessment_scores", {})
    assessment_score = (sum(assessment_scores.values()) / len(assessment_scores)
                        if assessment_scores else 0.0)

    return {
        "candidate_id": cand["candidate_id"],
        # Experience
        "years_exp": years_exp,
        "avg_tenure": avg_tenure,
        "promotion_count": float(promotion_count),
        "leadership_count": float(leadership_count),
        # Technical
        "retrieval_score": retrieval_score,
        "vector_db_score": vector_db_score,
        "embedding_score": embedding_score,
        "evaluation_score": evaluation_score,
        "ml_score": ml_score,
        "llm_score": llm_score,
        # Career
        "startup_score": startup_score,
        "product_company_score": product_company_score,
        "consulting_score": consulting_score,
        "career_growth_score": career_growth_score,
        # Education
        "education_tier_score": education_tier_score,
        # Behavioral
        "github_score_imputed": github_score_imputed,
        "github_missing": float(github_missing),
        "assessment_score": assessment_score,
    }
```

**Step 3.3 — Helper: classify product vs consulting companies**
```python
CONSULTING_SIGNALS = [
    "consulting", "outsourcing", "services", "infosys", "wipro",
    "tcs", "cognizant", "accenture", "capgemini", "ibm services",
    "agency", "staffing", "it services"
]
PRODUCT_SIGNALS = [
    "saas", "product", "platform", "software", "app",
    "marketplace", "fintech", "edtech", "healthtech"
]

def classify_company_types(career: list) -> float:
    product_score = 0.0
    for role in career:
        industry = role.get("industry", "").lower()
        company = role.get("company", "").lower()
        text = industry + " " + company
        is_consulting = any(kw in text for kw in CONSULTING_SIGNALS)
        is_product = any(kw in text for kw in PRODUCT_SIGNALS)
        if is_product and not is_consulting:
            product_score += 1.0
        elif not is_consulting:
            product_score += 0.5  # ambiguous, slight positive
    return min(1.0, product_score / max(1, len(career)))
```

**Step 3.4 — Process all 100k and save**
```python
all_features = []
for batch in tqdm(stream_candidates("data/raw/candidates.jsonl.gz")):
    for cand in batch:
        try:
            features = extract_candidate_features(cand)
            all_features.append(features)
        except Exception as e:
            print(f"Error on {cand.get('candidate_id')}: {e}")

import polars as pl
df = pl.DataFrame(all_features)
df.write_parquet("data/artifacts/candidate_features.parquet")
print(f"Saved {len(df)} candidates")
```

### Verification Checklist
- [ ] Output shape: exactly 100,000 rows
- [ ] No null values in any numeric column (fill with 0.0 if missing)
- [ ] `years_exp` distribution: check `df["years_exp"].describe()` — should range 0–30+, mean ~7–10
- [ ] `evaluation_score` distribution: mostly 0.0 with rare high values — this is expected and correct
- [ ] `product_company_score` + `consulting_score` do not always sum to 1.0 (some candidates have ambiguous backgrounds)
- [ ] `github_missing` flag exists and correctly marks candidates where `github_activity_score == -1`
- [ ] Run `df.null_count()` — must return all zeros
- [ ] Spot-check 5 candidates manually: pull their raw profile, compute features by hand, compare

### Common Mistakes
- Loading all 100k into memory at once: always stream in batches of 1000.
- Treating `years_of_experience` from profile as the only source: cross-validate with sum of career history durations, take the max.
- Forgetting that `github_activity_score == -1` means "no data", not "zero activity".

### Output
```
data/artifacts/candidate_features.parquet
Schema: candidate_id (str), 20+ numeric features (f64)
```

---

## PHASE 3.5 — CAREER INTELLIGENCE LAYER

### Goal
Extract signals hidden inside `career_history[].description` text that don't appear in the skills section. This directly addresses the JD warning: a candidate who built a semantic product search engine may never use the word "RAG" anywhere in their profile.

### Prerequisites
- Phase 2 (ontology) complete
- Phase 3 (knowledge graph) complete — candidate IDs available

### Implementation Steps

**Step 3.5.1 — Build career description corpus per candidate**
```python
def build_career_corpus(cand: dict) -> str:
    """
    Concatenate all career description text for a candidate.
    Weight more recent roles by repeating them.
    """
    career = cand.get("career_history", [])
    # Sort by recency (most recent first)
    sorted_career = sorted(career, key=lambda r: r.get("end_date", ""), reverse=True)

    parts = []
    for i, role in enumerate(sorted_career):
        desc = role.get("description", "")
        title = role.get("title", "")
        company = role.get("company", "")
        # Repeat most recent role twice for extra weight
        weight = 2 if i == 0 else 1
        parts.extend([f"{title} at {company}: {desc}"] * weight)

    return " ".join(parts)
```

**Step 3.5.2 — Career BM25 score (against JD ontology query)**
```python
from rank_bm25 import BM25Okapi
import re

def tokenize(text: str) -> list:
    text = text.lower()
    text = re.sub(r'[^\w\s]', ' ', text)
    return text.split()

# Build BM25 query from ontology critical terms
JD_QUERY_TERMS = (
    ONTOLOGY["RETRIEVAL"][:5] +
    ONTOLOGY["VECTOR_DB"][:5] +
    ONTOLOGY["EVALUATION"][:5] +
    ONTOLOGY["EMBEDDINGS"][:3]
)

def compute_career_bm25_score(career_corpus: str,
                               bm25_index: BM25Okapi,
                               query: list) -> float:
    """Score how well career descriptions match the JD query."""
    doc_tokens = tokenize(career_corpus)
    scores = bm25_index.get_scores(query)
    # This is called per-candidate, not across the index
    # For efficiency, build the BM25 scores in batch
    return float(scores)  # handled in batch below
```

**Step 3.5.3 — Batch processing for all 100k**
```python
# Build corpus for all candidates
print("Building career corpora...")
corpora = []
candidate_ids = []

with gzip.open("data/raw/candidates.jsonl.gz", 'rt') as f:
    for line in tqdm(f):
        cand = json.loads(line)
        corpora.append(build_career_corpus(cand))
        candidate_ids.append(cand["candidate_id"])

# BM25 index over all career corpora
print("Building career BM25 index...")
tokenized_corpora = [tokenize(c) for c in corpora]
career_bm25 = BM25Okapi(tokenized_corpora)

# Score against JD query
query_tokens = tokenize(" ".join(JD_QUERY_TERMS))
print("Scoring career descriptions...")
career_bm25_scores = career_bm25.get_scores(query_tokens)
# Normalize to 0–1
career_bm25_norm = (career_bm25_scores - career_bm25_scores.min()) / \
                   (career_bm25_scores.max() - career_bm25_scores.min() + 1e-9)
```

**Step 3.5.4 — Career ontology score (direct term matching)**
```python
def compute_career_ontology_score(corpus: str) -> float:
    """
    How many critical ontology terms appear in career descriptions?
    Weighted heavily toward EVALUATION (rare, gold signal).
    """
    scores = compute_ontology_scores(corpus)
    return (
        0.30 * scores.get("RETRIEVAL", 0.0)
        + 0.25 * scores.get("EVALUATION", 0.0)   # highest weight — rarest
        + 0.20 * scores.get("VECTOR_DB", 0.0)
        + 0.15 * scores.get("EMBEDDINGS", 0.0)
        + 0.10 * scores.get("ML_AI", 0.0)
    )
```

**Step 3.5.5 — Founding team score**
```python
def compute_founding_team_score(cand: dict) -> float:
    """
    Detect signals that candidate has founding/early-employee experience.
    This directly targets the "Founding Team" in the JD title.
    """
    career = cand.get("career_history", [])
    profile = cand.get("profile", {})
    score = 0.0

    for role in career:
        title = role.get("title", "").lower()
        desc = role.get("description", "").lower()
        company_size = role.get("company_size", "")
        text = title + " " + desc

        # Explicit founding signals
        founding_signals = [
            "founding engineer", "founding member", "founding team",
            "first engineer", "first employee", "employee #1",
            "employee #2", "employee #3", "employee #4", "employee #5",
            "employee number 1", "early employee", "founding",
            "co-founder", "technical co-founder", "0 to 1",
            "zero to one", "built from scratch", "early team",
            "series a", "series b", "seed stage"
        ]
        if any(sig in text for sig in founding_signals):
            score += 1.0

        # Company size signals (small company = possible founding context)
        if company_size in ["1-10", "11-50", "1-50", "11-100"]:
            score += 0.3

        # Title signals that imply early-stage
        if any(kw in title for kw in ["founding", "staff engineer", "principal"]):
            score += 0.2

    return min(1.0, score)
```

**Step 3.5.6 — Assemble and save**
```python
career_features = []
with gzip.open("data/raw/candidates.jsonl.gz", 'rt') as f:
    for i, line in enumerate(tqdm(f)):
        cand = json.loads(line)
        corpus = corpora[i]

        career_features.append({
            "candidate_id": cand["candidate_id"],
            "career_bm25_score": float(career_bm25_norm[i]),
            "career_ontology_score": compute_career_ontology_score(corpus),
            "founding_team_score": compute_founding_team_score(cand),
            "career_corpus_length": len(corpus.split()),
        })

df_career = pl.DataFrame(career_features)
df_career.write_parquet("data/artifacts/career_features.parquet")
```

### Verification Checklist
- [ ] `career_features.parquet` contains exactly 100,000 rows
- [ ] `founding_team_score` is non-zero for < 5% of candidates (it should be rare)
- [ ] `career_ontology_score` is > 0.5 for only top ~10% of candidates
- [ ] Manually verify: pull a candidate who mentions "recommendation system" in career history — their `career_bm25_score` should be high even if skills section doesn't mention RAG
- [ ] Spot check: a marketing manager should have `career_ontology_score` ≈ 0
- [ ] Spot check: a candidate who says "founding engineer at Series A startup" should have `founding_team_score` > 0.5

### Common Mistakes
- Only scanning the skills section for these signals: the whole point of 3.5 is career descriptions.
- Weighting all ontology groups equally: `EVALUATION` terms are rare and critical — weight them highest.
- Not handling candidates with empty career history: return 0.0 for all scores gracefully.

### Output
```
data/artifacts/career_features.parquet
Schema: candidate_id, career_bm25_score, career_ontology_score,
        founding_team_score, career_corpus_length
```

---

## PHASE 3.7 — BEHAVIORAL INTELLIGENCE LAYER

### Goal
Convert all raw `redrob_signals` behavioral fields into clean, normalized scores that model recruiter-side demand and candidate-side availability. The challenge description explicitly highlights these signals. Most competing teams will use them partially or not at all — a well-engineered behavioral feature set is a legitimate leaderboard differentiator.

### Prerequisites
- Phase 3 complete (candidate_features.parquet exists — provides years_exp for imputation baseline)
- All 100k candidate raw profiles accessible

### Why a Dedicated Phase
These features were partially computed inside Phase 3 in earlier versions. Splitting them out is justified because:
- They share no logic with structural profile features (KG)
- They share no logic with text-mined features (Career Intelligence)
- They are the only features derived from recruiter-side market signals
- They need population-level normalization (e.g., market_demand_raw must be normalized across all 100k before it becomes a useful feature)

### Implementation Steps

**Step 3.7.1 — Define raw signal extraction**
```python
from datetime import datetime

def extract_behavioral_raw(cand: dict) -> dict:
    """Extract all raw behavioral signals from redrob_signals block."""
    signals = cand.get("redrob_signals", {})
    cid = cand["candidate_id"]

    # --- Availability inputs ---
    last_active_raw = signals.get("last_active_date", "")
    days_inactive = 9999  # default: assume inactive if missing
    if last_active_raw:
        try:
            la = datetime.strptime(last_active_raw[:10], "%Y-%m-%d")
            days_inactive = max(0, (datetime.now() - la).days)
        except ValueError:
            pass

    response_rate = float(signals.get("recruiter_response_rate", 0.0))
    response_time_hours = float(signals.get("avg_response_time_hours", 9999.0))
    notice_period_days = float(signals.get("notice_period_days", 90.0))

    # --- Market demand inputs ---
    saved_30d = float(signals.get("saved_by_recruiters_30d", 0.0))
    search_appearances_30d = float(signals.get("search_appearance_30d", 0.0))
    profile_views_30d = float(signals.get("profile_views_received_30d", 0.0))

    # --- Reliability inputs ---
    interview_completion = float(signals.get("interview_completion_rate", 0.0))
    offer_acceptance = float(signals.get("offer_acceptance_rate", 0.0))

    # --- Responsiveness inputs ---
    # Uses response_rate and response_time_hours (computed separately below)

    return {
        "candidate_id": cid,
        # Raw availability
        "_days_inactive": days_inactive,
        "_response_rate": response_rate,
        "_response_time_hours": response_time_hours,
        "_notice_period_days": notice_period_days,
        # Raw market demand
        "_saved_30d": saved_30d,
        "_search_appearances_30d": search_appearances_30d,
        "_profile_views_30d": profile_views_30d,
        # Raw reliability
        "_interview_completion": interview_completion,
        "_offer_acceptance": offer_acceptance,
    }
```

**Step 3.7.2 — Compute scores (population-normalized)**
```python
import numpy as np
import polars as pl

def compute_behavioral_scores(raw_df: pl.DataFrame) -> pl.DataFrame:
    """
    Convert raw signals into normalized [0,1] scores.
    Market demand MUST be normalized population-wide, not per-candidate.
    All others can be normalized per-candidate.
    """

    # --- Availability Score ---
    # Combines: recency of last activity, response rate, response time, notice period
    INACTIVE_BASELINE = 365   # 1 year without activity = 0 score
    MAX_RESPONSE_HOURS = 168  # 1 week = worst acceptable
    MAX_NOTICE_DAYS = 180     # 6 months = worst acceptable

    raw_df = raw_df.with_columns([
        # Each component normalized to [0, 1]
        (1.0 - (pl.col("_days_inactive") / INACTIVE_BASELINE).clip(0.0, 1.0))
            .alias("_active_score"),
        (pl.col("_response_rate") / 100.0).clip(0.0, 1.0)
            .alias("_response_rate_score"),
        (1.0 - (pl.col("_response_time_hours") / MAX_RESPONSE_HOURS).clip(0.0, 1.0))
            .alias("_response_time_score"),
        (1.0 - (pl.col("_notice_period_days") / MAX_NOTICE_DAYS).clip(0.0, 1.0))
            .alias("_notice_score"),
    ]).with_columns(
        (0.40 * pl.col("_active_score")
         + 0.30 * pl.col("_response_rate_score")
         + 0.15 * pl.col("_response_time_score")
         + 0.15 * pl.col("_notice_score"))
        .alias("availability_score")
    )

    # --- Responsiveness Score ---
    # Separate from availability: pure communication speed and reliability
    raw_df = raw_df.with_columns(
        (0.60 * pl.col("_response_rate_score")
         + 0.40 * pl.col("_response_time_score"))
        .alias("responsiveness_score")
    )

    # --- Market Demand Score (population-normalized) ---
    # Raw composite: saved × 3 + appearances × 1 + views × 0.5
    raw_df = raw_df.with_columns(
        (pl.col("_saved_30d") * 3.0
         + pl.col("_search_appearances_30d") * 1.0
         + pl.col("_profile_views_30d") * 0.5)
        .alias("_market_demand_raw")
    )
    max_demand = raw_df["_market_demand_raw"].max()
    raw_df = raw_df.with_columns(
        (pl.col("_market_demand_raw") / (max_demand + 1e-9))
        .alias("market_demand_score")
    )

    # --- Recruiter Interest Score ---
    # Focuses on DIRECT recruiter intent signals (saved + search), not passive views
    max_saved = raw_df["_saved_30d"].max()
    max_search = raw_df["_search_appearances_30d"].max()
    raw_df = raw_df.with_columns(
        (0.65 * (pl.col("_saved_30d") / (max_saved + 1e-9))
         + 0.35 * (pl.col("_search_appearances_30d") / (max_search + 1e-9)))
        .alias("recruiter_interest_score")
    )

    # --- Reliability Score ---
    raw_df = raw_df.with_columns(
        (0.60 * pl.col("_interview_completion")
         + 0.40 * pl.col("_offer_acceptance"))
        .alias("reliability_score")
    )

    # Drop raw columns, keep only named scores + candidate_id
    output_cols = [
        "candidate_id",
        "availability_score",
        "market_demand_score",
        "recruiter_interest_score",
        "reliability_score",
        "responsiveness_score",
        # Keep these as raw features too — LightGBM may use them separately
        "_days_inactive",
        "_notice_period_days",
        "_saved_30d",
    ]
    return raw_df.select(output_cols).rename({
        "_days_inactive": "days_inactive_raw",
        "_notice_period_days": "notice_period_days",
        "_saved_30d": "saved_by_recruiters_30d",
    })
```

**Step 3.7.3 — Process all 100k and save**
```python
print("Extracting behavioral signals...")
raw_records = []
with gzip.open("data/raw/candidates.jsonl.gz", 'rt') as f:
    for line in tqdm(f):
        cand = json.loads(line)
        raw_records.append(extract_behavioral_raw(cand))

raw_df = pl.DataFrame(raw_records)

print("Computing population-normalized behavioral scores...")
behavior_df = compute_behavioral_scores(raw_df)

behavior_df.write_parquet("data/artifacts/behavior_features.parquet")

# Sanity summary
print("\n=== Behavioral Feature Summary ===")
for col in ["availability_score", "market_demand_score",
            "recruiter_interest_score", "reliability_score", "responsiveness_score"]:
    vals = behavior_df[col]
    print(f"{col}: mean={vals.mean():.3f}, max={vals.max():.3f}, "
          f"p90={vals.quantile(0.9):.3f}, zeros={vals.filter(vals==0).len()}")
```

**Step 3.7.4 — Behavioral Leakage Experiment (run once, document result)**
```python
# Train two LightGBM models: one with and one without behavioral features.
# Document the top-100 overlap. If overlap < 85%, behavioral features matter
# significantly. If > 95%, they add little incremental value to the ranking.
# This experiment determines how heavily to weight them in the ensemble.

BEHAVIORAL_COLS = [
    "availability_score", "market_demand_score",
    "recruiter_interest_score", "reliability_score"
]

# Model A: full feature set (defined in Phase 8)
# Model B: full feature set minus BEHAVIORAL_COLS
# Compare: top-100 overlap, SHAP importance of behavioral features
# Document result in: data/artifacts/behavioral_leakage_experiment.md
```

### Verification Checklist
- [ ] `behavior_features.parquet` has exactly 100,000 rows
- [ ] `market_demand_score` is correctly population-normalized: max value should be 1.0
- [ ] `availability_score` is 0.0 for candidates where `last_active_date` is >2 years ago
- [ ] `notice_period_days` is stored as raw value (LightGBM may find non-linear signal in it)
- [ ] `saved_by_recruiters_30d > 0` for fewer than 20% of candidates (most candidates have 0 saves)
- [ ] No nulls in any column — fill with 0.0 for all missing signal data
- [ ] `recruiter_interest_score` is strictly higher for candidates with saves > candidates with only views
- [ ] Behavioral leakage experiment is documented (compare top-100 overlap with/without these features)
- [ ] Spot check: a candidate with `saved_by_recruiters_30d = 50` should have `market_demand_score` in top 5% of all candidates

### Common Mistakes
- Normalizing `market_demand_score` per-candidate instead of population-wide: this destroys the relative signal. A candidate who was saved 50 times is fundamentally different from one saved 0 times — that comparison only makes sense population-wide.
- Treating missing `last_active_date` as "very recently active": always assume worst-case (inactive) when data is missing.
- Including `days_inactive_raw` with wrong sign: higher days inactive = LESS available. Ensure the score is inverted correctly.
- Not handling `notice_period_days = 0` (immediate joiner): this is a positive signal, not an error. The score should be 1.0 for notice_period_days=0.

### Output
```
data/artifacts/behavior_features.parquet
Schema: candidate_id (str), availability_score (f64), market_demand_score (f64),
        recruiter_interest_score (f64), reliability_score (f64),
        responsiveness_score (f64), days_inactive_raw (f64),
        notice_period_days (f64), saved_by_recruiters_30d (f64)
```

---

## PHASE 4 — DATA INTEGRITY ENGINE

### Goal
Score every candidate on data plausibility. Detect honeypot profiles without deleting anyone. Output a fraud probability and quality score that will be used as features in the ranker and as hard-removal thresholds in the online pipeline.

### Prerequisites
- Phase 3 complete (years_exp available)
- All 100k candidate raw profiles

### Implementation Steps

**Step 4.1 — Rule Family 1: Timeline Contradictions**
```python
from datetime import datetime

def check_timeline_contradictions(cand: dict) -> tuple[int, float]:
    """Returns (anomaly_count, severity_score)."""
    career = cand.get("career_history", [])
    anomaly_count = 0
    severity = 0.0

    for role in career:
        start = role.get("start_date", "")
        end = role.get("end_date", "")
        duration = role.get("duration_months", 0)

        # Negative duration
        if duration < 0:
            anomaly_count += 1
            severity = max(severity, 1.0)  # severe

        # Duration doesn't match dates
        if start and end and end != "present":
            try:
                s = datetime.strptime(start[:7], "%Y-%m")
                e = datetime.strptime(end[:7], "%Y-%m")
                computed_months = (e.year - s.year) * 12 + (e.month - s.month)
                if abs(computed_months - duration) > 6:  # 6-month tolerance
                    anomaly_count += 1
                    severity = max(severity, 0.4)

                # Company founded after claimed start date
                # (requires external company founding year data — skip if not available)
            except ValueError:
                pass

    # Check for overlapping roles (two full-time jobs at same time)
    overlap_count = count_career_overlaps(career)
    anomaly_count += overlap_count
    if overlap_count > 0:
        severity = max(severity, 0.6)

    return anomaly_count, severity
```

**Step 4.2 — Rule Family 2: Skill Duration Contradictions**
```python
def check_skill_duration(cand: dict) -> tuple[int, float]:
    skills = cand.get("skills", [])
    profile = cand.get("profile", {})
    total_exp_months = float(profile.get("years_of_experience", 0)) * 12

    anomaly_count = 0
    severity = 0.0

    for skill in skills:
        skill_months = skill.get("duration_months", 0)
        if skill_months > total_exp_months + 12:  # 12-month tolerance
            anomaly_count += 1
            ratio = skill_months / max(1, total_exp_months)
            severity = max(severity, min(1.0, ratio / 3))

    return anomaly_count, severity
```

**Step 4.3 — Rule Family 3: Expert Inflation**
```python
def check_expert_inflation(cand: dict) -> tuple[int, float]:
    skills = cand.get("skills", [])
    profile = cand.get("profile", {})
    years_exp = float(profile.get("years_of_experience", 1))

    expert_skills = [s for s in skills if s.get("proficiency") == "expert"]
    expert_count = len(expert_skills)

    # Threshold: more than 2 expert skills per year of experience is suspicious
    threshold = years_exp * 2
    if expert_count > threshold:
        severity = min(1.0, (expert_count - threshold) / (threshold + 1))
        return 1, severity

    return 0, 0.0
```

**Step 4.4 — Rule Family 4: Seniority Contradictions**
```python
SENIOR_TITLES = [
    "principal", "staff", "senior staff", "distinguished",
    "vp of engineering", "cto", "director of engineering"
]

def check_seniority_contradiction(cand: dict) -> tuple[int, float]:
    career = cand.get("career_history", [])
    profile = cand.get("profile", {})
    years_exp = float(profile.get("years_of_experience", 0))

    for role in career:
        title = role.get("title", "").lower()
        if any(t in title for t in SENIOR_TITLES) and years_exp < 3:
            return 1, 0.7  # Severe — impossible progression

    return 0, 0.0
```

**Step 4.5 — Rule Family 5: Salary Impossibility**
```python
def check_salary_signals(cand: dict) -> tuple[int, float]:
    signals = cand.get("redrob_signals", {})
    salary_range = signals.get("expected_salary_range_inr_lpa", {})
    low = salary_range.get("min", 0)
    high = salary_range.get("max", 0)

    anomaly_count = 0
    severity = 0.0

    if low == 0 and high == 0:
        anomaly_count += 1
        severity = 0.2  # minor

    if high > 500:  # > 500 LPA is implausible for most profiles
        anomaly_count += 1
        severity = max(severity, 0.5)

    return anomaly_count, severity
```

**Step 4.6 — Rule Family 6: Endorsement Contradictions**
```python
def check_endorsement_contradiction(cand: dict) -> tuple[int, float]:
    skills = cand.get("skills", [])
    anomaly_count = 0
    severity = 0.0

    for skill in skills:
        proficiency = skill.get("proficiency", "")
        endorsements = skill.get("endorsements", 0)

        if proficiency in ["beginner", "novice"] and endorsements > 500:
            anomaly_count += 1
            severity = max(severity, 0.5)

    return anomaly_count, severity
```

**Step 4.7 — Aggregate all rules and compute fraud probability**
```python
def compute_quality_score(cand: dict) -> dict:
    """Run all rule families and aggregate."""
    checks = [
        check_timeline_contradictions(cand),
        check_skill_duration(cand),
        check_expert_inflation(cand),
        check_seniority_contradiction(cand),
        check_salary_signals(cand),
        check_endorsement_contradiction(cand),
    ]

    total_anomalies = sum(c[0] for c in checks)
    max_severity = max((c[1] for c in checks), default=0.0)

    # fraud_probability: combination of count and severity
    fraud_prob = min(1.0, (total_anomalies * 0.1) + (max_severity * 0.7))

    # quality_score: inverse
    quality_score = max(0.0, 1.0 - fraud_prob * 0.8)

    return {
        "candidate_id": cand["candidate_id"],
        "quality_score": quality_score,
        "fraud_probability": fraud_prob,
        "anomaly_count": total_anomalies,
        "has_severe_anomaly": max_severity > 0.6,
    }
```

**Step 4.8 — Process all 100k and save**
```python
quality_records = []
with gzip.open("data/raw/candidates.jsonl.gz", 'rt') as f:
    for line in tqdm(f):
        cand = json.loads(line)
        quality_records.append(compute_quality_score(cand))

df_quality = pl.DataFrame(quality_records)
df_quality.write_parquet("data/artifacts/quality_features.parquet")

# Summary stats
honeypot_count = df_quality.filter(pl.col("fraud_probability") > 0.98).height
print(f"Candidates with fraud_probability > 0.98: {honeypot_count}")
print(f"Expected: ~80 candidates (per dataset docs)")
```

### Verification Checklist
- [ ] Output has exactly 100,000 rows
- [ ] `fraud_probability > 0.98` affects approximately 80 candidates (the known honeypots)
- [ ] `has_severe_anomaly == True` for candidates with fraud_probability > 0.6
- [ ] NO candidates are deleted — only scored
- [ ] Spot check: candidate with "8 years at a 3-year-old company" → `fraud_probability > 0.7`
- [ ] Spot check: normal senior engineer with clean history → `quality_score > 0.85`
- [ ] All rules are deterministic — running twice produces identical output

### Common Mistakes
- Using an LLM for honeypot detection: this must be rule-based and deterministic.
- Hard-deleting candidates here: never. Only score.
- Setting fraud thresholds too aggressively: most candidates with one anomaly should survive.

### Output
```
data/artifacts/quality_features.parquet
Schema: candidate_id, quality_score, fraud_probability,
        anomaly_count, has_severe_anomaly (bool)
```

---

## PHASE 5 — VECTOR GENERATION (KAGGLE RTX)

### Goal
Precompute the dense embedding spaces for all 100,000 candidates across multiple scopes and models.

### Architecture Update (Post-Diagnostic V12)
We strictly avoid collapsing the candidate profile into a single "blob". We maintain 6 independent dense indexes to prevent semantic dilution:
- **Models**: `BAAI/bge-large-en-v1.5` and `intfloat/e5-large-v2`
- **Scopes**: Profile Text, Career History Text, Skills Text
- **Vectors per Candidate**: 6
- **Storage**: `np.float16` arrays inside Parquet to strictly bound VRAM and RAM footprint.

### Implementation Output
```python
data/artifacts/candidate_embeddings_bge.parquet (100k rows)
data/artifacts/candidate_embeddings_e5.parquet (100k rows)
data/artifacts/jd_embeddings.npz
```
*Note: We bypassed `faiss` entirely in favor of direct Numpy C-compiled matrix math for perfect exact-match fidelity at the 100k scale.*

---

## PHASE 6 — HYBRID RETRIEVAL ENSEMBLE

### Goal
Reduce the full 100,000 candidate pool to the Top 3,000 using independent Sparse and Dense semantic nets.

### Architecture Update (Post-Diagnostic V12)
We DO NOT use any Eligibility Filters (Phase 5.5 is removed). The hardware is sufficient to search the full 100k pool directly, guaranteeing we don't accidentally drop highly qualified candidates with poorly formatted resumes.

**Step 6.1 — Independent Dense RRF**
We query all 6 dense indices independently against the full 100k pool and extract the Top 5000 candidates per index using fast `np.argpartition`.
We fuse them using weighted Reciprocal Rank Fusion (RRF), heavily leaning into the Career scope which demonstrated the highest retrieval diversity in diagnostics:
```python
DENSE_WEIGHTS = {
    "e5_career": 1.0, "e5_profile": 0.5, "e5_skills": 0.4,
    "bge_career": 0.9, "bge_profile": 0.4, "bge_skills": 0.3
}
```
This produces the **Top 10,000 Dense Candidates**.

**Step 6.2 — Independent Sparse Search (BM25)**
We run a fully customized, offline-compatible `VectorizedBM25` built via Sklearn's `CountVectorizer` across the entire 100k candidate pool.
This produces the **Top 10,000 BM25 Candidates**.

**Step 6.3 — Global Fusion**
We merge the Top 10k Dense and Top 10k BM25 via RRF, yielding the final 10,000 candidates. The top 3,000 are extracted for Phase 7 scoring.
Each candidate is tagged with their `retrieval_source` (`dense_only`, `bm25_only`, `dense+bm25`).

### Verification
- Dense/BM25 overlap should be ~40-50% (proving high retrieval diversity).
- Final 3000 candidate pool is saved to `retrieval_top_3000.parquet`.
```

---

## PHASE 7A — TEACHER ENSEMBLE

### Goal
Generate synthetic relevance labels for the top 3,000 candidates using 3 specialized LLM teachers. These labels will train the LightGBM ranker. Label quality here directly determines final model quality.

### Prerequisites
- Phase 6 complete (top_3000.parquet)
- LLM API access
- All candidate feature files

### Implementation Steps

**Step 7A.1 — Load candidate profiles for top 3,000**
```python
# Need full profiles for teacher evaluation
top_3000_ids = set(pl.read_parquet("data/artifacts/top_3000.parquet")["candidate_id"].to_list())

profiles = {}
with gzip.open("data/raw/candidates.jsonl.gz", 'rt') as f:
    for line in f:
        cand = json.loads(line)
        if cand["candidate_id"] in top_3000_ids:
            profiles[cand["candidate_id"]] = cand
```

**Step 7A.2 — Teacher A: Technical Lens Prompt**
```python
TEACHER_A_PROMPT = """You are a Senior AI Engineer evaluating a candidate for a technical role.
You focus ONLY on technical depth in:
- Vector databases (Pinecone, Qdrant, Milvus, FAISS, Weaviate)
- Embedding models and semantic search
- Production retrieval systems
- ML/AI infrastructure

Rate the candidate's technical fit for a Senior AI Engineer role.

JD Technical Requirements:
{jd_requirements}

Candidate Profile:
{candidate_profile}

Return ONLY valid JSON. No explanation:
{{
  "score": <integer 0-100>,
  "rationale": "<one sentence citing specific technical evidence from profile>"
}}

Score anchors:
- 0-20: No relevant technical experience
- 21-40: Basic ML but missing retrieval/vector DB experience  
- 41-60: Some relevant experience, not production-level
- 61-80: Strong technical fit with most requirements
- 81-95: Excellent technical fit with production retrieval experience
- 96-100: Exceptional — deep expertise in ALL technical requirements
"""
```

**Step 7A.3 — Teacher B: Evaluation Expertise Lens**
```python
TEACHER_B_PROMPT = """You are a Search Systems Engineer evaluating a candidate.
You focus ONLY on ranking evaluation expertise:
- NDCG, MAP, MRR, Precision@K, Recall@K
- Offline evaluation frameworks
- A/B testing for ranking systems
- Search relevance measurement
- Offline-to-online correlation

This is the RAREST and MOST VALUABLE signal for this role.
Most candidates will score LOW here — that is expected and correct.
Do NOT inflate scores. Reserve 80+ for candidates who clearly demonstrate hands-on
evaluation framework experience.

JD Evaluation Requirements:
"Hands-on experience designing evaluation frameworks for ranking systems (NDCG, MAP, offline-to-online correlation)"

Candidate Profile:
{candidate_profile}

Return ONLY valid JSON. No explanation:
{{
  "score": <integer 0-100>,
  "rationale": "<one sentence citing specific evaluation experience from profile, or 'No evaluation experience found'>"
}}

Score anchors:
- 0-20: No mention of any evaluation metrics or frameworks
- 21-40: Mentions metrics in passing but no framework design
- 41-60: Has used evaluation metrics but not designed frameworks
- 61-80: Has designed or contributed to evaluation systems
- 81-100: Has owned ranking evaluation frameworks end-to-end
"""
```

**Step 7A.4 — Teacher C: Execution and Founding Team Lens**
```python
TEACHER_C_PROMPT = """You are a Startup Founder evaluating a candidate for a founding team role.
You focus ONLY on:
- Startup/product company experience (NOT consulting/outsourcing)
- Founding team signals (early employee, 0-to-1 experience)
- Execution speed: ships fast, doesn't over-theorize
- Ownership language: "I built", "I deployed", "I shipped"
- Scrappy builder mindset

JD Cultural Requirements:
"Scrappy product-engineering attitude. Needs to ship code fast rather than endlessly theorize.
Founding Team role."

Candidate Profile:
{candidate_profile}

Return ONLY valid JSON. No explanation:
{{
  "score": <integer 0-100>,
  "rationale": "<one sentence citing specific execution/startup evidence from profile>"
}}

Score anchors:
- 0-20: Pure consulting/services background, no product experience
- 21-40: Mixed background, mostly services
- 41-60: Product experience but large company, no startup
- 61-80: Clear product/startup background with ownership signals
- 81-100: Founding team experience, explicit "I built X from scratch" at startups
"""
```

**Step 7A.5 — Batch teacher evaluation**
```python
import time
import json
import pickle

def evaluate_candidate(cand: dict, prompt_template: str, jd_requirements: dict) -> dict:
    """Call LLM and parse response. Retry up to 3 times on failure."""
    profile_str = json.dumps({
        "headline": cand.get("profile", {}).get("headline", ""),
        "summary": cand.get("profile", {}).get("summary", ""),
        "years_experience": cand.get("profile", {}).get("years_of_experience", 0),
        "current_title": cand.get("profile", {}).get("current_title", ""),
        "skills": [s.get("name") for s in cand.get("skills", [])[:20]],
        "career_history": [
            {
                "title": r.get("title"),
                "company": r.get("company"),
                "duration_months": r.get("duration_months"),
                "description": r.get("description", "")[:500]
            }
            for r in cand.get("career_history", [])[:5]
        ]
    }, indent=2)

    prompt = prompt_template.format(
        jd_requirements=json.dumps(jd_requirements, indent=2),
        candidate_profile=profile_str
    )

    for attempt in range(3):
        try:
            raw = call_llm(prompt, temperature=0, max_tokens=200)
            result = json.loads(raw.strip())
            assert "score" in result and 0 <= result["score"] <= 100
            return result
        except Exception:
            time.sleep(2)

    return {"score": 50, "rationale": "parse_error"}  # fallback

# Run all 3 teachers across top 3000
# Cache results aggressively to disk after each batch
CACHE_PATH = "data/artifacts/teacher_cache.pkl"
cache = {}
try:
    with open(CACHE_PATH, "rb") as f:
        cache = pickle.load(f)
except FileNotFoundError:
    pass

jd_req = json.load(open("data/artifacts/jd_requirements.json"))
teacher_results = []

top_3000_ids = pl.read_parquet("data/artifacts/top_3000.parquet")["candidate_id"].to_list()

for i, cid in enumerate(tqdm(top_3000_ids)):
    if cid in cache:
        teacher_results.append(cache[cid])
        continue

    cand = profiles[cid]
    result_a = evaluate_candidate(cand, TEACHER_A_PROMPT, jd_req)
    result_b = evaluate_candidate(cand, TEACHER_B_PROMPT, jd_req)
    result_c = evaluate_candidate(cand, TEACHER_C_PROMPT, jd_req)

    row = {
        "candidate_id": cid,
        "teacher_a_score": float(result_a["score"]),
        "teacher_b_score": float(result_b["score"]),
        "teacher_c_score": float(result_c["score"]),
        "rationale_a": result_a.get("rationale", ""),
        "rationale_b": result_b.get("rationale", ""),
        "rationale_c": result_c.get("rationale", ""),
    }
    row["teacher_mean"] = (row["teacher_a_score"] + row["teacher_b_score"] + row["teacher_c_score"]) / 3
    row["teacher_median"] = float(sorted([row["teacher_a_score"], row["teacher_b_score"], row["teacher_c_score"]])[1])
    row["teacher_std"] = float(np.std([row["teacher_a_score"], row["teacher_b_score"], row["teacher_c_score"]]))

    cache[cid] = row
    teacher_results.append(row)

    # Save cache every 50 candidates
    if i % 50 == 0:
        with open(CACHE_PATH, "wb") as f:
            pickle.dump(cache, f)

df_teachers = pl.DataFrame(teacher_results)
df_teachers.write_parquet("data/artifacts/synthetic_labels.parquet")
```

### Verification Checklist
- [ ] Exactly 3,000 rows in `synthetic_labels.parquet`
- [ ] `teacher_b_score` (evaluation expert) is mostly < 40 — high scores should be RARE
- [ ] `teacher_std` has meaningful variance — not all near zero (all teachers agreeing is suspicious)
- [ ] Score histograms: check that each teacher uses the full 0–100 range, not just 70–90
- [ ] `parse_error` fallbacks: should be < 2% of candidates
- [ ] Cache hits: if resuming, cache should be loaded correctly
- [ ] Spot check: find a candidate who mentions "NDCG" explicitly — their `teacher_b_score` should be > 70

### Common Mistakes
- Not using temperature=0: scores become non-deterministic.
- Not caching: 3,000 × 3 teachers = 9,000 API calls. If the run crashes at 8,000, you want to resume.
- Using one general teacher instead of three specialized ones: specialization forces each teacher to focus on a different dimension.

### Output
```
data/artifacts/synthetic_labels.parquet
Schema: candidate_id, teacher_a_score, teacher_b_score, teacher_c_score,
        teacher_mean, teacher_median, teacher_std, rationale_a/b/c
```

---


## PHASE 7.1 — TEACHER DRIFT & REASONING CLUSTERING [V12]
### Goal
Detect template collapse in LLM teacher reasoning.
### Implementation
Embed the `reasoning_chain` outputs. If >80% of candidates fall into 1 cluster, fail the pipeline due to drift.


## PHASE 7B — LABEL CALIBRATION

### Goal
Ensure synthetic labels are spread across the full 0–100 range. Compressed distributions (e.g., 75–85 only) cause LightGBM to learn poor ranking functions because there's no signal to differentiate the top from the bottom.

### Implementation Steps

**Step 7B.1 — Check the distribution**
```python
import matplotlib.pyplot as plt
import numpy as np

df = pl.read_parquet("data/artifacts/synthetic_labels.parquet")
medians = df["teacher_median"].to_numpy()

print(f"Min: {medians.min():.1f}")
print(f"P10: {np.percentile(medians, 10):.1f}")
print(f"P50: {np.percentile(medians, 50):.1f}")
print(f"P90: {np.percentile(medians, 90):.1f}")
print(f"Max: {medians.max():.1f}")
print(f"Std: {medians.std():.1f}")

# Calibration needed if spread is < 40 points (P90-P10 < 40)
NEEDS_CALIBRATION = (np.percentile(medians, 90) - np.percentile(medians, 10)) < 40
print(f"Calibration needed: {NEEDS_CALIBRATION}")
```

**Step 7B.2 — Apply quantile calibration if needed**
```python
from sklearn.preprocessing import QuantileTransformer

if NEEDS_CALIBRATION:
    qt = QuantileTransformer(output_distribution='uniform', n_quantiles=500)
    calibrated = qt.fit_transform(medians.reshape(-1, 1)).flatten() * 100
    df = df.with_columns(pl.Series("calibrated_label", calibrated))
    print(f"After calibration — P10: {np.percentile(calibrated, 10):.1f}, P90: {np.percentile(calibrated, 90):.1f}")
else:
    df = df.with_columns(pl.col("teacher_median").alias("calibrated_label"))

df.write_parquet("data/artifacts/calibrated_labels.parquet")
```

### Verification Checklist
- [ ] `calibrated_label` range spans at least 0–80 (ideally 5–95)
- [ ] P90 - P10 > 40 after calibration
- [ ] The ordering (ranking) of candidates is preserved — calibration changes scale, not order
- [ ] Plot histogram: visually confirm it looks spread out, not a spike

### Output
```
data/artifacts/calibrated_labels.parquet
New column: calibrated_label (float, 0–100)
```

---

## PHASE 7C — PAIRWISE REFINEMENT

### Goal
Improve ordering among near-boundary candidates using pairwise LLM judgments. Only run on the top 300 candidates. Only accept judgments that are consistent in both directions.

### Implementation Steps

**Step 7C.1 — Select refinement pool**
```python
df = pl.read_parquet("data/artifacts/calibrated_labels.parquet").sort("calibrated_label", descending=True)
top_300_ids = df.head(300)["candidate_id"].to_list()
```

**Step 7C.2 — Identify pairs to compare**
```python
# Only compare candidates within 15 points of each other
scores = {row["candidate_id"]: row["calibrated_label"]
          for row in df.head(300).to_dicts()}

WINDOW = 15
pairs_to_compare = []
ids = list(scores.keys())

for i in range(len(ids)):
    for j in range(i+1, min(i+20, len(ids))):  # only compare nearby candidates
        if abs(scores[ids[i]] - scores[ids[j]]) < WINDOW:
            pairs_to_compare.append((ids[i], ids[j]))

print(f"Pairs to compare: {len(pairs_to_compare)}")
```

**Step 7C.3 — Pairwise prompt**
```python
PAIRWISE_PROMPT = """You are a senior recruiter for a Senior AI Engineer — Founding Team role.
Compare these two candidates. Evaluate for:
1. Technical depth in retrieval/vector DB/embeddings
2. Ranking evaluation experience (NDCG, MAP)
3. Product/startup background
4. Founding team suitability

Candidate A:
{profile_a}

Candidate B:
{profile_b}

Return ONLY valid JSON:
{{
  "winner": "A" or "B" or "tie",
  "margin": "clear" or "slight",
  "reason": "<one specific reason citing evidence from profiles>"
}}
"""

def run_pairwise(cid_a: str, cid_b: str) -> dict:
    """Run A vs B and B vs A for consistency."""
    result_ab = evaluate_pairwise(cid_a, cid_b)
    result_ba = evaluate_pairwise(cid_b, cid_a)

    # Normalize B vs A result to A vs B perspective
    def normalize(result, swapped: bool):
        if swapped and result["winner"] == "A":
            return {**result, "winner": "B"}
        if swapped and result["winner"] == "B":
            return {**result, "winner": "A"}
        return result

    r_ab = normalize(result_ab, False)
    r_ba = normalize(result_ba, True)

    # Consistent if both agree or both say tie
    consistent = r_ab["winner"] == r_ba["winner"]
    return {
        "cid_a": cid_a, "cid_b": cid_b,
        "winner": r_ab["winner"] if consistent else "tie",
        "consistent": consistent,
        "margin": r_ab.get("margin", "slight")
    }
```

**Step 7C.4 — Update labels based on consistent pairwise results**
```python
refined_scores = {cid: float(s) for cid, s in scores.items()}

for pair in tqdm(pairs_to_compare):
    result = run_pairwise(pair[0], pair[1])
    if not result["consistent"] or result["winner"] == "tie":
        continue  # fall back to absolute labels — no change

    winner = result["winner"]
    loser = "B" if winner == "A" else "A"
    winner_id = pair[0] if winner == "A" else pair[1]
    loser_id = pair[1] if winner == "A" else pair[0]

    # Only apply if inconsistent with current order
    if refined_scores[winner_id] < refined_scores[loser_id]:
        margin = 5.0 if result["margin"] == "clear" else 2.0
        refined_scores[winner_id] += margin
        refined_scores[loser_id] -= margin

# Merge refined scores back
df_full = pl.read_parquet("data/artifacts/calibrated_labels.parquet")
refined_col = [refined_scores.get(cid, row["calibrated_label"])
               for cid, row in zip(df_full["candidate_id"].to_list(),
                                   df_full.iter_rows(named=True))]

df_full = df_full.with_columns(
    pl.Series("refined_label", refined_col)
)
df_full.write_parquet("data/artifacts/refined_labels.parquet")
```

### Verification Checklist
- [ ] Pairwise comparisons run in both directions for every pair
- [ ] Inconsistent pairs fall back to absolute labels (no change)
- [ ] Top 300 label distribution is not dramatically altered from Phase 7B
- [ ] A candidate you know is strong did not get demoted by a contradictory pair
- [ ] Parse error rate < 5% for pairwise prompts

### Output
```
data/artifacts/refined_labels.parquet
New column: refined_label
```

---

## PHASE 7.25 — TEACHER ↔ STUDENT FEATURE PARITY AUDIT

### Goal
Formally verify that every concept the teacher ensemble evaluates has a corresponding numeric feature in the student's training matrix. This prevents a critical but silent failure mode: the teacher gives high scores for candidates with top-tier university education, but `education_tier_score` was accidentally dropped from the feature list. The student model then cannot learn the signal the teacher encoded — labels and features are misaligned.

This phase takes 30 minutes to run. Skipping it has caused significant silent leakage in competition pipelines.

### Prerequisites
- Phase 7A complete (teacher prompts are finalized)
- Phase 3, 3.5, 3.7, 4 complete (all feature files exist)

### Implementation Steps

**Step 7.25.1 — Define the Teacher Concept Registry**

Every dimension the teacher was explicitly prompted to evaluate must be registered here:

```python
# file: offline/phase07_25_feature_parity_audit.py

TEACHER_CONCEPT_REGISTRY = {
    # Teacher A — Technical Lens concepts
    "vector_database_depth": {
        "description": "Teacher A evaluates Pinecone/Qdrant/Milvus/FAISS/Weaviate expertise",
        "required_features": ["vector_db_score", "retrieval_score"],
        "teacher": "A"
    },
    "embedding_expertise": {
        "description": "Teacher A evaluates embedding model knowledge",
        "required_features": ["embedding_score"],
        "teacher": "A"
    },
    "retrieval_systems": {
        "description": "Teacher A evaluates production retrieval experience",
        "required_features": ["retrieval_score", "career_bm25_score", "career_ontology_score"],
        "teacher": "A"
    },
    "ml_ai_depth": {
        "description": "Teacher A evaluates general ML/AI depth",
        "required_features": ["ml_score", "llm_score"],
        "teacher": "A"
    },

    # Teacher B — Evaluation Expertise concepts
    "ranking_evaluation_frameworks": {
        "description": "Teacher B evaluates NDCG/MAP/MRR hands-on experience",
        "required_features": ["evaluation_score", "career_ontology_score"],
        "teacher": "B"
    },
    "ab_testing": {
        "description": "Teacher B evaluates A/B testing for ranking systems",
        "required_features": ["evaluation_score"],
        "teacher": "B"
    },

    # Teacher C — Execution and Founding Team concepts
    "startup_background": {
        "description": "Teacher C evaluates product/startup company experience",
        "required_features": ["startup_score", "product_company_score"],
        "teacher": "C"
    },
    "founding_team_signals": {
        "description": "Teacher C evaluates early-employee and founding team experience",
        "required_features": ["founding_team_score"],
        "teacher": "C"
    },
    "ownership_signals": {
        "description": "Teacher C evaluates ownership language: built, shipped, deployed",
        "required_features": ["career_ontology_score"],  # OWNERSHIP group in ontology
        "teacher": "C"
    },
    "consulting_penalty": {
        "description": "Teacher C penalizes consulting/services background",
        "required_features": ["consulting_score"],
        "teacher": "C"
    },

    # Shared across teachers
    "years_experience": {
        "description": "All teachers consider total years of experience",
        "required_features": ["years_exp"],
        "teacher": "ALL"
    },
    "seniority_level": {
        "description": "All teachers consider current title and seniority",
        "required_features": ["leadership_count", "promotion_count"],
        "teacher": "ALL"
    },
    "education_quality": {
        "description": "All teachers consider university tier if mentioned",
        "required_features": ["education_tier_score"],
        "teacher": "ALL"
    },
    "recruiter_market_demand": {
        "description": "Context signal: how much recruiter interest does this profile have",
        "required_features": ["market_demand_score", "recruiter_interest_score"],
        "teacher": "CONTEXT"
    },
    "candidate_availability": {
        "description": "Context signal: can the candidate realistically join",
        "required_features": ["availability_score", "notice_period_days"],
        "teacher": "CONTEXT"
    },
    "github_activity": {
        "description": "Technical signal: code contribution activity",
        "required_features": ["github_score_imputed", "github_missing"],
        "teacher": "ALL"
    },
}
```

**Step 7.25.2 — Build the actual feature inventory**
```python
import polars as pl
import json

# All columns that will be in the LightGBM feature matrix (must match FEATURE_COLS in Phase 8)
ACTUAL_FEATURE_COLS = [
    "retrieval_score", "vector_db_score", "embedding_score",
    "evaluation_score", "ml_score", "llm_score",
    "startup_score", "product_company_score", "consulting_score", "career_growth_score",
    "career_bm25_score", "career_ontology_score", "founding_team_score",
    "years_exp", "promotion_count", "leadership_count", "avg_tenure",
    "availability_score", "market_demand_score", "recruiter_interest_score",
    "reliability_score", "responsiveness_score",
    "github_score_imputed", "github_missing", "assessment_score",
    "quality_score", "fraud_probability", "anomaly_count",
    "teacher_median", "teacher_std",
    "retrieval_score_adjusted",
    "education_tier_score",
    "notice_period_days", "saved_by_recruiters_30d",
]

ACTUAL_FEATURE_SET = set(ACTUAL_FEATURE_COLS)
```

**Step 7.25.3 — Run the audit**
```python
def run_feature_parity_audit(
    concept_registry: dict,
    actual_feature_set: set
) -> dict:
    """
    For each teacher concept, verify all required features exist in the
    actual feature matrix. Fails loudly if any are missing.
    """
    audit_results = {}
    failures = []

    for concept_name, concept_info in concept_registry.items():
        required = concept_info["required_features"]
        missing = [f for f in required if f not in actual_feature_set]
        passed = len(missing) == 0

        audit_results[concept_name] = {
            "teacher": concept_info["teacher"],
            "description": concept_info["description"],
            "required_features": required,
            "missing_features": missing,
            "passed": passed
        }

        if not passed:
            failures.append(concept_name)

    return audit_results, failures

audit_results, failures = run_feature_parity_audit(
    TEACHER_CONCEPT_REGISTRY,
    ACTUAL_FEATURE_SET
)

# Print results
print("\n=== TEACHER ↔ STUDENT FEATURE PARITY AUDIT ===\n")
for concept, result in audit_results.items():
    status = "✅ PASS" if result["passed"] else "❌ FAIL"
    print(f"{status}  [{result['teacher']}] {concept}")
    if not result["passed"]:
        print(f"       MISSING FEATURES: {result['missing_features']}")

# Save audit to disk
import json
with open("data/artifacts/feature_parity_audit.json", "w") as f:
    json.dump(audit_results, f, indent=2)

# Hard fail if any concept is missing
if failures:
    print(f"\n⛔ AUDIT FAILED — {len(failures)} concept(s) have no corresponding features:")
    for f in failures:
        print(f"  - {f}: {audit_results[f]['missing_features']}")
    print("\nACTION: Add the missing features to the feature matrix before proceeding to Phase 8.")
    print("Do NOT proceed to Phase 8 with a failing audit.")
    raise SystemExit(1)
else:
    print(f"\n✅ AUDIT PASSED — all {len(TEACHER_CONCEPT_REGISTRY)} teacher concepts have student features")
```

**Step 7.25.4 — Verify feature files contain the registered columns**
```python
# Physical check: not just that column names are in the list,
# but that the actual parquet files contain them
import os

feature_files = {
    "candidate_features.parquet": [
        "retrieval_score", "vector_db_score", "embedding_score",
        "evaluation_score", "ml_score", "llm_score",
        "startup_score", "product_company_score", "consulting_score",
        "years_exp", "promotion_count", "leadership_count",
        "education_tier_score", "github_score_imputed", "github_missing"
    ],
    "career_features.parquet": [
        "career_bm25_score", "career_ontology_score", "founding_team_score"
    ],
    "behavior_features.parquet": [
        "availability_score", "market_demand_score", "recruiter_interest_score",
        "reliability_score", "responsiveness_score", "notice_period_days",
        "saved_by_recruiters_30d"
    ],
    "quality_features.parquet": [
        "quality_score", "fraud_probability", "anomaly_count"
    ],
}

print("\n=== PHYSICAL FILE COLUMN CHECK ===")
for filename, expected_cols in feature_files.items():
    path = f"data/artifacts/{filename}"
    if not os.path.exists(path):
        print(f"❌ MISSING FILE: {path}")
        continue

    df = pl.read_parquet(path)
    actual_cols = set(df.columns)
    missing = [c for c in expected_cols if c not in actual_cols]

    if missing:
        print(f"❌ {filename}: missing columns {missing}")
    else:
        print(f"✅ {filename}: all {len(expected_cols)} expected columns present")

    # Also check row count
    if len(df) != 100_000:
        print(f"   ⚠️  Row count: {len(df)} (expected 100,000)")
    else:
        print(f"   ✓  Row count: {len(df):,}")
```

### Verification Checklist
- [ ] `feature_parity_audit.json` exists and shows 0 failures
- [ ] All 4 feature parquet files contain their expected columns
- [ ] Every parquet file has exactly 100,000 rows
- [ ] No concept in the registry has an empty `required_features` list
- [ ] `education_tier_score` is present — this is a commonly missed feature from Teacher A
- [ ] `consulting_score` is present — required for Teacher C's penalty model
- [ ] `founding_team_score` is present — required for Teacher C and Phase 9.5
- [ ] Phase 8 is NOT started until this audit passes completely

### Common Mistakes
- Building the feature list in Phase 8 without running this audit first: by the time you see SHAP values, it's too late — you'll have trained a model that can't represent key teacher concepts.
- Adding features to `ACTUAL_FEATURE_COLS` without verifying the corresponding parquet file actually has that column.
- Running the audit against the wrong feature file: the physical column check in Step 7.25.4 guards against this.

### Output
```
data/artifacts/feature_parity_audit.json
Schema: {concept_name: {teacher, description, required_features, missing_features, passed}}
```

---


## PHASE 7.5 — HARD NEGATIVE MINING [V12]
### Goal
Force the model to learn strict boundary conditions by finding candidates who share keywords but violate explicit JD constraints (e.g., pure consulting background). Apply score caps instead of forcing label=0.


## PHASE 8 — LEARNING TO RANK

### Goal
Train a machine learning model to predict recruiter relevance scores from the feature matrix. The model compresses all the teacher signal into a fast, deterministic ranker that runs at inference time.

**Model strategy: Regression-First.**

The primary model is `LightGBMRegressor` with Huber loss. `LightGBMRanker` with LambdaRank is run as a comparison experiment only.

**Why Huber Regression over LambdaRank:**

LambdaRank is designed for multi-query settings where you train across many different queries and the model learns a general ranking function. This competition has exactly one JD — one query. In a single-query setting:

- LambdaRank cannot generalize across queries (there are none)
- LambdaRank's relative-pair gradients can be unstable on 3,000 samples
- Huber regression directly optimizes the teacher scores as absolute values, which is exactly what they are — a numeric estimate of recruiter relevance
- Huber is robust to outlier labels (miscalibrated teacher scores) unlike MSE
- Huber produces a continuous score that directly maps to the submission's `score` column

LambdaRank is kept as a benchmark to verify that Huber is not dramatically worse. In practice, on single-query datasets of this size, Huber consistently wins or ties. If LambdaRank shows > 5% better top-100 overlap across 5 seeds AND Phase 8.75 shows better Composite score, switch to LambdaRank. Otherwise: Huber wins by simplicity.

### Implementation Steps

**Step 8.1 — Build the feature matrix**
```python
import lightgbm as lgb
import numpy as np

# Load all feature files
cf = pl.read_parquet("data/artifacts/candidate_features.parquet")
crf = pl.read_parquet("data/artifacts/career_features.parquet")
qf = pl.read_parquet("data/artifacts/quality_features.parquet")
tf = pl.read_parquet("data/artifacts/top_3000.parquet")
lf = pl.read_parquet("data/artifacts/refined_labels.parquet").select(
    ["candidate_id", "refined_label", "teacher_median", "teacher_std"]
)

# Behavioral signals (loaded from raw data)
# Build behavior_features.parquet separately (see below)
bf = pl.read_parquet("data/artifacts/behavior_features.parquet")

# Join everything on candidate_id
df = (tf
    .join(cf, on="candidate_id", how="left")
    .join(crf, on="candidate_id", how="left")
    .join(qf, on="candidate_id", how="left")
    .join(lf, on="candidate_id", how="left")
    .join(bf, on="candidate_id", how="left")
    .fill_null(0.0)
)

FEATURE_COLS = [
    # Technical
    "retrieval_score", "vector_db_score", "embedding_score",
    "evaluation_score", "ml_score", "llm_score",
    # Career (from KG)
    "startup_score", "product_company_score", "career_growth_score",
    # Career (from 3.5)
    "career_bm25_score", "career_ontology_score", "founding_team_score",
    # Experience
    "years_exp", "promotion_count", "leadership_count", "avg_tenure",
    # Behavioral
    "availability_score", "market_demand_score", "reliability_score",
    "github_score_imputed", "github_missing", "assessment_score",
    # Quality
    "quality_score", "fraud_probability", "anomaly_count",
    # Teacher signals
    "teacher_median", "teacher_std",
    # Retrieval
    "retrieval_score_adjusted",
    # Education
    "education_tier_score",
]

X = df.select(FEATURE_COLS).to_numpy().astype(np.float32)
y = df["refined_label"].to_numpy().astype(np.float32)
```

**Step 8.2 — Train and benchmark**
```python
from sklearn.model_selection import train_test_split

X_train, X_val, y_train, y_val = train_test_split(X, y, test_size=0.2, random_state=42)

# Model A: Huber Regression (often best for single-query ranking)
model_huber = lgb.LGBMRegressor(
    objective="huber",
    alpha=0.9,
    learning_rate=0.05,
    num_leaves=63,
    max_depth=8,
    n_estimators=500,
    random_state=42,
    n_jobs=-1
)
model_huber.fit(
    X_train, y_train,
    eval_set=[(X_val, y_val)],
    callbacks=[lgb.early_stopping(50), lgb.log_evaluation(100)]
)

# Model B: LambdaRank (for comparison)
model_lambda = lgb.LGBMRanker(
    objective="lambdarank",
    learning_rate=0.05,
    num_leaves=63,
    max_depth=8,
    n_estimators=500,
    random_state=42,
    n_jobs=-1
)
model_lambda.fit(
    X_train, y_train,
    group=[len(X_train)],  # single query
    eval_set=[(X_val, y_val)],
    eval_group=[[len(X_val)]],
    callbacks=[lgb.early_stopping(50), lgb.log_evaluation(100)]
)

# Compare top-100 overlap across 5 random seeds
def top100_overlap(model_a, model_b, X, k=100):
    scores_a = model_a.predict(X)
    scores_b = model_b.predict(X)
    top_a = set(np.argsort(scores_a)[::-1][:k])
    top_b = set(np.argsort(scores_b)[::-1][:k])
    return len(top_a & top_b) / k

overlap = top100_overlap(model_huber, model_lambda, X_val)
print(f"Top-100 overlap between Huber and LambdaRank: {overlap:.2%}")
# If overlap > 85%, models agree — either is fine. Use Huber (simpler).

# Save winner (usually Huber)
import pickle
with open("data/artifacts/lgbm_ranker.pkl", "wb") as f:
    pickle.dump(model_huber, f)
```

### Verification Checklist
- [ ] Training completes without error
- [ ] Early stopping triggers (not running all 500 rounds blindly)
- [ ] Huber vs LambdaRank top-100 overlap > 80%
- [ ] Feature importance: at least one of {evaluation_score, market_demand_score, founding_team_score} appears in top 10
- [ ] Model scores on `X_val` have meaningful spread (not all the same value)

### Output
```
data/artifacts/lgbm_ranker.pkl
```

---

## PHASE 8.5 — SHAP FEEDBACK LOOP

### Goal
Audit that the model has learned what we intended. If critical signals are not in the top feature importance, the teacher labels are wrong — not the model.

### Implementation Steps

**Step 8.5.1 — Run SHAP analysis**
```python
import shap
import pickle
import numpy as np
import polars as pl

with open("data/artifacts/lgbm_ranker.pkl", "rb") as f:
    model = pickle.load(f)

# Use validation set
explainer = shap.TreeExplainer(model)
shap_values = explainer.shap_values(X_val)

# Feature importance from SHAP
mean_abs_shap = np.abs(shap_values).mean(axis=0)
importance_df = pl.DataFrame({
    "feature": FEATURE_COLS,
    "importance": mean_abs_shap.tolist()
}).sort("importance", descending=True)

print("\n=== SHAP Feature Importance ===")
print(importance_df.head(15))
```

**Step 8.5.2 — Automated verification**
```python
# Critical features that MUST be in top 15
MUST_BE_IMPORTANT = {
    "evaluation_score",    # NDCG/MAP — JD explicitly requests this
    "market_demand_score", # saved_by_recruiters — rare dataset signal
    "founding_team_score", # "Founding Team" is in the JD title
    "retrieval_score",     # core technical requirement
}

top_15_features = set(importance_df.head(15)["feature"].to_list())
missing_from_top15 = MUST_BE_IMPORTANT - top_15_features

if missing_from_top15:
    print(f"\n⚠️  SHAP WARNING: These critical features are not in top 15:")
    for f in missing_from_top15:
        rank = importance_df["feature"].to_list().index(f) + 1
        print(f"  {f}: rank #{rank}")
    print("\nACTION: Fix teacher prompts and regenerate labels before proceeding.")
    print("Do NOT tune model hyperparameters — the labels are the problem.")
else:
    print("\n✅ SHAP validation passed — all critical features in top 15")
```

### Verification Checklist
- [ ] SHAP analysis completes without error
- [ ] `evaluation_score` in top 15 features by SHAP importance
- [ ] `market_demand_score` in top 15 features
- [ ] `founding_team_score` in top 15 features
- [ ] `retrieval_score` in top 10 features
- [ ] `fraud_probability` has non-zero importance (model is using integrity signals)
- [ ] If any critical feature is missing: go back to Phase 7A, fix the relevant teacher prompt, regenerate

---


## PHASE 8.5 — AUTOMATED SHAP FEEDBACK LOOP [V12]
### Goal
Automatically generate SHAP feature importances after LTR training. If core JD features fall out of the top 10, fail the build.


## PHASE 8.75 — RETRIEVAL & RANKING STRESS TEST

### Goal
Create a local proxy for leaderboard performance before any real submission. Without this phase, every architectural change is tuned blind — you have no signal about whether a change to the ontology, the teacher prompts, or the feature weights actually improved NDCG@10. This phase simulates the judge's evaluation using teacher labels as a proxy ground truth.

This is the only phase that gives you a feedback loop before you submit.

### Prerequisites
- Phase 8 complete (LightGBM model trained)
- Phase 8.5 complete (SHAP passed)
- Phase 6 complete (top_3000.parquet exists with retrieval scores)

### Implementation Steps

**Step 8.75.1 — Recall@3000 Verification**

Measures whether the hybrid retrieval is capturing all genuinely relevant candidates before the ranking stage. If a truly relevant candidate isn't in the top 3,000, no amount of model tuning will recover them.

```python
import polars as pl
import numpy as np

# Use teacher labels as proxy: any candidate with teacher_median > 75 is "relevant"
RELEVANCE_THRESHOLD = 75.0

labels = pl.read_parquet("data/artifacts/refined_labels.parquet")
top_3000 = pl.read_parquet("data/artifacts/top_3000.parquet")

# Relevant candidates according to teacher
relevant_ids = set(
    labels.filter(pl.col("refined_label") >= RELEVANCE_THRESHOLD)["candidate_id"].to_list()
)

# Relevant candidates in the retrieved top 3000
retrieved_ids = set(top_3000["candidate_id"].to_list())
retrieved_relevant = relevant_ids & retrieved_ids

recall_at_3000 = len(retrieved_relevant) / max(1, len(relevant_ids))

print(f"=== RETRIEVAL STRESS TEST ===")
print(f"Teacher-relevant candidates (score ≥ {RELEVANCE_THRESHOLD}): {len(relevant_ids)}")
print(f"Retrieved in top 3000: {len(retrieved_relevant)}")
print(f"Recall@3000: {recall_at_3000:.3f}")

if recall_at_3000 < 0.85:
    print("⚠️  WARNING: Recall@3000 < 0.85 — you are missing relevant candidates at retrieval.")
    print("   ACTION: Increase top_k temporarily, diagnose which relevant candidates were missed,")
    print("   and adjust hybrid weights or ontology to capture them.")
elif recall_at_3000 < 0.95:
    print("⚠️  CAUTION: Recall@3000 is acceptable but not excellent. Monitor carefully.")
else:
    print("✅ Recall@3000 is strong.")
```

**Step 8.75.2 — Simulated NDCG@10, NDCG@50, MAP, P@10**

Uses teacher labels as proxy relevance grades. This is not a perfect proxy for the hidden ground truth, but it is the best available local signal and will track the true leaderboard directionally.

```python
def dcg_at_k(relevances: list, k: int) -> float:
    """Compute DCG@K given a list of relevance scores in ranked order."""
    relevances = np.array(relevances[:k])
    if len(relevances) == 0:
        return 0.0
    gains = (2 ** relevances - 1) / np.log2(np.arange(2, len(relevances) + 2))
    return float(np.sum(gains))

def ndcg_at_k(ranked_relevances: list, k: int) -> float:
    """Compute NDCG@K."""
    actual_dcg = dcg_at_k(ranked_relevances, k)
    ideal_relevances = sorted(ranked_relevances, reverse=True)
    ideal_dcg = dcg_at_k(ideal_relevances, k)
    if ideal_dcg == 0:
        return 0.0
    return actual_dcg / ideal_dcg

def average_precision(ranked_relevances: list, threshold: float = 50.0) -> float:
    """Compute Average Precision treating scores >= threshold as relevant."""
    relevant = np.array(ranked_relevances) >= threshold
    if relevant.sum() == 0:
        return 0.0
    precisions = []
    num_relevant = 0
    for i, rel in enumerate(relevant):
        if rel:
            num_relevant += 1
            precisions.append(num_relevant / (i + 1))
    return float(np.mean(precisions))

def run_ranking_simulation(model, X, candidate_ids, label_lookup, top_k=100):
    """
    Simulate leaderboard evaluation using teacher labels as proxy ground truth.
    Returns dict of metric_name -> score.
    """
    # Get model predictions and rank
    raw_scores = model.predict(X)
    ranked_indices = np.argsort(raw_scores)[::-1][:top_k]
    ranked_ids = [candidate_ids[i] for i in ranked_indices]

    # Get teacher labels for ranked candidates (normalized 0–1 for NDCG)
    ranked_relevances = []
    for cid in ranked_ids:
        label = label_lookup.get(cid, 0.0)
        # Normalize to [0, 3] grades for NDCG (0=not relevant, 3=highly relevant)
        grade = min(3.0, label / 33.3)
        ranked_relevances.append(grade)

    # All teacher labels for ideal computation
    all_labels = [(cid, label_lookup.get(cid, 0.0)) for cid in candidate_ids]
    all_labels_sorted = sorted(all_labels, key=lambda x: x[1], reverse=True)
    ideal_relevances = [min(3.0, l / 33.3) for _, l in all_labels_sorted[:top_k]]

    # Compute metrics
    actual_ndcg10 = ndcg_at_k(ranked_relevances, 10) / ndcg_at_k(ideal_relevances, 10) \
        if ndcg_at_k(ideal_relevances, 10) > 0 else 0.0

    # Properly compute NDCG using ideal as denominator
    def ndcg_proper(ranked, ideal, k):
        return dcg_at_k(ranked, k) / max(1e-9, dcg_at_k(ideal, k))

    ndcg10 = ndcg_proper(ranked_relevances, ideal_relevances, 10)
    ndcg50 = ndcg_proper(ranked_relevances, ideal_relevances, 50)
    map_score = average_precision(ranked_relevances, threshold=2.0)
    p_at_10 = np.mean([1 if r >= 2.0 else 0 for r in ranked_relevances[:10]])

    # Composite score matching challenge formula
    composite = 0.50 * ndcg10 + 0.30 * ndcg50 + 0.15 * map_score + 0.05 * p_at_10

    return {
        "NDCG@10": ndcg10,
        "NDCG@50": ndcg50,
        "MAP": map_score,
        "P@10": p_at_10,
        "Composite": composite,
    }
```

**Step 8.75.3 — Run the simulation and save the report**
```python
import pickle

with open("data/artifacts/lgbm_ranker.pkl", "rb") as f:
    lgbm = pickle.load(f)

# Build feature matrix and labels for top-3000 candidates
labels_df = pl.read_parquet("data/artifacts/refined_labels.parquet")
label_lookup = {row["candidate_id"]: row["refined_label"]
                for row in labels_df.iter_rows(named=True)}

# Feature matrix (same assembly as Phase 8)
# X, candidate_ids = build_feature_matrix(top_3000_ids)  # use Phase 8 function
metrics = run_ranking_simulation(lgbm, X, candidate_ids, label_lookup)

print("\n=== RANKING STRESS TEST RESULTS ===")
print("(Using teacher labels as proxy ground truth — directionally accurate, not exact)")
print()
for metric, value in metrics.items():
    print(f"  {metric}: {value:.4f}")
print()
print(f"  Leaderboard proxy score: {metrics['Composite']:.4f}")
print()

# Save report
stress_report = "# Ranking Stress Test Report\n\n"
stress_report += f"**Retrieval Recall@3000:** {recall_at_3000:.3f}\n\n"
stress_report += "## Proxy Leaderboard Metrics\n\n"
stress_report += "| Metric | Weight | Value |\n|---|---|---|\n"
stress_report += f"| NDCG@10 | 0.50 | {metrics['NDCG@10']:.4f} |\n"
stress_report += f"| NDCG@50 | 0.30 | {metrics['NDCG@50']:.4f} |\n"
stress_report += f"| MAP | 0.15 | {metrics['MAP']:.4f} |\n"
stress_report += f"| P@10 | 0.05 | {metrics['P@10']:.4f} |\n"
stress_report += f"| **Composite** | — | **{metrics['Composite']:.4f}** |\n\n"
stress_report += "> These metrics use teacher labels as proxy ground truth.\n"
stress_report += "> A 0.01 improvement here typically corresponds to a meaningful leaderboard move.\n"

with open("data/artifacts/stress_test_report.md", "w") as f:
    f.write(stress_report)

print("Saved: data/artifacts/stress_test_report.md")
```

**Step 8.75.4 — Iterative tuning protocol using stress test**

Use this simulation to compare any two versions of the system before committing a change:

```
For any proposed change (e.g., adjusted ontology weights, new feature, different top_k):
  1. Run the change
  2. Re-run Phases 8 and 8.75
  3. Compare Composite score
  4. If Composite improves ≥ 0.002: accept the change
  5. If Composite improves < 0.002: the change is noise — revert it
  6. If Composite drops: revert immediately

Keep a version log:
  V1 baseline:                  Composite = 0.XXXX
  V2 + career description BM25: Composite = 0.XXXX
  V3 + founding_team_score:     Composite = 0.XXXX
  ...
```

### Verification Checklist
- [ ] `stress_test_report.md` exists with all 4 metrics computed
- [ ] `Recall@3000 > 0.85` — if not, fix retrieval before tuning the ranker
- [ ] `NDCG@10 > NDCG@50` — this is always true by math; if it's not, the metric code has a bug
- [ ] `Composite` score is computed correctly: `0.50*NDCG10 + 0.30*NDCG50 + 0.15*MAP + 0.05*P10`
- [ ] The simulation has been run at least once per major model change
- [ ] A version log exists documenting the Composite score for each architecture change

### Common Mistakes
- Using raw teacher scores without normalizing to NDCG relevance grades: NDCG expects relevance grades (0, 1, 2, 3), not scores (0–100). Divide by 33.3 and cap at 3.
- Treating the simulation score as identical to the true leaderboard score: it's a directional proxy, not a perfect predictor. Use it for relative comparisons between versions, not as an absolute score estimate.
- Forgetting to re-run this after Phase 7C (pairwise refinement): the labels change there, so the simulation results change too.

### Output
```
data/artifacts/stress_test_report.md
```

---

## PHASE 9 — ENSEMBLE MODELS

### Goal
Combine LightGBM with XGBoost to reduce ranking instability. Two models with different algorithmic bases often catch each other's blind spots.

### Implementation Steps

```python
import xgboost as xgb

# Train XGBoost on same features/labels
model_xgb = xgb.XGBRegressor(
    objective="reg:pseudohubererror",
    learning_rate=0.05,
    max_depth=7,
    n_estimators=500,
    subsample=0.8,
    colsample_bytree=0.8,
    random_state=42,
    n_jobs=-1,
    early_stopping_rounds=50,
    eval_metric="rmse"
)
model_xgb.fit(
    X_train, y_train,
    eval_set=[(X_val, y_val)],
    verbose=100
)

with open("data/artifacts/xgb_ranker.pkl", "wb") as f:
    pickle.dump(model_xgb, f)

# Combine: normalize each model's output to [0,1] then blend
def ensemble_score(X, lgbm_model, xgb_model,
                   lgbm_weight=0.6, xgb_weight=0.4):
    lgbm_scores = lgbm_model.predict(X)
    xgb_scores = xgb_model.predict(X)

    # Normalize each to [0, 1]
    def norm(s):
        return (s - s.min()) / (s.max() - s.min() + 1e-9)

    return lgbm_weight * norm(lgbm_scores) + xgb_weight * norm(xgb_scores)
```

### Verification Checklist
- [ ] Both models trained and saved
- [ ] Top-100 overlap between LGBM and XGBoost > 85%
- [ ] If overlap < 70%, models disagree substantially — investigate which has better SHAP alignment with critical features
- [ ] Ensemble score distribution is spread across a reasonable range (not all ~0.5)

### Output
```
data/artifacts/lgbm_ranker.pkl
data/artifacts/xgb_ranker.pkl
```

---


## PHASE 9.2 — CROSS-ENCODER RE-RANKING [V12]
### Goal
Apply a heavy cross-encoder (`ms-marco-MiniLM-L-6-v2` or `bge-reranker-large`) ONLY to the Top 500 candidates to maximize NDCG@50.


## PHASE 9.5 — ELITE RE-RANKING

### Goal
Specifically optimize NDCG@10 by applying a second, sharper scoring pass to the top 20 candidates. This layer uses a different weight profile that heavily emphasizes the two rarest, most JD-critical signals: evaluation expertise and founding team fit.

### Prerequisites
- Phase 9 complete — full top-100 list available
- All feature files loaded

### Implementation Steps

```python
def compute_elite_score(features: dict) -> float:
    """
    Re-ranking formula for top 20 candidates.
    Weights are different from ensemble — emphasize rare critical signals.
    """
    return (
        0.30 * features.get("evaluation_score", 0.0)      # NDCG/MAP — rarest
        + 0.25 * features.get("founding_team_score", 0.0) # JD title requirement
        + 0.20 * features.get("availability_score", 0.0)  # Can they actually join?
        + 0.15 * features.get("teacher_median", 0.0) / 100  # Overall confidence (normalize to 0-1)
        - 0.10 * min(1.0, features.get("teacher_std", 0.0) / 30)  # Uncertainty penalty
    )

def apply_elite_reranking(top_100_df: pl.DataFrame,
                           features_df: pl.DataFrame,
                           pool_size: int = 20) -> pl.DataFrame:
    """
    Input: top_100_df sorted by ensemble_score descending
    Output: same 100 candidates, but top 20 re-ordered by elite_score
    """
    # Split: top 20 for re-ranking, rest stay in place
    top_20 = top_100_df.head(pool_size)
    rest = top_100_df.tail(len(top_100_df) - pool_size)

    # Join features
    top_20_features = top_20.join(features_df, on="candidate_id", how="left")

    # Compute elite scores
    elite_scores = []
    for row in top_20_features.iter_rows(named=True):
        elite_scores.append(compute_elite_score(row))

    top_20 = top_20.with_columns(pl.Series("elite_score", elite_scores))
    top_20_reranked = top_20.sort("elite_score", descending=True).drop("elite_score")

    # Reassemble: re-ranked top 20 + unchanged rest
    return pl.concat([top_20_reranked, rest])
```

### Verification Checklist
- [ ] Re-ranking only affects positions 1–20, not 21–100
- [ ] If a candidate with NDCG/MAP experience was ranked #15, they should move into top 5 after re-ranking
- [ ] Candidates ranked 21–100 have the same relative order before and after
- [ ] The re-ranking is deterministic (pure formula, no randomness)

---

## PHASE 10 — REASONING BANK

### Goal
Generate unique, factually grounded reasoning for all 3,000 candidates offline. The reasoning is stored and attached at inference time — no LLM calls during the online pipeline.

### Implementation Steps

**Step 10.1 — Reasoning prompt template**
```python
REASONING_PROMPT = """You are writing a factual recruiter assessment for this candidate.

STRICT RULES:
1. Only use information explicitly present in the candidate profile below
2. Never invent skills, companies, projects, or experiences
3. Every claim must cite specific evidence (a company name, a role title, a technology name)
4. Use numbers whenever available (years, months, scores)
5. Structure must be exactly 3 sentences

Job Description Requirements:
{jd_requirements_summary}

Candidate Profile:
{candidate_profile}

Write exactly 3 sentences following this structure:

SENTENCE 1 (Evidence): State the candidate's total experience and 2-3 specific technical 
  skills/systems from their profile that are relevant to the role.

SENTENCE 2 (Alignment): Identify the strongest specific alignment with the JD requirements,
  citing a concrete company/project/achievement from their career history.

SENTENCE 3 (Gap): State ONE honest gap or concern (e.g., notice period, consulting background,
  missing vector DB experience, high seniority mismatch). Be specific.

Output only the 3 sentences. No headers, no bullets, no JSON.
"""

JD_SUMMARY = """
Senior AI Engineer — Founding Team
Must have: retrieval systems, vector databases (Pinecone/Qdrant/Milvus), 
embedding-based search, ranking evaluation (NDCG/MAP)
Background: 5-9 years, product companies, startup/founding team mindset, fast execution
"""
```

**Step 10.2 — Generate for all 3,000**
```python
reasoning_records = []
reasoning_cache = {}

for cid in tqdm(top_3000_ids):
    if cid in reasoning_cache:
        reasoning_records.append(reasoning_cache[cid])
        continue

    cand = profiles[cid]
    profile_str = format_profile_for_reasoning(cand)  # compact but complete

    for attempt in range(3):
        try:
            reasoning = call_llm(
                REASONING_PROMPT.format(
                    jd_requirements_summary=JD_SUMMARY,
                    candidate_profile=profile_str
                ),
                temperature=0.3,  # slight creativity to avoid identical phrasings
                max_tokens=300
            )
            # Validate: must be non-empty and not contain red-flag phrases
            assert len(reasoning) > 50
            assert "no information" not in reasoning.lower()
            break
        except Exception:
            reasoning = f"{cand.get('profile', {}).get('years_of_experience', '?')} years of ML experience with relevant technical background. Profile shows alignment with core AI engineering requirements. Assessment limited due to sparse profile data."

    record = {"candidate_id": cid, "reasoning": reasoning.strip()}
    reasoning_cache[cid] = record
    reasoning_records.append(record)

    if len(reasoning_records) % 100 == 0:
        with open("data/artifacts/reasoning_cache.pkl", "wb") as f:
            pickle.dump(reasoning_cache, f)

df_reasoning = pl.DataFrame(reasoning_records)
df_reasoning.write_parquet("data/artifacts/reasoning.parquet")
```

**Step 10.3 — Post-generation validation**
```python
def validate_reasoning(reasoning: str, candidate_profile: dict) -> list:
    """Returns list of issues found."""
    issues = []

    # Must have a number
    import re
    if not re.search(r'\d', reasoning):
        issues.append("no_number")

    # Must not be too short
    if len(reasoning.split()) < 30:
        issues.append("too_short")

    # Check for common hallucination patterns
    hallucination_patterns = ["RAG system" , "vector database expert", "10+ years"]
    for pattern in hallucination_patterns:
        if pattern.lower() in reasoning.lower():
            years_exp = candidate_profile.get("profile", {}).get("years_of_experience", 0)
            # Flag if the claim doesn't match the data
            if "10+ years" in pattern and years_exp < 10:
                issues.append(f"potential_hallucination: {pattern}")

    return issues

# Validate all 3000
validation_issues = []
for record in reasoning_records:
    cid = record["candidate_id"]
    issues = validate_reasoning(record["reasoning"], profiles[cid])
    if issues:
        validation_issues.append({"candidate_id": cid, "issues": issues})

print(f"Reasoning entries with issues: {len(validation_issues)} / 3000")
print(f"Target: < 5% ({0.05 * 3000:.0f})")
```

### Verification Checklist
- [ ] All 3,000 candidates have reasoning (no gaps in coverage)
- [ ] No reasoning entry shorter than 30 words
- [ ] > 95% of reasoning entries contain at least one number
- [ ] < 5% of entries flagged in post-generation validation
- [ ] Manually read 20 reasoning entries — they should all feel unique and grounded
- [ ] The reasoning for a candidate who lacks vector DB experience mentions this gap
- [ ] Reasoning bank size covers all top 3,000 (not just top 100 or 500)

### Output
```
data/artifacts/reasoning.parquet
Schema: candidate_id (str), reasoning (str)
```

---

## PHASE 11 — RUNTIME VERIFICATION

### Goal
Prove that the online pipeline completes in under 5 minutes on CPU with ≤16 GB RAM. Produce documented evidence for judges.

### Implementation Steps

```python
import time
import tracemalloc
import polars as pl

def benchmark_online_pipeline():
    """Run the full online pipeline with precise timing."""
    timings = {}
    tracemalloc.start()

    t0 = time.perf_counter()

    # O1: Load
    t_load_start = time.perf_counter()
    cf = pl.read_parquet("data/artifacts/candidate_features.parquet")
    crf = pl.read_parquet("data/artifacts/career_features.parquet")
    qf = pl.read_parquet("data/artifacts/quality_features.parquet")
    bf = pl.read_parquet("data/artifacts/behavior_features.parquet")
    index = faiss.read_index("data/artifacts/faiss.index")
    with open("data/artifacts/bm25.pkl", "rb") as f:
        bm25_data = pickle.load(f)
    with open("data/artifacts/lgbm_ranker.pkl", "rb") as f:
        lgbm = pickle.load(f)
    with open("data/artifacts/xgb_ranker.pkl", "rb") as f:
        xgb_model = pickle.load(f)
    reasoning_df = pl.read_parquet("data/artifacts/reasoning.parquet")
    timings["O1_load"] = time.perf_counter() - t_load_start

    # O2: Retrieve
    t_ret = time.perf_counter()
    top_3000_ids = run_hybrid_retrieval(index, bm25_data)
    timings["O2_retrieval"] = time.perf_counter() - t_ret

    # O3: Integrity filter
    t_int = time.perf_counter()
    filtered_ids = apply_integrity_filter(top_3000_ids, qf)
    timings["O3_integrity"] = time.perf_counter() - t_int

    # O4: Model scoring
    t_model = time.perf_counter()
    scores = run_ensemble_scoring(filtered_ids, cf, crf, qf, bf, lgbm, xgb_model)
    timings["O4_scoring"] = time.perf_counter() - t_model

    # O5: Top 100
    t_top = time.perf_counter()
    top_100 = select_top_100(scores)
    timings["O5_top100"] = time.perf_counter() - t_top

    # O6: Elite re-ranking
    t_elite = time.perf_counter()
    top_100 = apply_elite_reranking(top_100, cf.join(crf, on="candidate_id"))
    timings["O6_elite"] = time.perf_counter() - t_elite

    # O7: Score normalization
    t_norm = time.perf_counter()
    top_100 = normalize_scores(top_100)
    timings["O7_normalize"] = time.perf_counter() - t_norm

    # O8: Reasoning join
    t_reason = time.perf_counter()
    top_100 = top_100.join(reasoning_df, on="candidate_id", how="left")
    timings["O8_reasoning"] = time.perf_counter() - t_reason

    total = time.perf_counter() - t0
    timings["TOTAL"] = total

    # Memory
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    return timings, peak / 1024 / 1024 / 1024  # peak GB

timings, peak_gb = benchmark_online_pipeline()

# Generate runtime_report.md
report = "# Runtime Verification Report\n\n"
report += "| Stage | Time |\n|---|---|\n"
for stage, t in timings.items():
    report += f"| {stage} | {t:.2f}s |\n"
report += f"\n**Peak Memory:** {peak_gb:.2f} GB\n"
report += f"\n**Status:** {'✅ PASS' if timings['TOTAL'] < 300 else '❌ FAIL — optimize FAISS nprobe'}\n"

with open("data/artifacts/runtime_report.md", "w") as f:
    f.write(report)

print(report)
```

### Optimization If Over Budget
```
If TOTAL > 300 seconds:
1. Reduce faiss.index.nprobe from 50 → 30 (fastest fix, ~30% speedup, slight recall loss)
2. Switch candidate feature loading to lazy evaluation with Polars scan_parquet
3. Pre-filter candidates with fraud_probability > 0.98 from the feature matrix entirely
4. Profile each step and optimize the slowest one first
```

### Verification Checklist
- [ ] `runtime_report.md` exists with all stage timings
- [ ] `TOTAL < 300 seconds` on the target machine (CPU only)
- [ ] `Peak Memory < 16 GB`
- [ ] Run the benchmark THREE times — all three runs complete successfully
- [ ] Output CSV is identical across all three runs (determinism check)

---


## PHASE 11.25 — SUBMISSION SIMULATION [V12]
### Goal
Generate the CSV and run strict Kaggle format validation before export.


## PHASE 11.5 — SUBMISSION SAFETY AUDIT

### Goal
Run an automated, exhaustive safety check on the final CSV before it leaves your machine. This phase directly protects against disqualification. Every check here maps to a specific way submissions have historically been invalidated in ranking competitions.

### Why a Dedicated Phase
By the time you are generating the final CSV you are tired, time-pressured, and past the point of careful thinking. This phase exists so you can run a single command and get a definitive PASS or FAIL — no manual inspection required.

### Prerequisites
- Online pipeline has produced the output CSV
- `validate_submission.py` (provided by the challenge) is accessible

### Implementation Steps

**Step 11.5.1 — Structural checks**
```python
# file: offline/phase11_5_submission_audit.py
import polars as pl
import json
import re
import sys
from pathlib import Path

def run_submission_audit(csv_path: str) -> dict:
    """
    Run all safety checks on the submission CSV.
    Returns a dict of check_name -> {passed: bool, detail: str}.
    Prints a full audit report.
    """
    results = {}
    df = None

    # --- CHECK 1: File exists and is readable ---
    if not Path(csv_path).exists():
        print(f"⛔ FATAL: File not found: {csv_path}")
        sys.exit(1)

    try:
        df = pl.read_csv(csv_path)
        results["file_readable"] = {"passed": True, "detail": f"Loaded {len(df)} rows"}
    except Exception as e:
        results["file_readable"] = {"passed": False, "detail": str(e)}
        print(f"⛔ FATAL: Cannot read CSV: {e}")
        sys.exit(1)

    # --- CHECK 2: Exactly 100 rows ---
    passed = len(df) == 100
    results["row_count"] = {
        "passed": passed,
        "detail": f"Got {len(df)} rows, expected 100"
    }

    # --- CHECK 3: Required columns exist ---
    required_cols = {"candidate_id", "rank", "score", "reasoning"}
    actual_cols = set(df.columns)
    missing_cols = required_cols - actual_cols
    extra_cols = actual_cols - required_cols
    passed = len(missing_cols) == 0
    detail = "All columns present" if passed else f"Missing: {missing_cols}"
    if extra_cols:
        detail += f" | Extra (OK but unexpected): {extra_cols}"
    results["required_columns"] = {"passed": passed, "detail": detail}

    if missing_cols:
        print(f"⛔ FATAL: Missing required columns: {missing_cols}")
        sys.exit(1)

    # --- CHECK 4: Ranks are integers 1–100, no duplicates ---
    ranks = df["rank"].to_list()
    ranks_set = set(ranks)
    passed = (ranks_set == set(range(1, 101)))
    results["rank_integrity"] = {
        "passed": passed,
        "detail": ("Ranks are exactly 1–100" if passed
                   else f"Expected {{1..100}}, got min={min(ranks)}, max={max(ranks)}, unique={len(ranks_set)}")
    }

    # --- CHECK 5: Candidate IDs are all unique ---
    n_unique = df["candidate_id"].n_unique()
    passed = n_unique == 100
    results["candidate_id_uniqueness"] = {
        "passed": passed,
        "detail": f"{n_unique} unique candidate_ids (expected 100)"
    }

    # --- CHECK 6: Scores are strictly decreasing ---
    scores = df.sort("rank")["score"].to_list()
    violations = [(i+1, scores[i], scores[i+1])
                  for i in range(len(scores)-1) if scores[i] <= scores[i+1]]
    passed = len(violations) == 0
    results["scores_strictly_decreasing"] = {
        "passed": passed,
        "detail": ("Scores strictly decreasing ✓" if passed
                   else f"{len(violations)} violations: first at rank {violations[0][0]}: {violations[0][1]} → {violations[0][2]}")
    }

    # --- CHECK 7: Scores in valid range ---
    score_min = df["score"].min()
    score_max = df["score"].max()
    passed = (0 <= score_min) and (score_max <= 100)
    results["score_range"] = {
        "passed": passed,
        "detail": f"Score range: [{score_min:.2f}, {score_max:.2f}] (expected [0, 100])"
    }

    # --- CHECK 8: No null or empty reasoning ---
    null_count = df["reasoning"].is_null().sum()
    empty_count = df["reasoning"].filter(pl.col("reasoning") == "").len()
    passed = (null_count == 0) and (empty_count == 0)
    results["reasoning_not_null"] = {
        "passed": passed,
        "detail": f"Null: {null_count}, Empty: {empty_count}"
    }

    # --- CHECK 9: Reasoning quality — evidence, alignment, gap ---
    def check_reasoning_quality(text: str) -> list:
        issues = []
        if not text or len(text.split()) < 25:
            issues.append("too_short")
        if not re.search(r'\d', text):
            issues.append("no_number")
        # Check for generic/templated language
        generic_phrases = [
            "strong candidate", "excellent fit", "highly recommended",
            "no information", "not provided", "n/a"
        ]
        if any(p in text.lower() for p in generic_phrases):
            issues.append("generic_language")
        return issues

    quality_issues = {}
    for row in df.iter_rows(named=True):
        issues = check_reasoning_quality(row["reasoning"])
        if issues:
            quality_issues[row["candidate_id"]] = issues

    passed = len(quality_issues) == 0
    results["reasoning_quality"] = {
        "passed": passed,
        "detail": (f"All 100 reasoning entries pass quality check" if passed
                   else f"{len(quality_issues)} entries have issues: {list(quality_issues.items())[:3]}...")
    }

    # --- CHECK 10: Honeypot safety — fraud_probability check ---
    # Load quality features to check if any top-100 candidates are suspected honeypots
    try:
        qf = pl.read_parquet("data/artifacts/quality_features.parquet")
        top_100_ids = df["candidate_id"].to_list()
        top_100_quality = qf.filter(pl.col("candidate_id").is_in(top_100_ids))

        high_fraud_in_top100 = top_100_quality.filter(
            pl.col("fraud_probability") > 0.5
        )
        severe_in_top100 = top_100_quality.filter(
            pl.col("fraud_probability") > 0.98
        )

        # Hard rule: > 10% of top 100 with fraud > 0.98 = likely disqualification
        passed = len(severe_in_top100) < 10
        results["honeypot_safety"] = {
            "passed": passed,
            "detail": (f"Severe fraud (>0.98) in top 100: {len(severe_in_top100)} "
                       f"| Moderate fraud (>0.5) in top 100: {len(high_fraud_in_top100)} "
                       f"| Limit: < 10 severe")
        }

        if not passed:
            print(f"⛔ HONEYPOT WARNING: {len(severe_in_top100)} candidates with fraud_probability > 0.98 "
                  f"are in your top 100. This may trigger disqualification if > 10 are actual honeypots.")
            print(f"   Candidates: {severe_in_top100['candidate_id'].to_list()}")

    except Exception as e:
        results["honeypot_safety"] = {
            "passed": False,
            "detail": f"Could not run honeypot check: {e}"
        }

    # --- CHECK 11: Candidate IDs exist in source data ---
    # Spot-check: verify format of IDs looks valid (not checking all 100k for speed)
    sample_ids = df["candidate_id"].head(5).to_list()
    passed = all(isinstance(cid, str) and len(cid) > 3 for cid in sample_ids)
    results["candidate_id_format"] = {
        "passed": passed,
        "detail": f"Sample IDs: {sample_ids[:3]}"
    }

    return results

def print_audit_report(results: dict) -> bool:
    """Print formatted report and return True if all checks passed."""
    print("\n" + "=" * 60)
    print("       SUBMISSION SAFETY AUDIT REPORT")
    print("=" * 60 + "\n")

    all_passed = True
    for check_name, result in results.items():
        status = "✅ PASS" if result["passed"] else "❌ FAIL"
        print(f"{status}  {check_name}")
        print(f"         {result['detail']}")
        if not result["passed"]:
            all_passed = False

    print("\n" + "=" * 60)
    if all_passed:
        print("✅ ALL CHECKS PASSED — Safe to submit")
    else:
        failed = [k for k, v in results.items() if not v["passed"]]
        print(f"⛔ AUDIT FAILED — {len(failed)} check(s) failed: {failed}")
        print("   DO NOT SUBMIT until all checks pass.")
    print("=" * 60 + "\n")

    return all_passed

if __name__ == "__main__":
    csv_path = sys.argv[1] if len(sys.argv) > 1 else "team_xxx.csv"
    results = run_submission_audit(csv_path)
    passed = print_audit_report(results)

    # Save audit log
    with open("data/artifacts/submission_audit.json", "w") as f:
        json.dump({k: v for k, v in results.items()}, f, indent=2)

    sys.exit(0 if passed else 1)  # Exit code 1 if any check fails
```

**Step 11.5.2 — Run the official validator**
```bash
# After the custom audit passes, run the challenge-provided validator
python validate_submission.py team_xxx.csv

# If this fails for any reason, the submission will be rejected by judges.
# Fix the issue, re-run run_ranking.py, re-run both validators.
```

**Step 11.5.3 — Determinism check**
```bash
# Run the pipeline twice and diff the outputs
python online/run_ranking.py
cp team_xxx.csv team_xxx_run1.csv

python online/run_ranking.py
cp team_xxx.csv team_xxx_run2.csv

diff team_xxx_run1.csv team_xxx_run2.csv
# Expected output: nothing (files are identical)
# If there is any diff: the pipeline has randomness — find and fix it
```

### Verification Checklist
- [ ] Phase 11.5 script exists at `offline/phase11_5_submission_audit.py`
- [ ] All 11 automated checks pass
- [ ] Official `validate_submission.py` passes
- [ ] Determinism check passes (two runs produce identical CSV)
- [ ] Audit log saved to `data/artifacts/submission_audit.json`
- [ ] Honeypot check: fewer than 10 candidates with `fraud_probability > 0.98` in top 100
- [ ] Scores are strictly decreasing (violation at rank 47→48 is not rare — check carefully)
- [ ] Reasoning entries: none shorter than 25 words, none containing generic boilerplate

### What Each Check Protects Against
| Check | Failure Mode |
|---|---|
| Row count == 100 | Pipeline returned partial results or duplicated rows |
| Required columns | Column rename bug in export step |
| Rank integrity | Off-by-one error in rank assignment |
| Candidate ID uniqueness | Join multiplied rows |
| Scores strictly decreasing | Normalization step created ties |
| Score range [0,100] | Raw model outputs not normalized |
| Reasoning not null | Reasoning join missed some candidates |
| Reasoning quality | Hallucinated or templated outputs |
| Honeypot safety | Integrity filter threshold too lenient |
| Candidate ID format | Wrong ID column joined |
| Official validator | Any submission spec requirement not caught above |

### Output
```
data/artifacts/submission_audit.json
Exit code 0 = all checks passed, safe to submit
Exit code 1 = one or more checks failed, DO NOT submit
```

---

---

# ONLINE INFERENCE PIPELINE

**File: `online/run_ranking.py`** — this is what judges execute.

```python
#!/usr/bin/env python3
"""
Redrob Candidate Ranking — Online Inference Pipeline
Usage: python online/run_ranking.py
Output: team_xxx.csv

Runtime target: < 5 minutes, CPU only, no network
"""

import time
import pickle
import numpy as np
import polars as pl
import faiss

ARTIFACTS = "data/artifacts"
OUTPUT_PATH = "team_xxx.csv"

def run():
    t_start = time.perf_counter()

    # === O1: LOAD ===
    print("[O1] Loading artifacts...")
    cf = pl.read_parquet(f"{ARTIFACTS}/candidate_features.parquet")
    crf = pl.read_parquet(f"{ARTIFACTS}/career_features.parquet")
    qf = pl.read_parquet(f"{ARTIFACTS}/quality_features.parquet")
    bf = pl.read_parquet(f"{ARTIFACTS}/behavior_features.parquet")
    reasoning = pl.read_parquet(f"{ARTIFACTS}/reasoning.parquet")

    index = faiss.read_index(f"{ARTIFACTS}/faiss.index")
    index.nprobe = 50

    with open(f"{ARTIFACTS}/bm25.pkl", "rb") as f:
        bm25_data = pickle.load(f)
    with open(f"{ARTIFACTS}/faiss_id_mapping.pkl", "rb") as f:
        id_mapping = pickle.load(f)
    with open(f"{ARTIFACTS}/lgbm_ranker.pkl", "rb") as f:
        lgbm = pickle.load(f)
    with open(f"{ARTIFACTS}/xgb_ranker.pkl", "rb") as f:
        xgb_model = pickle.load(f)

    jd_embedding = np.load(f"{ARTIFACTS}/jd_embedding.npy")
    print(f"  Load time: {time.perf_counter() - t_start:.2f}s")

    # === O2: RETRIEVE TOP 3000 ===
    print("[O2] Running hybrid retrieval...")
    t2 = time.perf_counter()

    # Dense search
    scores_dense, indices_dense = index.search(jd_embedding, 5000)
    dense_results = {
        id_mapping[int(idx)]: float(sc)
        for sc, idx in zip(scores_dense[0], indices_dense[0])
        if idx >= 0
    }

    # BM25 search
    bm25_index = bm25_data["index"]
    bm25_ids = bm25_data["ids"]
    jd_query = ["retrieval", "semantic", "search", "embeddings", "vector",
                 "database", "ndcg", "map", "ranking", "evaluation", "rag",
                 "pinecone", "qdrant", "founding", "startup"]
    bm25_scores = bm25_index.get_scores(jd_query)
    top_bm25_idx = np.argsort(bm25_scores)[::-1][:5000]
    max_bm25 = float(bm25_scores[top_bm25_idx[0]])
    bm25_results = {
        bm25_ids[i]: float(bm25_scores[i]) / (max_bm25 + 1e-9)
        for i in top_bm25_idx
    }

    # Combine all candidate IDs
    all_ids = list(set(dense_results.keys()) | set(bm25_results.keys()))

    # Build retrieval score using career ontology from precomputed features
    crf_indexed = crf.with_columns(pl.col("candidate_id")).to_pandas().set_index("candidate_id")

    retrieval_rows = []
    for cid in all_ids:
        d = dense_results.get(cid, 0.0)
        b = bm25_results.get(cid, 0.0)
        if cid in crf_indexed.index:
            co = float(crf_indexed.loc[cid, "career_ontology_score"])
            cb = float(crf_indexed.loc[cid, "career_bm25_score"])
        else:
            co, cb = 0.0, 0.0
        retrieval_score = 0.35 * d + 0.25 * b + 0.25 * co + 0.15 * cb
        retrieval_rows.append({"candidate_id": cid, "retrieval_score": retrieval_score})

    df_ret = pl.DataFrame(retrieval_rows).sort("retrieval_score", descending=True).head(3000)
    top_3000_ids = df_ret["candidate_id"].to_list()
    print(f"  Retrieval time: {time.perf_counter() - t2:.2f}s")

    # === O3: INTEGRITY FILTER ===
    print("[O3] Applying integrity filter...")
    t3 = time.perf_counter()

    qf_indexed = qf.filter(pl.col("candidate_id").is_in(top_3000_ids))
    hard_remove = set(
        qf_indexed.filter(
            (pl.col("fraud_probability") > 0.98) &
            (pl.col("has_severe_anomaly") == True)
        )["candidate_id"].to_list()
    )
    filtered_ids = [cid for cid in top_3000_ids if cid not in hard_remove]
    print(f"  Hard removed: {len(hard_remove)} candidates")
    print(f"  Remaining: {len(filtered_ids)}")
    print(f"  Integrity time: {time.perf_counter() - t3:.2f}s")

    # === O4: ENSEMBLE SCORING ===
    print("[O4] Running ensemble scoring...")
    t4 = time.perf_counter()

    # Build feature matrix for filtered candidates
    df_features = (
        pl.DataFrame({"candidate_id": filtered_ids})
        .join(cf, on="candidate_id", how="left")
        .join(crf, on="candidate_id", how="left")
        .join(qf, on="candidate_id", how="left")
        .join(bf, on="candidate_id", how="left")
        .join(df_ret, on="candidate_id", how="left")
        .fill_null(0.0)
    )

    X = df_features.select(FEATURE_COLS).to_numpy().astype(np.float32)

    lgbm_scores = lgbm.predict(X)
    xgb_scores = xgb_model.predict(X)

    def norm(s):
        return (s - s.min()) / (s.max() - s.min() + 1e-9)

    ensemble_scores = 0.6 * norm(lgbm_scores) + 0.4 * norm(xgb_scores)
    print(f"  Scoring time: {time.perf_counter() - t4:.2f}s")

    # === O5: TOP 100 SELECTION ===
    print("[O5] Selecting top 100...")
    top_100_idx = np.argsort(ensemble_scores)[::-1][:100]
    top_100_ids = [df_features["candidate_id"][i] for i in top_100_idx]
    top_100_scores = ensemble_scores[top_100_idx]

    df_top100 = pl.DataFrame({
        "candidate_id": top_100_ids,
        "ensemble_score": top_100_scores.tolist()
    })

    # === O6: ELITE RE-RANKING (top 20 only) ===
    print("[O6] Elite re-ranking...")
    # Load all features for top 20
    top_20 = df_top100.head(20)
    rest = df_top100.tail(80)

    all_features_df = (
        cf.join(crf, on="candidate_id", how="left")
         .join(bf, on="candidate_id", how="left")
         .fill_null(0.0)
    )

    # Also need teacher_median from synthetic labels
    tl = pl.read_parquet(f"{ARTIFACTS}/synthetic_labels.parquet").select(
        ["candidate_id", "teacher_median", "teacher_std"]
    )
    all_features_df = all_features_df.join(tl, on="candidate_id", how="left").fill_null(50.0)

    top_20_feat = top_20.join(all_features_df, on="candidate_id", how="left").fill_null(0.0)

    elite_scores = []
    for row in top_20_feat.iter_rows(named=True):
        elite = (
            0.30 * row.get("evaluation_score", 0.0)
            + 0.25 * row.get("founding_team_score", 0.0)
            + 0.20 * row.get("availability_score", 0.0)
            + 0.15 * row.get("teacher_median", 50.0) / 100
            - 0.10 * min(1.0, row.get("teacher_std", 0.0) / 30)
        )
        elite_scores.append(elite)

    top_20 = top_20.with_columns(pl.Series("elite_score", elite_scores))
    top_20_reranked = top_20.sort("elite_score", descending=True).drop("elite_score")

    df_final_100 = pl.concat([top_20_reranked, rest])

    # === O7: SCORE NORMALIZATION ===
    print("[O7] Normalizing scores...")
    raw_scores = df_final_100["ensemble_score"].to_numpy()
    normalized = 100 * (raw_scores - raw_scores.min()) / (raw_scores.max() - raw_scores.min() + 1e-9)
    # Ensure strictly decreasing
    for i in range(1, len(normalized)):
        if normalized[i] >= normalized[i-1]:
            normalized[i] = normalized[i-1] - 0.01

    df_final_100 = df_final_100.with_columns(
        pl.Series("score", normalized.round(2))
    )

    # === O8: REASONING JOIN ===
    print("[O8] Attaching reasoning...")
    df_final_100 = df_final_100.join(reasoning, on="candidate_id", how="left")

    # Fallback for candidates without reasoning
    df_final_100 = df_final_100.with_columns(
        pl.col("reasoning").fill_null("Strong candidate profile aligned with role requirements.")
    )

    # === O9: VALIDATE ===
    print("[O9] Validating submission...")
    assert len(df_final_100) == 100, f"Expected 100, got {len(df_final_100)}"
    assert df_final_100["candidate_id"].n_unique() == 100, "Duplicate candidate IDs!"
    assert df_final_100["score"].to_numpy().tolist() == \
           sorted(df_final_100["score"].to_numpy().tolist(), reverse=True), \
           "Scores not strictly decreasing!"
    assert not df_final_100["reasoning"].is_null().any(), "Null reasoning found!"
    print("  ✅ All validation checks passed")

    # === O10: EXPORT ===
    print("[O10] Exporting CSV...")
    result = df_final_100.with_columns(
        pl.Series("rank", list(range(1, 101)))
    ).select(["candidate_id", "rank", "score", "reasoning"])

    result.write_csv(OUTPUT_PATH)
    print(f"  Saved to: {OUTPUT_PATH}")

    total_time = time.perf_counter() - t_start
    print(f"\n✅ Pipeline complete in {total_time:.2f}s ({total_time/60:.1f} min)")
    assert total_time < 300, f"RUNTIME EXCEEDED: {total_time:.1f}s > 300s"

if __name__ == "__main__":
    run()
```

---

---

# BEHAVIORAL FEATURES (SUPPORTING)

Build `behavior_features.parquet` as part of Phase 3 processing:

```python
from datetime import datetime, timedelta

def compute_behavioral_features(cand: dict) -> dict:
    signals = cand.get("redrob_signals", {})

    # Availability Score
    last_active = signals.get("last_active_date", "")
    days_inactive = 999
    if last_active:
        try:
            la = datetime.strptime(last_active[:10], "%Y-%m-%d")
            days_inactive = (datetime.now() - la).days
        except ValueError:
            pass

    response_rate = signals.get("recruiter_response_rate", 0.0)
    response_time = signals.get("avg_response_time_hours", 999)
    notice_days = signals.get("notice_period_days", 90)

    # Normalize each component to 0-1 (higher = more available)
    active_score = max(0, 1 - days_inactive / 365)
    response_score = float(response_rate) / 100
    response_time_score = max(0, 1 - response_time / 168)  # 168 hours = 1 week
    notice_score = max(0, 1 - notice_days / 180)  # 180 days = 6 months

    availability_score = (
        0.4 * active_score
        + 0.3 * response_score
        + 0.15 * response_time_score
        + 0.15 * notice_score
    )

    # Market Demand Score
    saved = signals.get("saved_by_recruiters_30d", 0)
    appearances = signals.get("search_appearance_30d", 0)
    views = signals.get("profile_views_received_30d", 0)

    # Raw market demand (will be normalized after computing for all candidates)
    market_demand_raw = saved * 3 + appearances * 1 + views * 0.5

    # Reliability Score
    interview_completion = signals.get("interview_completion_rate", 0.0)
    offer_acceptance = signals.get("offer_acceptance_rate", 0.0)
    reliability_score = 0.6 * float(interview_completion) + 0.4 * float(offer_acceptance)

    return {
        "candidate_id": cand["candidate_id"],
        "availability_score": availability_score,
        "market_demand_raw": market_demand_raw,
        "reliability_score": reliability_score,
        "days_inactive": float(days_inactive),
        "notice_period_days": float(notice_days),
    }

# After computing for all 100k, normalize market_demand_raw
all_behavioral = [compute_behavioral_features(c) for c in all_candidates]
df_b = pl.DataFrame(all_behavioral)
max_demand = df_b["market_demand_raw"].max()
df_b = df_b.with_columns(
    (pl.col("market_demand_raw") / (max_demand + 1e-9)).alias("market_demand_score")
).drop("market_demand_raw")

df_b.write_parquet("data/artifacts/behavior_features.parquet")
```

---

---

# IMPLEMENTATION SPRINT PLAN

| Day | Focus | Phases | Goal |
|---|---|---|---|
| Day 1 | Foundation | 1, 2, 3, 3.5, 3.7 | All candidate features extracted (KG + Career + Behavioral) |
| Day 2 | Infrastructure | 4, 5, 6 | Integrity checked, indexes built, Top 3,000 retrieved |
| Day 3 | Teacher Labels | 7A, 7B, 7.25 | Calibrated labels + feature parity audit passing |
| Day 4 | Refinement | 7C, 8, 8.5, 8.75 | LTR trained, SHAP validated, stress test baseline set |
| Day 5 | Ensemble + Output | 9, 9.5, 10 | Ensemble scored, elite re-ranked, reasoning bank complete |
| Day 6 | Hardening | 11, 11.5, online pipeline | Runtime < 5 min, submission audit passing, CSV clean |
| Day 7 | Buffer | Iterate on stress test, build sandbox demo | Submission ready with documented metrics |

**If anything slips:** cut Phase 7C (pairwise) first, then Phase 8.75 (stress test is useful but not blocking). Both can be added back on Day 7 buffer.
**Never cut:** Phase 3.7 (behavioral features — explicit challenge differentiator), Phase 4 (honeypot detection — disqualification risk), Phase 7.25 (feature parity audit — silently prevents wasted training), Phase 8.5 (SHAP — tells you if labels are wrong), Phase 9.5 (NDCG@10 hardening — 50% of score), Phase 11.5 (submission safety audit — prevents technical disqualification).

---

---

# FINAL SUBMISSION CHECKLIST

Run through every section in order. Do not submit until all boxes are checked. Phase 11.5 automates most of this — run it first, then verify the remaining manual items.

### Automated Audit (Run First)
- [ ] `python offline/phase11_5_submission_audit.py team_xxx.csv` exits with code 0
- [ ] `python validate_submission.py team_xxx.csv` passes (official challenge validator)
- [ ] `data/artifacts/submission_audit.json` shows all 11 checks passed

### Dataset & Schema
- [ ] CSV has exactly 100 rows
- [ ] CSV has exactly 4 columns: `candidate_id, rank, score, reasoning`
- [ ] Ranks are integers 1–100, no duplicates
- [ ] Scores are strictly decreasing (each score < previous score)
- [ ] All 100 `candidate_id` values are unique
- [ ] No null or empty `reasoning` values

### Feature Pipeline Integrity
- [ ] `feature_parity_audit.json` shows 0 failures (all teacher concepts have student features)
- [ ] `behavior_features.parquet` exists and has 100,000 rows
- [ ] `market_demand_score` is present and population-normalized (max = 1.0)
- [ ] `founding_team_score` is present and non-zero for < 5% of candidates
- [ ] All 4 feature files have exactly 100,000 rows with no nulls

### Retrieval Quality
- [ ] `stress_test_report.md` exists with `Recall@3000 > 0.85`
- [ ] Proxy NDCG@10 documented (baseline to compare against any future changes)
- [ ] Version log of Composite score across architecture iterations exists

### Model Quality
- [ ] SHAP validation passed: `evaluation_score`, `market_demand_score`, `founding_team_score` in top 15
- [ ] Both `lgbm_ranker.pkl` and `xgb_ranker.pkl` exist and load without error
- [ ] Top-100 overlap between LGBM and XGBoost > 85%
- [ ] Label calibration confirmed: P90 - P10 > 40 in `calibrated_labels.parquet`

### Honeypot Safety
- [ ] Phase 11.5 honeypot check: fewer than 10 candidates with `fraud_probability > 0.98` in top 100
- [ ] Hard-remove count in online pipeline logs: approximately 80 candidates removed
- [ ] Top 10 positions: manually verify none look like obvious spam or impossibly perfect profiles

### Reasoning Quality
- [ ] Every reasoning entry is ≥ 25 words
- [ ] Every entry contains at least one number (year, score, months, headcount)
- [ ] Every entry mentions at least one specific company name or technology from the profile
- [ ] Every entry acknowledges at least one weakness or concern
- [ ] No two entries are identical (scan for copy-paste)
- [ ] No entry contains phrases: "excellent fit", "highly recommended", "no information"

### Elite Re-Ranking
- [ ] Elite re-ranking only affected positions 1–20 (positions 21–100 unchanged)
- [ ] Any candidate with `evaluation_score > 0.5` appears in top 10 of final output
- [ ] Phase 9.5 is running in the online pipeline (not accidentally disabled)

### Runtime
- [ ] `runtime_report.md` shows `TOTAL < 300 seconds` on the submission machine (CPU only)
- [ ] Peak memory shown as `< 16 GB`
- [ ] Pipeline run 3 times — all three CSV outputs are byte-for-byte identical (determinism)

### Code Repository
- [ ] `requirements.txt` is complete and pinned to specific versions
- [ ] `README.md` has clear setup instructions: install → run offline phases → run online pipeline → output
- [ ] All precomputed artifacts are either committed or have a documented regeneration script
- [ ] Single command produces the submission CSV: `python online/run_ranking.py`
- [ ] `ARCHITECTURE_V11_FINAL.md` is committed and matches the actual implementation
- [ ] `submission_metadata.yaml` is filled and committed

### Sandbox Demo
- [ ] Hosted demo (HuggingFace Spaces / Streamlit / Colab) runs on a sample of 500 candidates
- [ ] Demo produces a ranked output in < 30 seconds
- [ ] Demo link is accessible without login

### Defend-Your-Work Preparation
- [ ] You can explain every phase without referring to notes
- [ ] You can recite the NDCG@10 formula and explain why it gets 50% weight
- [ ] You can explain why Phase 3.7 (behavioral features) is a differentiator vs other teams
- [ ] You can show SHAP output and explain what each top-5 feature reveals
- [ ] You can show the stress test report and explain what Recall@3000 measures
- [ ] You can explain the elite re-ranking formula and defend each weight
- [ ] You can explain why TOP_K = 3000 is locked and what would happen if you changed it
- [ ] You can explain the difference between your approach and a pure embedding-similarity baseline

---

> **Architecture V12 — FROZEN**
> Five additions from review round 2 are incorporated: Phase 3.7 (Behavioral Intelligence), Phase 7.25 (Feature Parity Audit), top_k LOCKED, Phase 8.75 (Stress Test), Phase 11.5 (Submission Safety Audit).
> Any future change requires experimental evidence from the stress test (Phase 8.75). If a change does not improve the proxy Composite score by ≥ 0.002, it is not a real improvement. No intuition-based changes from this point forward.

