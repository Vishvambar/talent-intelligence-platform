# Engineering Decisions & Tradeoffs

## Why No Online LLM?
**Decision**: Completely remove LLMs from the online execution path (ranking).
**Benefit**: Guarantees we easily pass the 5-minute maximum CPU-only runtime constraint. Eliminates non-deterministic output and API failures.
**Cost**: Requires extracting all semantic intelligence offline beforehand.

## Why Teacher-Student Distillation?
**Decision**: Separate the pipeline into an "Offline Recruiter Teacher" and an "Online Student Ranker."
**Benefit**: Allows us to use massive semantic models (BM25, E5, LLM Ontology Extraction) to generate high-quality labels without violating runtime bounds.
**Cost**: Long offline preprocessing time.

## Why Evidence Bank?
**Decision**: Pre-compute reasoning components (strengths, gaps, risks) and store them in a tabular `evidence_bank.parquet` rather than using a live RAG/LLM to explain scores.
**Benefit**: Zero hallucinations. 100% mathematical determinism, legally auditable, and instantly queried during runtime.
**Cost**: Slightly less expressive and fluid than live generative text.

## Why LightGBM?
**Decision**: Use LightGBM as the primary Student Ranker model.
**Benefit**: Unmatched CPU inference speed and native handling of unscaled tabular behavioral metrics (like `recruiter_response_rate`).
**Cost**: Requires offline K-Fold training and hyperparameter tuning.

## Why XGBoost?
**Decision**: Blend XGBoost with LightGBM in a static ensemble.
**Benefit**: XGBoost is highly robust on sparse features (e.g., missing graph features or zero-imputed metrics). The ensemble minimizes overfitting from either individual tree structure.
**Cost**: Slightly larger model bundle (two `.pkl` files instead of one).

## Why Hybrid Retrieval (BM25 + Dense)?
**Decision**: Combine BM25 (lexical) and E5 (dense) scores during the offline pipeline.
**Benefit**: Pure vector search is notoriously weak at handling exact keyword matches (e.g., distinguishing between "Java" and "JavaScript"). BM25 anchors the semantic meaning with hard lexical verification.
**Cost**: Requires maintaining both a BM25 index and a vector database offline.

## Why Elite Reranking?
**Decision**: Apply a deterministic business-logic reranker on the Top 50 candidates outputted by the ML model.
**Benefit**: ML models inherently optimize for the average. Elite Reranking guarantees that the absolute top candidates presented to the recruiter mathematically possess the core skills requested in the Job Description, overriding the ML model if necessary.
**Cost**: Requires careful tuning of the `elite_formula.json` threshold to avoid destroying the model's behavioral ranking.

## Why Integrity Score?
**Decision**: Track data inconsistencies (like overlapping dates, missing seniority flags, keyword stuffing).
**Benefit**: Acts as a honeypot defense. Instead of blindly ranking a candidate high because they stuffed their resume with keywords, the integrity penalty drastically reduces their score.
**Cost**: Requires complex upstream parsing in the Feature Warehouse.
