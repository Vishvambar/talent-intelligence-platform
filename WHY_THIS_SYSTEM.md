# Engineering Decisions

## Why Teacher-Student Distillation?
**Decision**: Separate the pipeline into an "Offline Teacher" and an "Online Student."
**Reason**: Strict Kaggle constraints (5-minute maximum inference runtime on a CPU-only environment) explicitly prohibit real-time LLM parsing of 100,000 dense candidate resumes.
**Tradeoff**: Demands heavy pre-computation (Phase 1-8 offline runs can take hours), but allows the actual deployment script (Phase 11) to execute complex semantic predictions in ~2 seconds using only `145 MB` of RAM.

## Why Evidence Bank?
**Decision**: Pre-compute reasoning components (strengths, gaps, risks) and store them in a tabular `evidence_bank.parquet` rather than using a live RAG/LLM to explain scores.
**Reason**: Generating language on the fly introduces hallucinations and non-determinism, violating the core Redrob requirements for reproducible and trustworthy ranking.
**Tradeoff**: Explanations are slightly less expressive and fluid than a raw GPT-4 output, but they are 100% mathematically deterministic, legally auditable, and incredibly fast to query.

## Why LightGBM + XGBoost Ensemble?
**Decision**: Use a statically blended ensemble of two tree-based gradient boosters instead of a neural network.
**Reason**: Tabular behavioral metrics (like `recruiter_response_rate`, `time_in_role`) dominate Redrob's feature importance. Tree-based models are intrinsically better suited for unscaled tabular data than MLP architectures. Ensembling LightGBM (speed) with XGBoost (robustness on sparse features) minimizes overfitting.
**Tradeoff**: Slightly larger model bundle (two `.pkl` files instead of one), but significantly higher stability across K-Folds.

## Why Hybrid Retrieval?
**Decision**: Combine BM25 (lexical) and E5/BGE (dense) scores during Phase 6 instead of relying purely on vector similarity.
**Reason**: Pure vector search is notoriously weak at handling exact keyword matches (e.g., distinguishing between "Java" and "JavaScript" or finding exact acronyms like "AWS"). Hybrid retrieval anchors the semantic meaning with hard lexical verification.
**Tradeoff**: Requires maintaining both a BM25 index and a vector database offline, increasing storage complexity.

## Why Elite Reranking?
**Decision**: Extract the Top 50 candidates outputted by the ML model and apply a deterministic business-logic reranker based heavily on retrieval overlap.
**Reason**: ML models inherently optimize for the average, occasionally ignoring strict hard requirements in favor of strong behavioral signals. Elite Reranking guarantees that the absolute top candidates presented to the recruiter mathematically possess the core skills requested in the Job Description.
**Tradeoff**: Overrides the pure ML score for the top decile, requiring careful tuning of the `elite_formula.json` threshold to avoid destroying the model's behavioral ranking.
