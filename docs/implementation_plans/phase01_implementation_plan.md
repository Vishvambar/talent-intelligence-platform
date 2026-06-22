# Phase 1 Implementation Plan: JD Intelligence Engine

**Status**: Completed & Frozen
**Target File**: `offline/phase01_jd_intelligence.py`
**Output File**: `data/artifacts/jd_requirements.json`

## Objective
Convert the raw `job_description.docx` into a deterministic, highly structured JSON schema. Enforce a strict "Output Contract" guaranteeing that no duplicate or overlapping semantic concepts exist in the final output.

## Micro-Level Implementation Details

### 1. Multi-Lens LLM Extraction
Instead of a single monolithic prompt, the extraction is divided into 3 specialized lenses to prevent the LLM from over-indexing on technical traits:
- **Technical Lens**: Extracts `retrieval_systems`, `vector_databases`, `embeddings`, etc.
- **Execution Lens**: Extracts product-centric traits (e.g., `startup_builder`, shipping velocity).
- **Culture Lens**: Extracts behavioral signals (e.g., `ownership`, `title_chasers`).

**API Resiliency (Micro-level addition):**
Every `router.generate()` call is explicitly wrapped in a `try...except Exception:` block.
```python
try:
    schema, meta = router.generate(PROMPT_TECHNICAL.format(jd=jd_text), "phase01", JDSchema)
    schemas.append(schema)
    metadata_list.append(meta)
except Exception as e:
    print(f"Technical Lens failed: {e}")
```
This guarantees that an intermittent 502/504 error from an external LLM provider (like Groq or Cerebras) will only fail a single lens. The script will continue and merge the surviving schemas.

### 2. Median Aggregation
When merging the 3 schemas, numeric values (like `importance` scores and `confidence` scores) are merged using `statistics.median()`. 
*Why?* To discard hallucinated outliers. If two lenses score a trait as 9/10, and a hallucinated third lens scores it 2/10, the median safely preserves the 9/10.

### 3. Semantic Canonicalization Mappings
Because LLMs generate stochastic strings, we manually enforce de-duplication using two hardcoded Python dictionaries: `CANONICAL_REQUIREMENTS` and `CANONICAL_NEGATIVES`.

**Micro-level mapping implementations:**
- `"product_engineering_background"` dynamically absorbs:
  - `"scrappy_product_engineering_attitude"`
  - `"scrappy_product_engineering"`
  - `"product_company_experience"`
- `"non_coding_engineers"` dynamically absorbs:
  - `"non_coding_architects"`
  - `"hands_off_leadership"`
  - `"hands_off_architect"`
  - `"non_coding_leads"`
- `"langchain_only_experience"` dynamically absorbs:
  - `"shallow_ai_experience"`
  - `"wrapper_development"`
  - `"toy_ai_projects"`
- `"domain_experience"` dynamically absorbs:
  - `"marketplace_experience"`

*Note: As explicitly requested, `"production_coding"` and `"production_ml_deployment"` are left separate, as they are independent tracking features.*

### 4. Semantic Merging Logic (`process_canonical_section`)
The canonicalization function does not just drop duplicate strings. It mathematically merges the underlying Pydantic schema objects:
1. It scans `hard_requirements`, `preferred_requirements`, and `negative_signals` dictionaries.
2. It groups raw keys into their canonical parent keys.
3. If multiple objects map to the same key, it calculates the `max` importance, the `median` confidence, and the `set()` union of all `evidence` and `synonyms` arrays.

### 5. Debugging Metadata Block
To ensure the pipeline is 100% transparent, the exact topological merging actions are explicitly recorded in the JSON output. The `process_canonical_section` function returns a `merged_info` array containing the specific graph edges.

**Output Schema addition:**
```json
"semantic_canonicalization": {
  "status": "success",
  "duplicates_removed": 5,
  "merged_concepts": [
    {
      "canonical": "langchain_only_experience",
      "merged": [
        "toy_ai_projects",
        "shallow_ai_experience"
      ]
    }
  ]
}
```

## Verification
- Execution of `phase01_jd_intelligence.py` completed with `Duplicates removed: 5`.
- The final `jd_requirements.json` was audited and all target semantic overlaps were successfully collapsed while preserving independent features.
