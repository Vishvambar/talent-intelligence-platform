# Changelog

## v1: Teacher Initialization
- Implemented Offline Knowledge Distillation architecture to process massive candidate payloads via LLM without violating online runtime constraints.
- Established Phase 1 (JD Intelligence) and Phase 2 (Ontology Engine) as the core Semantic Grounding mechanism for the pipeline.
- Engineered Phase 3 (Feature Extraction) to pull 23 deterministic behavioral signals from raw candidate histories.

## v2: Evidence Bank
- Replaced runtime generative LLM calls with a pre-computed Evidence Bank (Phase 10).
- This shifted explanation generation entirely offline, eliminating hallucinations and ensuring the inference engine remains 100% deterministic and CPU-friendly.

## v3: Elite Reranking & Ensemble
- Introduced XGBoost as a secondary "Student" model to complement LightGBM, blending predictions statically to generalize on sparse text features (Phase 9A, 9B).
- Developed a dynamic Elite Reranking module (Phase 9C) to strictly prioritize candidates possessing business-critical skills (derived from Phase 6 BM25+Dense Hybrid Retrieval) over pure generic feature matches.
- Added strict multi-phase safety auditing, enforcing monotonically decreasing scores, exactly 100 final candidates, deterministic replayability, and candidate existence verification.
