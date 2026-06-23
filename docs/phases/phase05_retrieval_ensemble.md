# Phase 5 & 6: Multi-Embedding Hybrid Retrieval Ensemble

## What These Phases Actually Do
Phase 5 and 6 work together to filter the 100,000 candidates down to a highly relevant Top 3,000 pool. Rather than querying a traditional vector database, Phase 5 generates exact embeddings, and Phase 6 runs lightning-fast exact-match Numpy multiplications and Vectorized BM25 to guarantee 100% mathematical fidelity.

## The "Why" behind the architecture

### Why 6 Independent Dense Indices?
A candidate's headline/summary ("AI Enthusiast"), career history ("Built a production semantic search system..."), and skills section ("Python, PyTorch") have fundamentally different semantic structures. Averaging these texts before embedding dilutes the dense signal. We embed them separately using two different models (BGE and E5), creating 6 distinct semantic lenses. 

### Why both BGE and E5?
Our overlap diagnostics proved that BGE acts as a sharp ranker with high score variance, while E5 acts as a broad recall model with highly compressed scoring. Fusing them via RRF smooths out the blind spots of both models perfectly.

### Why search all 100k for BM25?
Dense retrieval discovers candidates based on semantic intent, but it can miss exact critical keywords. By running BM25 completely independently across all 100,000 candidates, we inject pure keyword-match candidates into the pool that Dense missed entirely.

### Why Top K = 3000?
A standard Top 100 retrieval drops elite but uniquely-phrased resumes. Given the Kaggle hardware, calculating pairwise metrics and LTR over 3000 candidates takes seconds. We vastly over-retrieve to guarantee 99%+ recall, pushing the precision burden entirely onto the downstream LightGBM tree ensemble in Phase 8.
