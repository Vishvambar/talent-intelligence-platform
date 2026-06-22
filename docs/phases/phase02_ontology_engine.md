# Phase 2: Domain Ontology Engine

## What This Phase Actually Does
Phase 2 ingests the `jd_requirements.json` from Phase 1 and merges it with a frozen, human-curated Expert Ontology. It produces a strict hierarchical knowledge graph (`ontology.json`) that maps concepts (e.g., "Pinecone" -> "VECTOR_DB" -> "RETRIEVAL") and generates regex-based coverage formulas. It exports a function to convert unstructured text into a flat numeric feature vector.


## The "Why" behind the Architecture

### 1. Why NO LLMs at Runtime?
The ontology acts as the backbone for sparse retrieval and feature engineering. If an LLM hallucinates a new term during ontology expansion (e.g., deciding that "Data Scientist" is synonymous with "Founding AI Engineer"), it cascades through the entire pipeline, poisoning the BM25 index and inflating feature scores. A frozen, human-curated ontology guarantees deterministic feature baselines.

### 2. Why explicitly ban generic company names?
If we allow the LLM to generate an ontology for "Consulting Background", it might include "TCS", "Infosys", or "Accenture". While statistically correlated, hardcoding company names introduces immense bias and penalizes elite engineers who happened to work there. We explicitly enforce `BANNED_COMPANIES` in the `validate_ontology()` loop, forcing the ontology to match on the *nature* of the work (e.g., "IT services", "outsourcing") rather than the brand name.

### 3. The Canonical Node Map (Preventing Double Counting)
During execution, we discovered that Phase 1 JD extractions (`VECTOR_DATABASES`, `EVALUATION_FRAMEWORKS`) conceptually collided with the frozen Expert rules (`VECTOR_DB`, `EVALUATION`). To prevent downstream models from penalizing or double-rewarding a candidate, we implemented a strict `CANONICAL_NODE_MAP`. This automatically collapses redundant concepts into a single node during generation, resulting in exactly 27 rigorously distinct nodes.

### 4. Normalized Coverage vs. Weight Domination
A critical mathematical design choice was ensuring that the raw `weight` of a node (1-10) does NOT multiply directly into the feature score. 
Instead, `coverage = min(1.0, matched_terms / len(terms))`. 
This guarantees that `vector_db_score` outputs exactly `0.0` to `1.0`. The `weight` metadata is passed separately. If we output raw weighted scores (`4.0` for `VECTOR_DB` and `0.8` for `OWNERSHIP`), the Phase 8 Tree algorithms would mistakenly learn that vector database mentions are semantically "larger" concepts than ownership.

### 5. Depth-First Hierarchical Inheritance
Candidates rarely use exact top-level industry categorizations. To solve this, Phase 2 implements a strict depth-3 inheritance model:
`final_node_score = max(own_coverage, 0.5 * max(child_coverages))`
If a candidate mentions "Pinecone, FAISS, Qdrant", `VECTOR_DB` peaks at `1.0`. Consequently, `RETRIEVAL` automatically inherits a proportional `0.5` score, giving them credit for the broader architectural domain.

### 6. Strict Regex Boundaries
We explicitly compile strings into `r"\b" + escaped_term + r"\b"` word boundaries. This was implemented to prevent aggressive false positives (e.g., a candidate writing "roadmap" and accidentally triggering the "map" retrieval keyword). 

### 7. Narrowing Behavioral Signals (e.g., Ownership)
Initial tests proved that words like "led" or "owned" are statistically noisy ("Led a college event"). We explicitly narrowed the `OWNERSHIP` node to highly specific technical signals like "led development", "system ownership", and "owned delivery".

### 8. LangChain as a Negative Signal
Instead of blindly penalizing the keyword "langchain" (which would unfairly punish elite engineers who utilize the framework), the negative node `LANGCHAIN_ONLY_EXPERIENCE` is carefully mapped to phrases like "langchain wrappers", "langchain only", and "api-only ai". This safely isolates "shallow wrapper developers" from the rest of the talent pool.

### 9. Cryptographic Traceability
To ensure complete end-to-end pipeline integrity, the `ontology.json` computes and injects the `SHA-256` hash of the `jd_requirements.json` file. If the Job Description is modified in the future, the hash changes, explicitly invalidating the downstream cache.
