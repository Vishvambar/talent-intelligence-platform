# Phase 3: Candidate Knowledge Graph & Feature Warehouse

## The "Why" behind the architecture

### Why extract features before retrieval?
Standard RAG pipelines embed raw text and rely purely on vector similarity. In recruitment, a candidate with "0 years of experience" who wrote an essay about RAG will have a very high embedding similarity to the JD. By extracting structured features (e.g., `years_of_experience`, `startup_score`) *first*, we allow downstream ranking models to learn the difference between semantic relevance and actual qualification.

### Why impute missing Github scores to the median?
If we assign `0` to candidates without Github data, the model learns that "no Github = terrible engineer". In reality, many elite engineers work in proprietary codebases. By imputing to the midpoint (40) and adding an explicit `github_missing=1` boolean flag, the LTR model can learn the conditional logic: "If Github exists, use the score; if missing, rely on experience features."
