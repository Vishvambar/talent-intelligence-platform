# Phase 5: Multi-Embedding Hybrid Retrieval Ensemble

## The "Why" behind the architecture

### Why use BOTH BGE-Large and E5-Large?
Different embedding models map the semantic space differently. BGE is optimized for general semantic textual similarity, while E5 handles instructional and asymmetric search queries exceptionally well. By ensembling both, we smooth out the blind spots of any single model.

### Why split Profile and Career embeddings?
A candidate's headline/summary ("AI Enthusiast") has a fundamentally different semantic structure than their career history ("Built a production semantic search system..."). Averaging these texts before embedding dilutes the dense signal. We embed them separately and weight them at runtime:
`Dense Score = (0.30 * profile_bge) + (0.20 * career_bge) + (0.30 * profile_e5) + (0.20 * career_e5)`

### Why Top K = 3000?
A standard Top 100 retrieval drops elite but uniquely-phrased resumes. Given the RTX 6000 hardware, calculating pairwise metrics and LTR over 3000 candidates takes seconds. We vastly over-retrieve to guarantee 99%+ recall, pushing the precision burden entirely onto the downstream LTR tree ensemble.
