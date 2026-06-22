# Phase 2: Domain Ontology Engine

## What This Phase Actually Does
Phase 2 ingests the `jd_requirements.json` from Phase 1 and merges it with a frozen, human-curated Expert Ontology. It produces a strict hierarchical knowledge graph (`ontology.json`) that maps concepts (e.g., "Pinecone" -> "VECTOR_DB" -> "RETRIEVAL") and generates regex-based coverage formulas. It exports a function to convert unstructured text into a flat numeric feature vector.


## The "Why" behind the architecture

### Why NO LLMs at Runtime?
The ontology acts as the backbone for sparse retrieval and feature engineering. If an LLM hallucinates a new term during ontology expansion (e.g., deciding that "Data Scientist" is synonymous with "Founding AI Engineer"), it cascades through the entire pipeline, poisoning the BM25 index and inflating feature scores. A frozen, human-curated ontology guarantees deterministic feature baselines.

### Why explicitly ban generic company names?
If we allow the LLM to generate an ontology for "Consulting Background", it might include "TCS", "Infosys", or "Accenture". While statistically correlated, hardcoding company names introduces immense bias and penalizes elite engineers who happened to work there. We must match on the *nature* of the work (e.g., "IT services", "outsourcing") rather than the brand name.
