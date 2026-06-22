# ADR 003: Teacher Ensemble Aggregation = Median

## Decision
We use `median` instead of `mean` to aggregate the 3 runs per candidate in the Phase 7 Teacher Ensemble.

## Context
We run the teacher LLM 3 times per candidate to get a stable score.

## Alternatives Considered
- **Mean (Average)**: Standard approach.
- **Max**: Optimistic approach.

## Why Rejected
LLMs occasionally hallucinate catastrophically (e.g., misreading a resume and giving a 10/100 to a perfect candidate). 
If the scores are `[90, 92, 10]`, the `mean` is `64` (destroying the candidate). The `median` is `90` (ignoring the hallucination). 
In an autonomous pipeline, outlier rejection is far more important than statistical smoothing.
