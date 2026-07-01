# Architecture Decision Record: Redrob Perfect Execution (Phase 1 & 2 Freeze)

## Context
Following a rigorous architecture audit, we realized the pipeline was behaving like a generic RAG/Ranking system rather than modeling a Recruiter's semantic reasoning process. To align perfectly with the Redrob Candidate Ranking Challenge, Phase 1 (JD Intelligence) and Phase 2 (Ontology Engine) required structural overhauls to represent a true **Recruiter Intelligence Engine**.

## Decisions Made

### 1. Typology Split (Entity & Role)
- **Problem**: Nodes were grouped into a flat generic `category` (e.g., "technical"), which lacked semantic precision.
- **Decision**: We separated node identity into `EntityType` (Technology, Organization, Person, Metric, Framework, Language, Behavior) and `SemanticRole` (Skill, Experience, Requirement, Preference, NegativeSignal, Evidence, BusinessSignal).
- **Result**: "FAISS" is now recognized as a `Technology` serving the role of a `Skill`, creating immensely more powerful downstream ranking features.

### 2. Semantic Entity Validation
- **Problem**: `banned_terms.py` was used to blacklist company names (e.g., "TCS"), which is brittle and non-scalable.
- **Decision**: Deleted the banlist in favor of `config/ontology/entity_validation.py`. We now define explicit `expected_entity_type` validation arrays (e.g., `VECTOR_DB` must be a `Technology`).
- **Result**: The engine natively blocks hallucinated nodes by enforcing semantic type-safety.

### 3. Biological Edge Propagation (True Weighted Edges)
- **Problem**: The Ontology Engine propagated child scores to parents using a flat, hardcoded `0.8` decay, ignoring graph nuances.
- **Decision**: Natively implemented a full-context convergence equation: `propagated_score = edge_weight × parent_score × child_score × parent_confidence`.
- **Result**: Node scores smoothly propagate based on the semantic strength of the child-parent relationship, and negative signals decay aggressively (`0.3`) to prevent graph poisoning.

### 4. Lens Provenance & Confidence Splitting
- **Problem**: Once the three JD lenses (Technical, Execution, Culture) merged, it was impossible to know which lens contributed which node.
- **Decision**: Injected a `contributors` list into every node and split confidence into `extraction_confidence` (raw LLM certainty) and `aggregation_confidence` (percentage of lenses that agreed on the node).
- **Result**: Provides flawless debugging provenance and allows Phase 2 propagation to scale based on consensus confidence.

### 5. Granular 4-Level Requirements
- **Problem**: JD Requirements were binary (`required: bool`), destroying nuance.
- **Decision**: Migrated to a `RequirementLevel` Enum (`CRITICAL`=1.0, `IMPORTANT`=0.8, `USEFUL`=0.5, `OPTIONAL`=0.2).
- **Result**: The LightGBM ranker now receives a highly granular priority signal.

## Status
- **Phase 1**: Completed & Frozen
- **Phase 2**: Completed & Frozen
