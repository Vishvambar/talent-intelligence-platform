# Phase 3: Candidate Knowledge Graph & Feature Warehouse

## What This Phase Actually Does
Phase 3 streams the raw `candidates.jsonl` (100,000+ candidates) and transforms unstructured text, scattered career histories, and missing behavioral signals into a flat, highly structured tabular numeric matrix (`candidate_features.parquet`). It relies on Phase 2 to map technical skills to normalized numeric scores (0.0 to 1.0). In addition, it algorithmically unpacks complex career histories to infer structural indicators like `career_gap_months`, `promotion_count`, and `title_inflation_score`.

## The "Why" behind the architecture

### Why extract features before retrieval?
Standard RAG pipelines embed raw text and rely purely on vector similarity. In recruitment, a candidate with "0 years of experience" who wrote an essay about RAG will have a very high embedding similarity to the JD. By extracting structured features (e.g., `years_of_experience`, `startup_score`) *first*, we allow downstream ranking models to learn the difference between semantic relevance and actual qualification.

### Why impute missing Github scores to the median?
If we assign `0` to candidates without Github data, the model learns that "no Github = terrible engineer". In reality, many elite engineers work in proprietary codebases. By imputing to the midpoint (40) and adding an explicit `github_missing=1` boolean flag, the LTR model can learn the conditional logic: "If Github exists, use the score; if missing, rely on experience features."

### Why calculate promotions and career gaps mathematically?
Counting the number of roles (`career_role_count`) isn't enough. By grouping roles by company, mapping them to a strict `TITLE_LEVELS` hierarchy, and sorting by chronological start dates, we can deterministically detect actual promotions (ignoring lateral moves). Similarly, calculating `title_inflation_score` dynamically as a ratio of `leadership_count / years_exp` creates a resilient, continuous penalty signal that naturally scales with a candidate's age. This sets up Phase 4 to succeed.
