# Phase 3 Implementation Plan: Feature Warehouse (V12 Upgraded)

**Status**: Frozen & Implemented
**Target File**: `offline/phase03_feature_warehouse.py`
**Input File**: `data/raw/candidates.jsonl`

## Objective
Convert all 100,000 raw candidate JSON profiles into structured tabular artifacts. This phase is the foundation for all downstream ranking, retrieval, and penalty models.

## Output Artifacts

Phase 3 will generate four separate, critical artifacts into `data/artifacts/`:

### 1. `candidate_features.parquet`
Only numeric features, strictly typed.
```json
{
    "candidate_id": "...",
    "years_exp": 8.3,
    "retrieval_score": 0.73,
    "job_hop_count": 2.0
}
```

### 2. `candidate_texts.parquet`
Raw text aggregates necessary for Phase 5 (Dense Retrieval), Phase 7 (Teacher), and Phase 10 (Reasoning Bank). Crucially, this also includes the full raw JSON string to eliminate ever having to re-parse the 500MB JSONL.
```json
{
    "candidate_id": "...",
    "headline": "...",
    "summary": "...",
    "skills_text": "...",
    "career_text": "...",
    "retrieval_text": "combined text",
    "raw_candidate_json": "{...}"
}
```

### 3. `feature_registry.json`
A formal registry defining the schema for the features DataFrame, preventing batch drift.

### 4. `feature_stats.json`
A comprehensive statistical report generated after export containing the `mean`, `std`, `min`, and `max` for every single numeric feature. This allows instant debugging of distributions before Phase 8.

## Implementation Details

### 1. Checkpointing Pipeline
To protect against OOMs or mid-stream parsing crashes (e.g. failing at candidate 87,000), candidates will be streamed, parsed, and **flushed to disk every 5,000 records**:
```text
data/artifacts/checkpoints/
  features_part_001.parquet
  texts_part_001.parquet
  ...
```
Once the stream finishes, all parts are merged into the final two single Parquet files.

### 2. Candidate Feature Extraction

- **Candidate ID Preservation**: Explicitly enforced. Every row joins on `candidate_id`.
- **Integrity Features (For Phase 4)**: Computes `job_hop_count`, `duplicate_company_count`, `career_gap_months`, and `title_inflation_score`. No penalties applied here, just computation.
- **Career Features Expansion**: Beyond just product/consulting, this explicitly ensures `founding_team_score`, `ownership_score`, `marketplace_score`, and `search_relevance_score` are captured and exposed for Elite ReRank.
- **Education Tie-Down**: `education_tier_score` bounds lowered to `[0.0 - 0.3]` to heavily de-emphasize pedigree compared to "shipping" and "ownership" signals.
- **Behavioral Signals**: `github_activity_score == -1` imputed to `40.0`, setting `github_missing = 1.0` flag for tree splits.
- **Technical Features**: Passes `headline + summary + skills` into Phase 2's `compute_ontology_feature_vector()` and automatically maps output scores.

### 3. V12 Verification Checklist

Before script completion, the merged artifacts are audited:
- **Shape Audit**: Dynamically counts the JSONL rows first (`raw_count = count_jsonl_rows()`), then asserts `len(df) == raw_count`.
- **Null Audit**: `assert df.null_count() == 0`
- **Cardinality Audit**: `assert len(df.columns) == EXPECTED_FEATURE_COUNT`
- **ID Uniqueness**: `assert df['candidate_id'].n_unique() == raw_count`
- **Ontology Coverage Audit**: Assert that key features (`retrieval_score.mean()`, `ownership_score.mean()`) are neither strictly `0.0` nor `1.0`.
