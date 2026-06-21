# Phase 1: JD Intelligence Engine

## Overview
Phase 1 is the entry point of the Redrob Candidate Ranking System. Its goal is to translate the unstructured, human-written Job Description (`data/raw/job_description.docx`) into a highly structured, machine-readable JSON schema (`jd_requirements.json`). This deterministic output schema powers downstream Retrieval (Phase 6), Ontology Expansion (Phase 2), and Teacher LTR ranking (Phase 7).

## Core Architecture

### 1. Robust LLM Routing Infrastructure
Because LLM API endpoints frequently encounter rate limits (429s), service outages (503s), and JSON formatting failures, Phase 1 relies on a newly introduced `shared/llm/router.py` component.

**Key Router Features:**
- **Phase-Aware Routing**: Fetches the priority fallback chain dynamically from `config/hyperparams.yaml` (e.g. `Gemini -> Cerebras -> Groq -> OpenRouter`).
- **Versioned Prompt Caching**: Hashes prompts with `cache_version: v1` to instantly return cached responses, saving tokens on pipeline reruns.
- **Pydantic Schema Enforcement**: Rejects any non-JSON or poorly structured outputs from the LLMs, automatically retrying the fallback chain.

### 2. Multi-Perspective Prompts
Instead of running an identical LLM prompt 5 times, Phase 1 approaches the JD using three distinct personas to extract maximum signal:
- **Prompt A (Technical Lens):** Focuses strictly on engineering constraints (e.g., Vector DBs, ML pipelines).
- **Prompt B (Execution Lens):** Identifies signals of startup/product velocity and execution speed.
- **Prompt C (Culture Lens):** Looks for behavioral expectations (async-first, ownership, fast failure).

### 3. Pydantic Constraints & Output Schema
Rather than simple binary values, Phase 1 extracts nuanced data for every concept:
- **`required`**: Boolean flag.
- **`importance`**: 1-10 scale.
- **`confidence`**: 0.0-1.0 scale tracking LLM certainty.
- **`evidence`**: Direct text snippets from the `.docx` to prove why the constraint exists.
- **`canonical_terms` & `synonyms`**: For expanding the search net (Phase 2).
- **`negative_signals`**: Tracks what the JD explicitly says it *doesn't* want, storing a `penalty_strength` (1-10) instead of a `required` boolean.

### 4. Median Aggregation
Once the 3 lenses return their schemas, the script intelligently merges them:
- **Booleans**: Majority vote.
- **Scores**: Median (preserves consensus, drops outliers).
- **Lists (Evidence, Synonyms)**: Set union.

## Execution

1. Make sure your `.env` is configured with the appropriate API keys.
2. Run the offline script:
   ```bash
   python offline/phase01_jd_intelligence.py
   ```
3. The output will be saved to `data/artifacts/jd_requirements.json` along with metadata tracking the models used and the generation timestamp.
