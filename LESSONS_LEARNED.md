# Lessons Learned (Engineering Evolution)

This document tracks the major architectural pivots we made while engineering the Redrob Candidate Ranking Pipeline. It demonstrates how we iterated away from naive implementations toward a mature, production-grade system.

## 1. The Pivot from Live Generative AI

**We initially attempted** to use a live Large Language Model (LLM) inside the online inference script to parse the resumes against the Job Description and dynamically generate the reasoning strings required for `submission.csv`.

**We discovered** three fatal flaws:
1. It immediately violated the 5-minute maximum CPU execution constraint (parsing 100,000 dense texts in real-time is impossible under these bounds).
2. The generative output was highly non-deterministic, making reproducibility impossible.
3. The LLM frequently hallucinated reasoning, claiming candidates possessed skills they did not.

**We changed** the architecture to a "Knowledge Distillation" model. We shifted 100% of the heavy NLP parsing to an offline "Teacher" phase. We then implemented an **Evidence Bank**—a pre-computed tabular store of reasoning strings. The online inference script simply performs a deterministic lookup into the Evidence Bank to render the final explanations.

**Tradeoff:** We sacrificed the fluidity and extreme expressiveness of live generative text in exchange for absolute determinism, zero hallucinations, and a 0.2-second inference runtime.

## 2. The Pivot from Pure Vector Search

**We initially attempted** to use a pure dense vector retrieval system (E5 embeddings) to map candidates to the Job Description priorities.

**We discovered** that while dense embeddings are excellent for semantic similarity (e.g., matching "Software Engineer" with "Developer"), they are notoriously weak at strict lexical constraints. The system would frequently suggest candidates who were missing exact business acronyms or specific technical tools (e.g., matching "Java" when the JD strictly required "JavaScript").

**We changed** the offline retrieval engine to a **Hybrid (BM25 + Dense)** architecture. We built a BM25 inverted index alongside the vector database to anchor the semantic scoring with hard lexical verification.

**Tradeoff:** We increased the complexity of our offline storage and preprocessing by having to maintain two distinct indices, but we gained mathematically rigorous keyword enforcement.

## 3. The Pivot from Single Model to Ensemble

**We initially attempted** to use a single LightGBM model as the core Student Ranker, given its speed and efficiency on CPU environments.

**We discovered** that while LightGBM handled dense tabular features beautifully, its performance degraded slightly on sparse, zero-imputed features derived from the candidate graph (e.g., missing GitHub repository metrics). 

**We changed** the prediction engine to a static ensemble, blending LightGBM with XGBoost.

**Tradeoff:** We increased the model footprint (requiring two `.pkl` files and slightly increasing the offline training overhead) to gain significant robustness across sparse datasets, preventing over-indexing on missing data structures.
