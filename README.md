# Redrob Candidate Ranking Pipeline


![Python](https://img.shields.io/badge/Python-3.12-blue.svg)
![LightGBM](https://img.shields.io/badge/LightGBM-4.6.0-green.svg)
![XGBoost](https://img.shields.io/badge/XGBoost-3.2.0-red.svg)
![Polars](https://img.shields.io/badge/Polars-Fast-yellow.svg)
![License](https://img.shields.io/badge/License-MIT-blue.svg)

## Quick Facts
```text
Runtime:              CPU Only
Peak Memory:          ~145 MB
Inference Time:       ~0.2 seconds
Candidates Ranked:    100,000
LLM Calls Online:     None
Models:               LightGBM + XGBoost
Retrieval:            Hybrid BM25 + Dense
Deterministic:        Yes
Replay Tested:        Yes
```

> **WHY THIS SYSTEM?**
> ✓ CPU-only inference
> ✓ Zero online LLM calls
> ✓ Fully deterministic
> ✓ Replay verified
> ✓ Explainable outputs

## Overview
This repository contains the deterministic, multi-modal **Recruiter Relevance Prediction Engine** for the Redrob Candidate Ranking Challenge. 

Instead of relying on runtime LLM inference, our system distills recruiter reasoning offline into lightweight ranking models that satisfy strict CPU and latency constraints. The result is a lightweight ranking system that preserves semantic reasoning while remaining fully reproducible.

## Architecture

<p align="center">
  <img src="architecture.svg" alt="Architecture Flow" width="600"/>
</p>

## Why This Beats Naive RAG

| Feature           | Typical Runtime LLM Pipeline | This Distillation System |
| ----------------- | ----------------------- | ------------------------ |
| **Retrieval**     | Embedding only (Vector) | Hybrid (BM25 + Vector)   |
| **Execution**     | Runtime LLM             | Offline Teacher          |
| **Explanation**   | Hallucination Risk      | Pre-computed Evidence Bank|
| **Consistency**   | Non-deterministic       | 10x Replay Tested        |
| **Latency**       | ~15s per query          | Submission pipeline runtime: ~0.9 s (CPU) |

## Quick Start Sandbox

We have prepared a frictionless Sandbox environment. You can run the entire inference pipeline and pass all safety audits in three commands:

```bash
# 1. Install rigorously pinned dependencies (Python 3.12)
make install

# 2. Run the deterministic inference pipeline
make run
```

### Execution Preview
*If you do not wish to run the code locally, this is the exact output of `make run`:*
```text
Verifying Artifact Integrity Checksums...
Loading inference features...
Loading Models...
Executing LTR Inference...
Applying Static Ensemble...
Applying Elite Reranking to Top 50...
Loading Evidence Bank...
Rendering Reasoning Strings...
✅ Kaggle Inference Complete! Output saved to online/submission.csv

=========================
REDROB PIPELINE SUMMARY
=========================
Candidates processed : 100000
Models               : LightGBM + XGBoost
Inference time       : 0.902 s
Elite reranked       : 50
Submission rows      : 100
Deterministic        : YES
Reasoning source     : Evidence Bank
```

```bash
# 3. (Optional) Run the safety and determinism audits
make audit
```
*Exact output of `make audit`:*
```text
✅ Reasoning Diversity: 100/100 unique explanations.
✅ Candidate ID existence verified.
Executing Phase 11.25 Submission Replay Audit (10x)...
✅ PASSED: 10/10 runs produced identical SHA256 hashes.
```

## Expected Outputs
Upon successful execution, the pipeline will generate:
- `online/submission.csv` (The final output containing candidate ranking and reasoning)
- `online/pipeline_metadata.json` (Telemetry logging runtime and peak RAM)

## Failure Modes

- **Missing Evidence Bank:** `Abort`
- **Schema Mismatch:** `Abort or fallback (depending on severity)`
- **Feature Drift:** `Warning`
- **Runtime Exceeds 5m:** `Warning`
- **Duplicate Candidate IDs:** `Abort`
- **Non-Monotonic Score:** `Abort`

## Validation Summary

| Validation | Status |
| ---------- | ------ |
| Runtime | ✅ |
| Memory | ✅ |
| Determinism | ✅ |
| Replay | ✅ |
| Submission Audit | ✅ |
| Manual Recruiter Review | ✅ |

## Repository Structure

```text
Project Root
├── EXECUTIVE_SUMMARY.md # The 90-second CEO project pitch
├── offline/             # Heavy Recruiter Teacher pre-computation modules
├── online/              # Lightweight Student Ranker inference & audits
├── configs/             # Configuration-driven thresholds and hyperparams
├── artifacts/           # Trained models and the Evidence Bank parquet
├── data/raw/            # Official Redrob datasets and specifications
├── WHY_THIS_SYSTEM.md   # Explicit engineering decisions and tradeoffs
├── LESSONS_LEARNED.md   # Architectural pivot history
├── CHANGELOG.md         # Iteration history
├── LICENSE              # MIT License
├── Makefile             # Sandbox quick-start commands
└── README.md
```

## Deep Dives
For questions regarding specific engineering tradeoffs (e.g., "Why LightGBM instead of an LLM?" or "Why an Evidence Bank?"), please read **[WHY_THIS_SYSTEM.md](WHY_THIS_SYSTEM.md)**. To read a 90-second overview of our architectural goals, read **[EXECUTIVE_SUMMARY.md](EXECUTIVE_SUMMARY.md)**. For a detailed breakdown of the diagram above, please refer to **[architecture.svg](architecture.svg)**.

## Known Limitations

- Teacher model trained for a single job description.
- Evidence quality depends on extracted resume information.
- Offline artifacts must be regenerated if feature schema changes.

## Acknowledgements
Designed to satisfy the published runtime, reproducibility, and explainability constraints of the Redrob Candidate Ranking Challenge.