# Phase 2 Implementation Plan: Domain Ontology Engine (V12 Upgraded)

**Status**: Frozen & Implemented
**Target File**: `offline/phase02_ontology_engine.py`
**Output File**: `data/artifacts/ontology.json`

## Objective
Build a hierarchical **knowledge layer** that sits between the JD parameters (Phase 1) and the downstream retrieval/ranking systems. This ontology must be deterministic, avoid false positives via regex, support explicit hierarchical concept inheritance, and merge Phase 1 intelligence with frozen expert rules.

## Implementation Details

### 1. Phase 1 Bootstrapping & Metadata
The script will load `data/artifacts/jd_requirements.json`.
- `hard_requirements` and `preferred_requirements` feed into `POSITIVE_ONTOLOGY`.
- `negative_signals` feed into `NEGATIVE_ONTOLOGY`.
- The `ontology.json` will export a comprehensive `metadata` block including the JD hash for traceability:
  ```json
  "metadata": {
    "version": "v12",
    "generated_from_jd_hash": "sha256...",
    "generated_from_jd_timestamp": "...",
    "ontology_nodes": 48,
    "positive_nodes": 31,
    "negative_nodes": 17
  }
  ```

### 2. Frozen Expert Hierarchy
We will append an `EXPERT_ONTOLOGY` dictionary. This imposes the architectural relationships, including explicitly requested behavioral and technical domain nodes to prevent an overly technical bias.
```python
EXPERT_ONTOLOGY = {
    "RETRIEVAL": { "weight": 10, "children": ["VECTOR_DB", "EMBEDDINGS", "SEARCH_RELEVANCE"], "terms": [...] },
    "VECTOR_DB": { "weight": 8, "children": [], "terms": [...] },
    "SEARCH_RELEVANCE": { "weight": 9, "children": [], "terms": [...] },
    "EXPERIMENTATION": { "weight": 8, "children": [], "terms": [...] },
    "ML_INFRASTRUCTURE": { "weight": 7, "children": [], "terms": [...] },
    "FOUNDING_TEAM": { "weight": 10, "children": [], "terms": [...] },
    "OWNERSHIP": { "weight": 9, "children": [], "terms": [...] },
    "PRODUCT_ENGINEERING": { "weight": 8, "children": [], "terms": [...] },
    "MARKETPLACE_SYSTEMS": { "weight": 7, "children": [], "terms": [...] }
}
```

### 3. Explicit Mathematical Formulas
1. **Coverage Formula**:
   `node_coverage = matched_terms / len(terms)`
   *(This ensures a strict, linear mathematical relationship. 2 out of 4 matched terms equals exactly 0.5 coverage).*
   
2. **Parent Propagation Math**:
   A parent node inherits a decayed maximum of its children.
   `final_node_score = max(own_coverage, 0.5 * max(child_coverages))`
   *If Pinecone (`VECTOR_DB`) = 1.0, `RETRIEVAL` automatically gets 0.5 without explicit retrieval terms.*

### 4. Integrity Validation Suite (`validate_ontology()`)
Before saving `ontology.json`, the script will run an integrity check:
- **No Duplicate Terms**: Asserts a term like `pinecone` appears only in one node.
- **No Company Names**: Asserts terms like `tcs`, `infosys`, `accenture` are completely absent.
- **No Empty Nodes**: Asserts `len(terms) > 0` for all nodes.
- **Weight Bounds**: Asserts `1 <= weight <= 10`.

### 5. Consumable Feature Vector Exposure
Instead of a generic scoring dict, the script will explicitly expose:
```python
def compute_ontology_feature_vector(text: str) -> dict:
    ...
```
This will return a flat dictionary of precisely named features ready for immediate consumption by the Phase 3 Feature Warehouse and Phase 8 Feature Matrix:
```json
{
    "retrieval_score": 0.85,
    "vector_db_score": 0.72,
    "evaluation_score": 0.91,
    "ownership_score": 0.44,
    "founding_team_score": 0.65,
    "consulting_only_score": 0.00
}
```
