# Phase 9: Ranking Ensemble (LGBM + XGBoost + Cross-Encoder)

## What This Phase Actually Does
Phase 9 trains and executes ultra-fast tree-based algorithms (LightGBM/XGBoost) over the `candidate_features.parquet` matrix. It learns to predict the expensive Phase 7 Teacher labels using only the cheap, structured Phase 3 features. This allows us to instantly rank and surface the absolute best candidates without paying LLM inference costs for everyone.


## The "Why" behind the architecture

### Why not LambdaRank?
LambdaRank optimizes the entire list for NDCG. However, in our pipeline, we only care about the absolute Top 100. Furthermore, our labels are continuous synthetic scores (0-100), not discrete relevance grades (0-4). A standard Huber loss regression model is far more stable, easier to interpret with SHAP, and explicitly penalizes large errors on the elite candidates (scores 85+).

### Why Cross-Encoder ONLY for the Top 500?
Cross-Encoders (`ms-marco-MiniLM-L-6-v2`) are the gold standard for relevance ranking because they allow the self-attention mechanism to cross-reference the query and document simultaneously. However, they are computationally catastrophic. Running a cross-encoder on 100,000 candidates would take days. 
By using Bi-Encoders + BM25 + LTR to funnel down to the Top 500, we can run the Cross-Encoder on the elite subset in seconds, achieving maximum precision where it matters most.
