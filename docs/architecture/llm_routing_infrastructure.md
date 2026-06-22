# Core Architecture: LLM Routing Infrastructure

## 1. The Core Philosophy
In the Redrob Candidate Ranking System, Large Language Models (LLMs) are **not** used at runtime to evaluate candidates on the fly. Doing so would violate latency requirements (5-minute timeout), compute constraints (CPU-only online environments), and cost boundaries. 

Instead, LLMs are deployed strictly as **offline data transformers and teachers**. However, offline execution still requires processing thousands of candidates. Relying on a single hardcoded provider (e.g., exclusively calling `openai.ChatCompletion`) introduces systemic fragility:
- **Rate Limits (429s):** Grading 3,000 candidates via an LLM will instantly exhaust most tier-1 API limits.
- **Service Outages (503s):** If the primary provider goes down, the entire pipeline halts.
- **Formatting Hallucinations:** LLMs frequently fail to adhere to strict JSON schemas, destroying downstream parsing.

To solve this, we engineered `shared/llm/router.py` — a centralized, phase-aware, schema-enforcing LLM infrastructure.

---

## 2. Phase-Aware Routing Mechanism

Not all phases have the same requirements. Some require massive context windows, while others require blazing fast inference speed. The `LLMRouter` reads `config/hyperparams.yaml` to determine the priority fallback chain dynamically based on the current phase.

### Configuration (`hyperparams.yaml`)
```yaml
llm:
  provider_priority:
    phase01:
      - gemini        # Preferred: Best at long context and JSON adherence
      - cerebras
      - groq
      - github_models
      - openrouter
    phase07:
      - groq          # Preferred: Blazing fast and cheap (critical for 3000 evaluations)
      - cerebras
      - gemini
      - github_models
      - openrouter
```

### Execution Flow
When a phase requires an LLM, it calls the router with a specific phase identifier:
```python
router.generate(prompt, phase="phase07", schema=EvaluationSchema)
```
1. The router identifies that it is operating in `phase07`.
2. It attempts to connect to `groq`.
3. If `groq` throws a `429 Rate Limit Exceeded`, the router catches the exception.
4. The router seamlessly falls back to `cerebras` and re-attempts the generation. No data is lost, and the script does not crash.

---

## 3. Pydantic Schema Enforcement

LLMs are notoriously bad at outputting clean JSON without conversational wrappers (e.g., *"Here is the JSON you asked for:"*). The router utilizes `pydantic` to enforce strict mathematical bounds and structural integrity.

### The Retry Loop
When the router receives raw text from the LLM:
1. It strips markdown blocks (` ```json ... ``` `).
2. It passes the raw string into the Pydantic schema: `schema.model_validate_json(raw_json)`.
3. If the LLM returned a confidence score of `15.0` instead of a float between `0.0` and `1.0`, Pydantic throws a `ValidationError`.
4. The router catches this specific error and **automatically retries** the LLM generation up to `max_retries` (default: 3).

---

## 4. Versioned Prompt Caching (`cache_version: v1`)

LLM calls are computationally expensive and slow. If a developer is debugging `phase01`, running the same prompt 50 times wastes tokens. 

The router implements a localized SHA-256 caching layer:
- The `prompt_hash` is generated using: `sha256(cache_version + phase + prompt)`.
- If a hash match is found in `data/artifacts/llm_cache/`, the router skips the API call entirely and instantly returns the cached JSON.
- **Cache Invalidation:** If the developer updates the prompt structure, they simply change `cache_version: v2` in `hyperparams.yaml`. This alters the hash, cleanly invalidating the old cache without needing to manually delete files.

---

## 5. Summary of LLM Usage Across Phases

| Phase | Responsibility | Router Priority | Reason for Priority |
|---|---|---|---|
| **Phase 1 (JD Intelligence)** | Extracting strict JSON schema and evidence snippets from unstructured `.docx` job descriptions. | `Gemini` -> `Cerebras` | Gemini possesses a massive context window and adheres strictly to JSON boundaries. |
| **Phase 2 (Domain Ontology)** | Expanding Phase 1 constraints into massive arrays of canonical synonyms and related concepts. | `Gemini` -> `Groq` | Requires deep world knowledge of technical ecosystems. |
| **Phase 7A (Teacher Ensemble)** | Grading/scoring thousands of candidate profiles against the JD to generate training labels for the ML model. | `Groq` -> `Cerebras` | Speed and cost are the only factors that matter when generating 3,000+ evaluations. |
| **Phase 10 (Reasoning Bank)** | Generating human-readable paragraphs explaining exactly *why* a candidate was ranked highly to be shown to recruiters. | `Gemini` -> `Cerebras` | Reasoning depth and narrative quality matter more than raw speed. |
