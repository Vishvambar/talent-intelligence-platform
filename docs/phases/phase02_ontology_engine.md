# Phase 2: Universal Candidate Representation Engine

## What This Phase Actually Does
Phase 2 abandons the traditional "dumb" pipeline of mapping raw resume text straight to embeddings, but it also strictly avoids running expensive LLM reasoning too early. 

It acts as the **Universal Candidate Representation Engine**, translating 100,000 raw candidate resumes into a structured, highly scalable, and deterministic graph representation. By offloading all subjective evaluation (the 5-Lens Reasoning Engine) to Phase 7, Phase 2 remains blazingly fast, highly scalable, and fundamentally JD-agnostic.

## The "Why" behind the Architecture

### 1. The Systems Anti-Pattern of Early Reasoning
Many retrieval systems fail because they push expensive LLM reasoning to the top of the funnel (e.g., analyzing all 100k candidates with a 32B model). We are solving a ranking problem, not a reading problem. 
- **Phase 1** should be expensive (understanding the JD deeply).
- **Phase 2** must be massively scalable (representing 100,000 candidates efficiently).
- **Phase 7** becomes expensive again (running deep reasoning on the retrieved Top 3,000).

### 2. JD-Agnostic "Universal" Representation
If candidate intelligence depends on today's JD, you must regenerate all 100,000 candidates when a new JD arrives. Phase 2 extracts absolute, deterministic, *universal* facts about a candidate (Skills, GitHub metrics, Projects, Timelines).

### 3. Deterministic Ontology & Graph Propagation
Instead of LLM hallucination, Phase 2 uses the exact Recruiter Ontology (generated in Phase 1) fused with an Expert Ontology. It executes:
1. **Regex Extraction**: High-speed, robust regex matching across the resume corpus.
2. **Topological Propagation**: Smoothly propagating extracted evidence upwards through the DAG (e.g., if a candidate has `FastAPI`, the engine deterministically gives them partial credit for the parent node `Python`).
3. **Typology Generation**: Mathematically clustering candidates by their node distribution (e.g., `role_skill_score`, `type_framework_score`).

### 4. Canonical Representations
We absolutely **do not embed paragraphs or LLM summaries** for retrieval. Summaries destroy semantic weight. Phase 2 serializes the candidate's structural graph into `Canonical Documents`. This preserves 100% of the semantic density for downstream embedding in Phase 3.

### 5. Production-Grade Engineering
- **Scalability**: By bypassing the LLM entirely, Phase 2 can process 100,000 candidates natively without requiring massive GPU clusters.
- **Buffered Checkpointing**: We bypass sequentially opening/closing millions of files by buffering extraction checkpoints to JSONL.
- **Candidate Fingerprints**: We generate precise checksums from the canonical documents to facilitate instant cache invalidation and duplicate detection.

## Next Steps in the Pipeline
The `candidate_features.jsonl` and Canonical Documents generated here are passed directly into the **Retrieval Ensemble (Phases 3-6)**, which slices the 100,000 candidates down to 3,000. 

Only then do those Top 3,000 pass into **Phase 7: Recruiter-Aware Candidate Intelligence**, where the massive 5-Lens Qwen-32B Reasoning Engine evaluates their specific fit against the JD.
