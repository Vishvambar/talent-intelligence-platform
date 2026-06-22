# Phase 1: JD Intelligence Engine

## The "Why" behind the Architecture

The Job Description (JD) Intelligence Engine is the foundation of the entire pipeline. If Phase 1 outputs noisy, duplicate, or hallucinated requirements, every downstream retrieval and ranking model will learn the wrong boundaries. The goal of Phase 1 is to convert the human-readable `job_description.docx` into a deterministic, queryable JSON object: `jd_requirements.json`.

### 1. Why use 3 separate LLM Lenses?
A single prompt asking an LLM for technical, execution, and cultural requirements often causes the model to over-index on one area (usually technical skills like Python or PyTorch) and completely ignore soft signals. 
By splitting the generation into three distinct lenses:
- **Technical Lens**: Focuses purely on tools, frameworks, and academic backgrounds.
- **Execution Lens**: Focuses purely on shipping velocity, startup builder mentalities, and production-ready deployments.
- **Culture Lens**: Focuses purely on behavioral signals, such as ownership, fast failure, and title-chasers.

We force the LLM to dedicate its entire attention mechanism to extracting deep signals for each specific domain.

### 2. Why API Resiliency via `try...except`?
During execution, we rely on third-party LLM providers (e.g., Groq, Cerebras) via the `LLMRouter`. If one API endpoint times out or fails to return a valid JSON schema, Phase 1 should not crash.
By wrapping each lens execution in a `try...except` block, the pipeline gracefully degrades. If the Culture lens fails, Phase 1 simply merges the Technical and Execution lenses, allowing the pipeline to survive multi-provider outages.

### 3. Why Median Aggregation?
Once the lenses return their schemas, we must aggregate their numeric outputs (e.g., importance scores from 1-10, confidence scores from 0-1). 
If we use the statistical `mean`, a single hallucinated lens can drastically shift the requirement weighting. The `median` acts as a robust statistic—if 2 out of 3 lenses agree that "Evaluation Expertise" is a 9/10, a rogue 3rd lens scoring it a 2/10 is entirely ignored. 

### 4. Why Semantic Canonicalization?
LLMs are stochastic text generators. Even with Temperature=0, the lenses will generate slightly different phrasing for the exact same underlying concept. For example, one lens might extract `llm_finetuning`, and another `llm_fine_tuning`. Or worse, `toy_ai_projects` vs `langchain_only_experience`.
If we pass these raw strings to the vector database or feature pipeline, we essentially penalize candidates who don't match both random variations.

To enforce our strict **Output Contract**, Phase 1 implements a deterministic Semantic Canonicalization step using hardcoded mapping dictionaries (`CANONICAL_REQUIREMENTS` and `CANONICAL_NEGATIVES`).

#### Example Mappings:
We explicitly collapse correlated, overlapping terms into a single canonical key:
- `"non_coding_engineers"` dynamically absorbs `"non_coding_architects"`, `"hands_off_leadership"`, `"hands_off_architect"`, and `"non_coding_leads"`.
- `"langchain_only_experience"` dynamically absorbs `"shallow_ai_experience"`, `"wrapper_development"`, and `"toy_ai_projects"`.
- `"pure_research_background"` absorbs `"academic_only"` and `"pure_research_focus"`.
- `"domain_experience"` absorbs `"marketplace_experience"`.

Note: We explicitly *avoid* merging `"production_coding"` and `"production_ml_deployment"`, as they are distinct features used downstream in Phase 3.

### 5. Why Metadata Tracking for Merged Concepts?
To ensure the pipeline is transparent and debuggable, Phase 1 appends a `semantic_canonicalization` block to the metadata of the output JSON.
Rather than just reporting `"duplicates_removed": 5`, it outputs the exact topological mapping of what was merged:

```json
"merged_concepts": [
  {
    "canonical": "langchain_only_experience",
    "merged": [
      "toy_ai_projects",
      "shallow_ai_experience"
    ]
  }
]
```
This guarantees that any engineer debugging the system knows exactly why a specific LLM-generated feature vanished and which canonical term absorbed it.
