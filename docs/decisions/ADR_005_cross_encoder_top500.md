# ADR 005: Cross-Encoder ONLY on Top 500

## Decision
We apply the Cross-Encoder Re-Ranker (`ms-marco-MiniLM-L-6-v2`) strictly to the Top 500 candidates outputted by the LightGBM/XGBoost ensemble.

## Context
Cross-encoders are vastly superior to bi-encoders for relevance ranking, but are O(N) computationally expensive.

## Alternatives Considered
- **Run on all 3000**: Takes ~15 minutes on RTX 6000.
- **Run on Top 100**: Too risky; if a great candidate was ranked #105 by the tree ensemble, the cross-encoder never sees them to save them.

## Consequences
Top 500 provides a deep enough pool to rescue elite candidates who were slightly undervalued by the tree ensemble, while executing in <30 seconds.
