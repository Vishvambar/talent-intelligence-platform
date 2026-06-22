# Phase 1: JD Intelligence Engine — Deep Implementation Spec

## 1. Executive Summary

Phase 1 is the critical entry point of the Redrob Candidate Ranking System. The core philosophy of this system is that **simple keyword matching is a trap**. A candidate might list all the right AI keywords but have a title like "Marketing Manager," while a perfect Tier-1 engineer might not explicitly mention "RAG" on their resume, even though their work implies it. 

To solve this, Phase 1 ingests the unstructured, human-written Job Description (`job_description.docx`) and converts it into a highly structured, machine-readable, schema-enforced JSON artifact (`jd_requirements.json`). This JSON acts as the deterministic source of truth that powers:
1. **Phase 2 (Domain Ontology Engine)**
2. **Phase 6 (Hybrid Retrieval)**
3. **Phase 7A (Teacher Ensemble Labeling)**

---

## 2. Shared LLM Infrastructure (`shared/llm/`)

Before extracting the JD, we built a robust LLM routing infrastructure. We recognized that depending on a single hardcoded LLM API is an anti-pattern. If Phase 7A requires generating thousands of evaluations and hits a `429 Rate Limit` or `503 Service Unavailable`, the pipeline halts. 

We solved this by introducing `shared/llm/router.py`.

### 2.1. Phase-Aware Routing
Instead of hardcoding "Use Gemini", the router reads `config/hyperparams.yaml` for a `provider_priority` chain mapped to the specific phase. 
* *Example Phase 1 priority:* `Gemini -> Cerebras -> Groq -> GitHub Models -> OpenRouter`.
* If Gemini exhausts its quota, the router seamlessly falls back to Cerebras without throwing an exception.

### 2.2. Pydantic Schema Enforcement & Retry Loops
LLMs frequently hallucinate formats (e.g., prepending `"Sure! Here is the JSON you requested:"` before the actual JSON block).
The router:
1. Strips markdown and conversational fluff.
2. Passes the raw JSON into Pydantic's `model_validate_json()`.
3. If Pydantic throws a `ValidationError` (e.g., because a confidence score was `17` instead of `< 1.0`), the router catches the exception and automatically retries the generation.

### 2.3. Versioned Prompt Caching
To prevent wasting tokens during pipeline debugging, the router implements `cache_version: v1`. 
* Every prompt + phase combination is hashed using `SHA-256`.
* If the exact same prompt is sent, the router instantly returns the cached JSON.
* If we update the prompt engineering logic, bumping `cache_version: v2` instantly invalidates the entire cache safely.

---

## 3. Data Ingestion

We specifically avoid reading from intermediate `.txt` dumps of the JD. If a recruiter updates the `.docx` file, the `.txt` file becomes stale, meaning the AI will evaluate candidates against outdated criteria.
* Phase 1 uses `python-docx` to read `data/raw/job_description.docx` dynamically at runtime, ensuring we always operate on the exact source of truth.

---

## 4. Multi-Perspective Prompt Engineering (The 3 Lenses)

Running the exact same LLM prompt 5 times at `temperature=0` wastes tokens and often yields 5 identical responses. Instead, Phase 1 forces the LLM to adopt three entirely different "Recruiter Personas" (Lenses) to extract maximum signal diversity:

### Lens A: Technical
* **Focus:** Strict engineering constraints.
* **Extraction Targets:** Specific frameworks (PyTorch), architecture paradigms (RAG), vector databases (Pinecone, FAISS), and evaluation frameworks (NDCG, MAP).

### Lens B: Execution & Product
* **Focus:** Shipping velocity and environmental fit.
* **Extraction Targets:** Evidence of "building from scratch", "shipping to real users", and "startup experience". It explicitly hunts for negative signals (e.g., "spent entire career in academic research labs with no production deployments").

### Lens C: Culture & Alignment
* **Focus:** Behavioral traits and work style.
* **Extraction Targets:** Ownership, async-first communication, fast failure. It explicitly looks for negative cultural markers like "title-chasers" or "framework enthusiasts".

---

## 5. Advanced Pydantic Output Schema

Phase 1 completely abandons binary `true/false` requirement tracking. The extracted JSON (`jd_requirements.json`) is heavily normalized.

### 5.1. `RequirementTrait` Configuration
For every extracted skill or trait, the schema demands:
* **`required`**: Boolean. Is this a hard blocker or a nice-to-have?
* **`importance`**: Integer (1-10). A vector database might be `10/10`, while LLM fine-tuning might be `4/10`.
* **`confidence`**: Float (0.0-1.0). How sure is the LLM that the JD actually asked for this?
* **`evidence`**: A list of direct string excerpts pulled straight from the JD. This guarantees the LLM isn't hallucinating requirements.
* **`canonical_terms` & `synonyms`**: Essential for Phase 2. Maps "vector database" to synonyms like "ANN search", "Pinecone", "Milvus".

### 5.2. `NegativeSignal` Configuration
The JD explicitly lists "Things we do NOT want." Phase 1 tracks these under a distinct `NegativeSignal` schema.
* Instead of a `required: true` flag (which is semantically incorrect for a negative trait), negative signals utilize a **`penalty_strength` (1-10)** metric.
* *Crucial Rule:* Company names (e.g., TCS, Infosys) are explicitly banned from the `synonyms` lists to prevent injecting systemic bias into the ranking algorithm. Instead, the LLM maps to structural descriptors like "IT Services" or "Client Consulting".

---

## 6. Median Aggregation Merging Logic

Once the 3 distinct lenses generate their respective JSON schemas, Phase 1 merges them into a single, cohesive master schema to act as the source of truth.

The merging rules are mathematically strict:
1. **Booleans (`required`)**: Majority vote. If 2 out of 3 lenses say a skill is required, it becomes required.
2. **Scores (`importance`, `confidence`, `penalty_strength`)**: **Median Aggregation**. We explicitly do *not* use the Average. If the 3 lenses score an importance as `[10, 9, 2]`, the average is `7`, dragging down a critical skill due to one hallucination. The median is `9`, safely preserving consensus while ignoring outliers.
3. **Lists (`evidence`, `canonical_terms`, `synonyms`)**: Set Union. All unique string values are combined, stripping duplicates.

---

## 7. Execution Flow & Metadata Tracking

Running Phase 1 is fully automated:
```bash
python offline/phase01_jd_intelligence.py
```

Before saving to disk, the script injects a highly detailed `metadata` payload into the JSON containing **Extraction Diagnostics**. This is crucial for debugging sudden latency spikes or model degradation later in the pipeline.

The metadata includes:
* **`phase`**: The exact phase ID (`phase01`).
* **`timestamp`**: The UTC timestamp of generation.
* **`successful_lenses`**: The number of successful lenses merged.
* **`failed_lenses`**: The number of lenses that failed to generate.
* **`cache_hit_rate`**: The percentage of lenses that bypassed the LLM due to `cache_version: v1` hashing.
* **`generation_time_seconds`**: The total time taken to generate the schema.
* **`schema_retries`**: The total number of Pydantic validation failures that forced an automatic retry.
* **`providers_used`**: An array of the exact providers utilized (e.g., `["gemini", "cerebras"]`) to explicitly trace failover executions.

The final output is serialized to `data/artifacts/jd_requirements.json`, fully unblocking the execution of the Domain Ontology Engine (Phase 2).
