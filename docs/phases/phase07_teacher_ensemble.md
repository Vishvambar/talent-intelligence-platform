# Phase 7: Teacher Ensemble & Synthetic Labels

## What This Phase Actually Does
Phase 7 generates ground-truth training labels for our ML models. Instead of relying on flawed historical human hiring data, we use a slow, expensive ensemble of high-end LLMs (GPT-4, Claude) acting as senior technical recruiters to strictly evaluate the Top 500 candidates. This produces unbiased, high-fidelity relevance scores (e.g., 0 to 100) to train the Phase 9 models.


## The "Why" behind the architecture

### Why Temperature = 0?
We are generating training labels for an XGBoost/LightGBM model. Variance in the training data acts as noise that the gradient booster has to fight. Temperature=0 guarantees that the exact same candidate profile parsed against the exact same JD yields the exact same synthetic score every single time.

### Why 3 Prompts (Technical, Evaluation, Execution)?
Just like Phase 1, asking an LLM to "score this candidate out of 100" results in a generic, vibes-based score. By forcing the LLM to run a rigorous Technical Evaluation (focusing purely on ML), a Metric Evaluation (focusing on NDCG/MAP), and an Execution Evaluation (focusing on shipping velocity), we get a structured, nuanced 3-part score.

### Why Teacher Drift Detection (Phase 7.1)?
LLMs suffer from "template collapse" when run in batch over thousands of items—they stop actually reading the prompt and start copy-pasting their previous reasoning structure. By clustering the `reasoning_chain` outputs, we mathematically detect if the LLM has stopped thinking and is just applying a cookie-cutter template.

### Why Hard Negative Mining (Phase 7.5)?
If we only train the LTR model on random candidates (score ~ 10) vs perfect candidates (score ~ 90), the model learns a trivial boundary. A "Hard Negative" is a candidate who has the exact right keywords ("Machine Learning", "Python") but violates a core constraint (e.g., 0 startup experience). By explicitly flagging them and capping their score, we force the LTR model to learn the complex, non-linear boundaries.
