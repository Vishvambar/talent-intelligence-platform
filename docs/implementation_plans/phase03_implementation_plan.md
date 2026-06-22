# Phase 3 Implementation Plan: Feature Warehouse

**Status**: Planning
**Target File**: `offline/phase03_feature_warehouse.py`
**Input File**: `data/raw/candidates.jsonl`
**Output File**: `data/artifacts/candidate_features.parquet`

## Objective
Convert all 100,000 raw candidate JSON profiles into a structured, flat numeric feature matrix. This script transforms unstructured text, fragmented career histories, and missing behavioral signals into continuous numerical distributions ready for Phase 8/9 tree-based ranking algorithms.

## Implementation Details

### 1. Dependency Upgrades
Phase 3 requires tabular dataframe manipulation and Parquet exporting. I will install `polars`, `pandas`, and `pyarrow` into the `venv` and update the `requirements.txt` accordingly.

### 2. Streaming Data Ingestion
To safely process the ~500MB JSONL file without blowing up the memory budget, we will stream the candidates in discrete chunks of 1,000:
```python
def stream_candidates(path: str, batch_size: int = 1000):
    batch = []
    with open(path, 'rt', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                batch.append(json.loads(line))
                if len(batch) == batch_size:
                    yield batch
                    batch = []
```

### 3. Feature Extraction Modules
For each candidate, we will execute a deterministic feature extraction suite:

- **Experience Features**: Computes `years_exp`, `avg_tenure`, `promotion_count` (title progression within the same company), and `leadership_count`.
- **Technical Features**: We dynamically import `compute_ontology_feature_vector` from `phase02_ontology_engine.py` and pass it the combined `headline + summary + skills_text`. The output dictionary (e.g., `vector_db_score`, `retrieval_score`) is flattened directly into the candidate's row.
- **Career Features**: We will classify each company in their history using `PRODUCT_SIGNALS` vs `CONSULTING_SIGNALS` to generate a `product_company_score` and a `consulting_score`. We will also generate a `startup_score`.
- **Education Features**: We map university tiers to numerical scores (`tier_1` = 1.0, `tier_4` = 0.2).
- **Behavioral Signals**: We impute missing `github_activity_score == -1` to exactly `40.0`, and set `github_missing = 1.0` so the tree can split on the imputation.

### 4. Tabular Export & Verification
The final list of 100,000 flat dictionaries is converted to a Polars/Pandas DataFrame and written to `candidate_features.parquet`.

Before exiting, the script will execute the V12 Verification Checklist:
- **Shape Audit**: Assert exactly 100,000 rows.
- **Null Audit**: Assert exactly 0 nulls across all numeric columns.
- **Imputation Audit**: Verify `github_missing` distribution matches the missing `-1` count in the raw data.
- **Distribution Audit**: Print `years_exp.describe()` to sanity-check ranges (0–30+).
