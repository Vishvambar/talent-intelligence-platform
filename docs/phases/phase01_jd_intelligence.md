# Phase 1: JD Intelligence Engine

## What This Phase Actually Does
Phase 1 reads the raw Job Description (JD) text and uses LLMs to extract a structured, deterministic JSON contract. It extracts hard requirements, preferred skills, and negative signals (red flags), canonicalizes them into standard terms, and saves them to `jd_requirements.json`. This provides a stable target for all downstream retrieval and ranking.

## The "Why" behind the Architecture

### 1. Why Domain-Specific Pydantic Schemas?
A single massive prompt asking an LLM to fulfill a gigantic JSON schema dilutes the quality of the extraction. We want deep, specialized intelligence without hallucination. By splitting the generation into highly specialized Pydantic models (`CapabilityOutput`, `BusinessOutput`, `RiskOutput`), we completely eliminate domain hallucination and keep the `model_json_schema()` injected into the prompt compact and robust.

### 2. Advanced Merge Logic and Priority Weighting
The winning node during extraction is now chosen by maximizing `(priority_weight * extraction_confidence)`. This ensures that highly trusted nodes consistently beat uncertain ones. We also explicitly implemented cycle detection in the `global_backprop` graph construction to strictly prevent infinite requirement cycles before wiring parent/child relationships.

### 3. Smarter Quality Scoring
Instead of an arbitrary LLM score, the `phase_quality_score` is a heuristic metric based on Evidence Coverage (are nodes backed by text?), Average Extraction Confidence, Pydantic Validity Rate, and Ontology Richness.

### 4. Post-Merge Expansion (Retrieval Strategy)
After merging the isolated lenses, we pass the aggregated intelligence to a Post-Merge generation step that explicitly outputs a `retrieval_strategy` (e.g. `"Dense > BM25"`, `"Favor startup over enterprise"`). Phase 6 consumes this directly for ranking weights.

### 5. Smart Self-Correction & Pydantic Retry Loop
Offline models frequently fail to close brackets or add trailing commas. Phase 1 employs a strict Regex Trailing-Comma cleaner and a Pydantic Retry Loop that explicitly feeds Python parsing errors back to the model (`"JSON/Pydantic Validation failed -> Expecting ',' delimiter... Fix it"`), guaranteeing 100% valid JSON outputs without fatal crashes.
