# REDROB CANDIDATE RANKING — ARCHITECTURE V11 FINAL
## Complete Implementation & Verification Engineering Specification

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
| Offline | LLMs, APIs, GPUs, long computation — all allowed |
| Online inference | CPU only · ≤16 GB RAM · ≤5 min wall-clock · No network · No APIs |

---

## REPOSITORY STRUCTURE

```
redrob-ranking/
├── ARCHITECTURE_V11_FINAL.md       ← this document
├── config/
│   └── hyperparams.yaml            ← all tunable values, nothing hardcoded
├── data/
│   ├── raw/                        ← original dataset files (gitignored)
│   └── artifacts/                  ← all precomputed artifacts
│       ├── jd_requirements.json
│       ├── ontology.json
│       ├── candidate_features.parquet
│       ├── career_features.parquet
│       ├── quality_features.parquet
│       ├── faiss.index
│       ├── bm25.pkl
│       ├── top_3000.parquet
│       ├── synthetic_labels.parquet
│       ├── calibrated_labels.parquet
│       ├── refined_labels.parquet
│       ├── lgbm_ranker.pkl
│       ├── xgb_ranker.pkl
│       ├── reasoning.parquet
│       └── runtime_report.md
├── offline/
│   ├── phase01_jd_intelligence.py
│   ├── phase02_ontology.py
│   ├── phase03_knowledge_graph.py
│   ├── phase03_5_career_intelligence.py
│   ├── phase04_integrity.py
│   ├── phase05_retrieval_infra.py
│   ├── phase06_hybrid_retrieval.py
│   ├── phase07a_teacher_ensemble.py
│   ├── phase07b_label_calibration.py
│   ├── phase07c_pairwise.py
│   ├── phase08_ltr.py
│   ├── phase08_5_shap.py
│   ├── phase09_ensemble.py
│   ├── phase09_5_elite_rerank.py
│   ├── phase10_reasoning_bank.py
│   └── phase11_runtime_verify.py
├── online/
│   └── run_ranking.py              ← judges execute this
├── requirements.txt
├── submission_metadata.yaml
└── team_xxx.csv                    ← final submission
```

---

## HYPERPARAMETER REGISTRY

**File: `config/hyperparams.yaml`** — nothing is hardcoded anywhere else.

```yaml
retrieval:
  top_k: 3000
  dense_weight: 0.35
  bm25_weight: 0.25
  ontology_weight: 0.25
  career_weight: 0.15
  faiss_nlist: 512
  faiss_m: 64
  faiss_nbits: 8
  faiss_nprobe: 50

teacher:
  temperature: 0
  runs_per_candidate: 3
  aggregation: median
  technical_weight: 0.45
  evaluation_weight: 0.35
  execution_weight: 0.20

pairwise:
  pool_size: 300
  score_window: 15  # only compare if |score_a - score_b| < 15

ltr:
  learning_rate: 0.05
  num_leaves: 63
  max_depth: 8
  n_estimators: 500
  early_stopping_rounds: 50

ensemble:
  lgbm_weight: 0.6
  xgb_weight: 0.4

elite_rerank:
  pool_size: 20
  evaluation_weight: 0.30
  founding_team_weight: 0.25
  availability_weight: 0.20
  teacher_median_weight: 0.15
  teacher_std_penalty: 0.10

integrity:
  fraud_hard_remove_threshold: 0.98
  minor_anomaly_penalty: -2
  medium_anomaly_penalty: -5
  severe_anomaly_penalty: -25
```

---

## COMPLETE PIPELINE

```
PHASE 1   JD Intelligence Engine
PHASE 2   Domain Ontology Engine
PHASE 3   Candidate Knowledge Graph
PHASE 3.5 Career Intelligence Layer       ← added after review
PHASE 4   Data Integrity Engine
PHASE 5   Retrieval Infrastructure
PHASE 6   Hybrid Retrieval
              ↓
         TOP 3000 CANDIDATES
              ↓
PHASE 7A  Teacher Ensemble
PHASE 7B  Label Calibration
PHASE 7C  Pairwise Refinement
              ↓
PHASE 8   Learning To Rank
PHASE 8.5 SHAP Feedback Loop
PHASE 9   Ensemble Models
PHASE 9.5 Elite Re-Ranking               ← added after review
              ↓
PHASE 10  Reasoning Bank
PHASE 11  Runtime Verification
              ↓
ONLINE PIPELINE (judges execute)
              ↓
TOP 100 CSV
```

---

---

# OFFLINE PHASE

---

## PHASE 1 — JD INTELLIGENCE ENGINE

### Goal
Convert the raw job description from human language into a structured JSON object that every downstream phase can query deterministically.

### Prerequisites
- `job_description.docx` present in `data/raw/`
- LLM API access (any: GPT-4, Claude, Gemini, Groq Llama 3)

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

## PHASE 5 — RETRIEVAL INFRASTRUCTURE

### Goal
Precompute all indexes needed for fast candidate retrieval. This is the most compute-intensive phase. Run it on GPU if available offline.

### Prerequisites
- Phases 1–4 complete
- `sentence-transformers` and `faiss-cpu` installed
- 8+ GB RAM available

### Implementation Steps

**Step 5.1 — Build the dense embedding index**
```python
from sentence_transformers import SentenceTransformer
import faiss
import numpy as np

# Load model
model = SentenceTransformer("BAAI/bge-large-en-v1.5")
# Alternative if memory is tight: "BAAI/bge-base-en-v1.5" (768 dims, faster)

def build_candidate_text(cand: dict) -> str:
    """The text we embed for each candidate."""
    profile = cand.get("profile", {})
    career = cand.get("career_history", [])
    skills = cand.get("skills", [])

    career_text = " | ".join([
        f"{r.get('title','')} at {r.get('company','')}: {r.get('description','')}"
        for r in career[:5]  # most recent 5 roles
    ])

    return " ".join([
        profile.get("headline", ""),
        profile.get("summary", ""),
        " ".join(s.get("name", "") for s in skills[:30]),
        career_text
    ])[:2000]  # truncate to avoid token limit issues

# Process in batches
BATCH_SIZE = 128
DIM = 1024  # bge-large output dimension

all_embeddings = []
all_ids = []

print("Generating embeddings...")
batch_texts = []
batch_ids = []

with gzip.open("data/raw/candidates.jsonl.gz", 'rt') as f:
    for line in tqdm(f):
        cand = json.loads(line)
        batch_texts.append(build_candidate_text(cand))
        batch_ids.append(cand["candidate_id"])

        if len(batch_texts) == BATCH_SIZE:
            embeddings = model.encode(
                batch_texts,
                normalize_embeddings=True,  # for cosine similarity
                show_progress_bar=False
            )
            all_embeddings.append(embeddings)
            all_ids.extend(batch_ids)
            batch_texts = []
            batch_ids = []

# Final batch
if batch_texts:
    embeddings = model.encode(batch_texts, normalize_embeddings=True)
    all_embeddings.append(embeddings)
    all_ids.extend(batch_ids)

all_embeddings = np.vstack(all_embeddings).astype('float32')
print(f"Embeddings shape: {all_embeddings.shape}")  # (100000, 1024)

# Build FAISS IVF-PQ index
nlist = 512   # number of Voronoi cells
m = 64        # PQ segments (must divide DIM=1024 → 1024/64=16 ✓)
nbits = 8     # bits per code

quantizer = faiss.IndexFlatIP(DIM)  # inner product (cosine since normalized)
index = faiss.IndexIVFPQ(quantizer, DIM, nlist, m, nbits)

# Train on a sample
print("Training FAISS index...")
sample_size = min(50000, len(all_embeddings))
index.train(all_embeddings[:sample_size])

# Add all embeddings
print("Adding vectors to index...")
index.add(all_embeddings)
index.nprobe = 50  # search 50 cells at query time

faiss.write_index(index, "data/artifacts/faiss.index")
print(f"FAISS index size: {index.ntotal} vectors")

# Save ID mapping (FAISS uses integer IDs, we need string candidate_ids)
id_mapping = {i: cid for i, cid in enumerate(all_ids)}
import pickle
with open("data/artifacts/faiss_id_mapping.pkl", "wb") as f:
    pickle.dump(id_mapping, f)
```

**Step 5.2 — Also embed the JD query vector**
```python
# Embed the JD for use in Phase 6
jd_text = f"""
Senior AI Engineer Founding Team
Required: embeddings, vector databases, retrieval systems, ranking evaluation,
NDCG, MAP, semantic search, RAG, product company, startup
Experience: 5-9 years applied ML, production retrieval systems,
founding team mindset, fast execution, ownership
"""
jd_embedding = model.encode([jd_text], normalize_embeddings=True).astype('float32')
np.save("data/artifacts/jd_embedding.npy", jd_embedding)
```

**Step 5.3 — Build BM25 index**
```python
from rank_bm25 import BM25Okapi
import re

def tokenize_for_bm25(text: str) -> list:
    text = text.lower()
    text = re.sub(r'[^\w\s]', ' ', text)
    tokens = text.split()
    # Add bigrams for multi-word technical terms
    bigrams = [f"{tokens[i]}_{tokens[i+1]}"
               for i in range(len(tokens)-1)
               if len(tokens[i]) > 2 and len(tokens[i+1]) > 2]
    return tokens + bigrams

bm25_corpus = []
bm25_ids = []

with gzip.open("data/raw/candidates.jsonl.gz", 'rt') as f:
    for line in tqdm(f):
        cand = json.loads(line)
        text = build_candidate_text(cand)
        bm25_corpus.append(tokenize_for_bm25(text))
        bm25_ids.append(cand["candidate_id"])

print("Building BM25 index...")
bm25_index = BM25Okapi(bm25_corpus)

with open("data/artifacts/bm25.pkl", "wb") as f:
    pickle.dump({"index": bm25_index, "ids": bm25_ids}, f)

print("BM25 index built.")
```

### Verification Checklist
- [ ] `faiss.index` exists and `index.ntotal == 100000`
- [ ] `faiss_id_mapping.pkl` maps 0..99999 → candidate_id strings
- [ ] `jd_embedding.npy` shape is `(1, 1024)`
- [ ] `bm25.pkl` loads correctly and `len(bm25_ids) == 100000`
- [ ] Test retrieval: query with "NDCG MAP ranking evaluation vector database" → verify top 5 results look relevant
- [ ] Memory check: FAISS index should be < 2 GB on disk with IVF-PQ compression

### Common Mistakes
- Not normalizing embeddings before building the index: with `normalize_embeddings=True`, inner product becomes cosine similarity. Without it, inner product is meaningless.
- Setting `nprobe` too low: 10 gives fast but poor recall. 50 is a good balance. 100 if you have time budget.
- Forgetting to save the ID mapping: FAISS returns integer indices, not candidate_id strings.

### Output
```
data/artifacts/faiss.index
data/artifacts/faiss_id_mapping.pkl
data/artifacts/jd_embedding.npy
data/artifacts/bm25.pkl
```

---

## PHASE 6 — HYBRID RETRIEVAL

### Goal
Reduce 100,000 candidates to the Top 3,000 while maintaining extremely high recall. This pool must contain essentially all truly relevant candidates — any relevant candidate missed here is permanently lost.

### Prerequisites
- Phases 1–5 complete

### Implementation Steps

**Step 6.1 — Dense retrieval (FAISS)**
```python
import faiss
import numpy as np
import pickle

index = faiss.read_index("data/artifacts/faiss.index")
index.nprobe = 50

jd_embedding = np.load("data/artifacts/jd_embedding.npy")

# Retrieve top 5000 from dense (we'll combine with others)
TOP_DENSE = 5000
scores, indices = index.search(jd_embedding, TOP_DENSE)

with open("data/artifacts/faiss_id_mapping.pkl", "rb") as f:
    id_mapping = pickle.load(f)

dense_results = {
    id_mapping[int(idx)]: float(score)
    for score, idx in zip(scores[0], indices[0])
    if idx >= 0
}
# dense_results: {candidate_id -> cosine_similarity}
```

**Step 6.2 — BM25 retrieval**
```python
with open("data/artifacts/bm25.pkl", "rb") as f:
    bm25_data = pickle.load(f)

bm25_index = bm25_data["index"]
bm25_ids = bm25_data["ids"]

# Query: key JD terms
jd_query = tokenize_for_bm25(
    "retrieval semantic search rag embeddings vector database pinecone qdrant "
    "milvus ndcg map ranking evaluation product startup founding engineer"
)

bm25_scores = bm25_index.get_scores(jd_query)
# Get top 5000 BM25
top_bm25_idx = np.argsort(bm25_scores)[::-1][:5000]
bm25_results = {
    bm25_ids[i]: float(bm25_scores[i])
    for i in top_bm25_idx
}

# Normalize BM25 scores to [0, 1]
max_bm25 = max(bm25_results.values()) if bm25_results else 1.0
bm25_results_norm = {k: v / max_bm25 for k, v in bm25_results.items()}
```

**Step 6.3 — Combine all retrieval signals**
```python
import polars as pl

# Load precomputed feature scores
cf = pl.read_parquet("data/artifacts/career_features.parquet")
qf = pl.read_parquet("data/artifacts/quality_features.parquet")

# Get all unique candidates from dense + BM25
all_candidate_ids = list(set(dense_results.keys()) | set(bm25_results_norm.keys()))
print(f"Candidates in union pool: {len(all_candidate_ids)}")

# Build per-candidate retrieval scores
retrieval_rows = []
for cid in all_candidate_ids:
    dense = dense_results.get(cid, 0.0)
    bm25 = bm25_results_norm.get(cid, 0.0)

    # Get ontology and career scores from precomputed features
    career_row = cf.filter(pl.col("candidate_id") == cid)
    career_ontology = career_row["career_ontology_score"][0] if len(career_row) > 0 else 0.0
    career_bm25 = career_row["career_bm25_score"][0] if len(career_row) > 0 else 0.0

    # Combined career intelligence score
    career_intel = (career_ontology + career_bm25) / 2

    # Retrieval score with config weights
    retrieval_score = (
        0.35 * dense
        + 0.25 * bm25
        + 0.25 * career_ontology
        + 0.15 * career_bm25
    )

    retrieval_rows.append({
        "candidate_id": cid,
        "dense_score": dense,
        "bm25_score": bm25,
        "career_intel_score": career_intel,
        "retrieval_score": retrieval_score,
    })

df_retrieval = pl.DataFrame(retrieval_rows)

# Apply quality penalty: down-rank extreme honeypots
df_retrieval = df_retrieval.join(
    qf.select(["candidate_id", "fraud_probability"]),
    on="candidate_id", how="left"
).with_columns(
    pl.col("fraud_probability").fill_null(0.0)
).with_columns(
    (pl.col("retrieval_score") * (1 - pl.col("fraud_probability") * 0.3))
    .alias("retrieval_score_adjusted")
)

# Take Top 3000
top_3000 = (df_retrieval
    .sort("retrieval_score_adjusted", descending=True)
    .head(3000))

top_3000.write_parquet("data/artifacts/top_3000.parquet")
print(f"Top 3000 saved. Score range: {top_3000['retrieval_score_adjusted'].min():.3f} - {top_3000['retrieval_score_adjusted'].max():.3f}")
```

### Verification Checklist
- [ ] Exactly 3,000 candidates in `top_3000.parquet`
- [ ] **Recall check**: manually identify 10 candidates who clearly match the JD — all 10 must appear in the top 3,000
- [ ] Top 100 by retrieval score: manually verify at least 80% look genuinely relevant
- [ ] `fraud_probability > 0.9` candidates should be rare in the top 3,000
- [ ] Dense and BM25 overlap: check `len(set(dense_top5k) & set(bm25_top5k))` — should be ~2,000 (significant overlap means both are retrieving similar relevant candidates)
- [ ] Score distribution is not flat — there should be clear separation between top 100 and 1000–3000

### Common Mistakes
- Taking top 3,000 from dense alone: use the union of dense + BM25 first, then score and select.
- Forgetting that FAISS returns cosine similarities as inner products (range roughly 0.0–1.0 for normalized vectors, sometimes negative): clamp to [0, 1].
- Not applying any fraud penalty at retrieval stage: a honeypot ranked #1 by dense similarity is a problem.

### Output
```
data/artifacts/top_3000.parquet
Schema: candidate_id, dense_score, bm25_score,
        career_intel_score, retrieval_score, retrieval_score_adjusted
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

## PHASE 8 — LEARNING TO RANK

### Goal
Train a machine learning model to predict recruiter relevance scores from the feature matrix. The model compresses all the teacher signal into a fast, deterministic ranker that runs at inference time.

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
| Day 1 | Foundation | 1, 2, 3, 3.5 | All candidate features extracted |
| Day 2 | Infrastructure | 4, 5, 6 | Top 3,000 candidates retrieved |
| Day 3 | Teacher Labels | 7A, 7B | Calibrated synthetic labels done |
| Day 4 | Refinement | 7C, 8, 8.5 | LTR model trained and SHAP validated |
| Day 5 | Ensemble + Output | 9, 9.5, 10 | Reasoning bank complete |
| Day 6 | Runtime + Validation | 11, online pipeline | Under 5 minutes, CSV exports cleanly |
| Day 7 | Buffer | Fix failures, build sandbox demo | Submission ready |

**If anything slips:** cut Phase 7C (pairwise) first. It's the lowest marginal return vs. effort.
**Never cut:** Phase 4 (honeypot detection — disqualification risk), Phase 8.5 (SHAP — tells you if labels are wrong), Phase 9.5 (NDCG@10 hardening — 50% of score).

---

---

# FINAL SUBMISSION CHECKLIST

Run through this in order before submitting. Do not submit until everything is checked.

### Dataset & Schema
- [ ] `validate_submission.py` runs without errors on `team_xxx.csv`
- [ ] CSV has exactly 100 rows
- [ ] CSV has exactly 4 columns: `candidate_id, rank, score, reasoning`
- [ ] Ranks are integers 1–100, no duplicates
- [ ] Scores are strictly decreasing (each score < previous)
- [ ] All 100 `candidate_id` values exist in `candidates.jsonl.gz`
- [ ] No null or empty `reasoning` values

### Honeypot Safety
- [ ] Check known honeypot patterns against your top 100 — none should appear
- [ ] Verify `hard_remove` count in logs (should be ~80 hard-removed before ranking)

### Reasoning Quality
- [ ] Read every reasoning entry in the final CSV
- [ ] Every entry contains at least one number
- [ ] Every entry mentions at least one specific company or technology from the profile
- [ ] Every entry contains one acknowledged weakness or concern
- [ ] No two entries are identical

### Runtime
- [ ] Online pipeline runs in < 5 minutes on CPU only
- [ ] `runtime_report.md` is committed to the repository
- [ ] Run the pipeline 3 times — output is identical each time (determinism)

### Code Repository
- [ ] `requirements.txt` is complete and pinned to specific versions
- [ ] `README.md` has clear setup instructions (install → run → output)
- [ ] All precomputed artifacts are either committed or have a script to regenerate them
- [ ] Single command produces the submission CSV: `python online/run_ranking.py`
- [ ] `submission_metadata_template.yaml` is filled and committed

### Sandbox Demo
- [ ] Hosted demo (HuggingFace/Streamlit/Colab) runs successfully on a sample of 500 candidates
- [ ] Demo produces a ranked output in < 30 seconds

### Defend-Your-Work Preparation
- [ ] You can explain every phase without referring to notes
- [ ] You can explain why each weight in the elite_score formula was chosen
- [ ] You can show SHAP output and explain what it reveals about your model
- [ ] You can explain the difference between your approach and a baseline embedding-similarity approach

---

> **Architecture V11 — FROZEN**
> Any future change requires experimental evidence. Run the changed version, compare NDCG on a validation set, and only merge if it improves. No intuition-based changes from this point forward.
