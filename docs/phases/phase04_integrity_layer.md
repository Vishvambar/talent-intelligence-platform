# Phase 4: Data Integrity Engine

## What This Phase Actually Does
Phase 4 acts as the honeypot and fraud-detection layer for the recruitment pipeline. Instead of blindly passing all candidates to the ranking model, this phase streams the raw `candidates.jsonl.gz` data and mathematically audits the physical possibilities of each candidate's career timeline. Crucially, it does **not** penalize scores or delete candidates. It simply generates objective numerical evidence that downstream models use to make their own decisions.

## The "Why" behind the architecture

### Why observational features instead of hard penalties?
If we manually multiply a candidate's score by `0.5` because they have a 6-month career gap, we destroy the value of the Phase 8 Tree Models (LightGBM). Machine learning excels at finding non-linear relationships. By passing `career_gap_months` and `timeline_inconsistency_score` directly to the model as features, the model might learn that a 6-month gap is actually a *positive* indicator for founding engineers, whereas an arbitrary penalty would have hidden that nuance.

### Why not use LLMs for honeypot detection?
LLMs are prone to hallucination and struggle with strict chronological math. Our rule families (e.g., Timeline Contradictions, Skill Duration Contradictions) rely strictly on parsing `duration_months` and computing calendar overlaps in Python. This guarantees deterministic, lightning-fast execution across 100,000 profiles.

### Key Integrity Signals Captured
- **Skill Density Score**: (`total_skill_months / career_months`). Easily catches keyword-stuffing candidates who dump 100+ skills on their resume to bypass traditional ATS filters.
- **Timeline Inconsistency Score**: (`sum of all role durations / elapsed calendar time`). Captures candidates overlapping roles or faking experience durations without actually having explicit overlapping dates.
- **Salary Outlier Score**: Computes a population-based Z-score deviation rather than using hardcoded bounds (e.g., `> 500 LPA`), making the pipeline resilient to different geographical markets and inflation over time.
- **Profile Completeness Score**: Measures the uncertainty introduced by missing fields (education, summary) so the model knows when it is making predictions on sparse data.

## Phase 4 Feature Status Summary

Future audits should reference this definitive list for Phase 8 inclusion:

**Active Features (Ready for LightGBM):**
- `timeline_inconsistency_score`
- `skill_density_score`
- `salary_outlier_score`
- `anomaly_count`
- `severity_sum`
- `max_severity`
- `skill_duration_contradiction_count`
- `max_skill_duration_excess_months`
- `seniority_velocity_score`

**Dataset-Inactive Features (Excluded from LightGBM due to lack of variance on this specific dataset):**
- `overlap_months`
- `profile_completeness_score`
