# Redrob Candidate Ranking Pipeline

## Overview
This repository contains the deterministic, multi-modal **Recruiter Relevance Prediction Engine** for the Redrob Candidate Ranking Challenge. It is designed to take raw candidate profiles and a Job Description and output the top 100 shortlisted candidates, complete with reasoning logic, without relying entirely on volatile LLM heuristics.

## Quick Start
Before executing, ensure you have Python 3.12+ and the dependencies installed:

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

To run Phase 1 (JD Extraction & Semantic Canonicalization):
```bash
python offline/phase01_jd_intelligence.py
```

## Architecture Link
**[Architectures/ARCHITECTURE_V12_FINAL.md](Architectures/ARCHITECTURE_V12_FINAL.md)** is the absolute single source of truth for this project. If you have questions about the pipeline, inputs, outputs, thresholds, or reasoning, start there.

For deeper engineering whitepapers on the "Why" behind specific phases, consult the `docs/phases/` directory. For the log of explicit architectural tradeoffs, consult `docs/decisions/`.

## Repository Structure
```text
README.md
Architectures/
└── ARCHITECTURE_V12_FINAL.md    <-- FULL SOURCE OF TRUTH
docs/
├── phases/                      <-- Engineering Deep Dives
├── decisions/                   <-- Architecture Decision Records
└── experiments/                 <-- Ablation testing logs
data/
├── raw/                         <-- Raw JD docs & candidate profiles
└── artifacts/                   <-- Output files (jd_requirements.json, etc.)
offline/                         <-- Core feature extraction & ranking pipeline
```

## Current Status
- **Phase 1**: Completed & Frozen
- **Phase 2**: Under Construction