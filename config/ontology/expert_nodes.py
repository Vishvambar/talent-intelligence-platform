EXPERT_POSITIVE = {
    "RETRIEVAL": {
        "weight": 10,
        "children": {"VECTOR_DB": 1.0, "EMBEDDINGS": 1.0, "SEARCH_RELEVANCE": 1.0},
        "terms": ["retrieval", "ir system", "semantic search", "rag", "retrieval augmented generation", "information retrieval"],
        "entity_type": "Technology",
        "semantic_role": "Skill"
    },
    "VECTOR_DB": {
        "weight": 8,
        "children": {},
        "terms": ["qdrant", "pinecone", "milvus", "faiss", "vector database", "weaviate", "chroma"],
        "entity_type": "Technology",
        "semantic_role": "Skill"
    },
    "EMBEDDINGS": {
        "weight": 8,
        "children": {},
        "terms": ["embedding", "embeddings", "sentence transformer", "openai embeddings", "bge", "e5", "dense vector", "cross-encoder"],
        "entity_type": "Technology",
        "semantic_role": "Skill"
    },
    "SEARCH_RELEVANCE": {
        "weight": 9,
        "children": {"EVALUATION": 1.0},
        "terms": ["search relevance", "search ranking", "ranking model", "relevance ranking", "ranking algorithms", "search quality", "ranking", "relevance"],
        "entity_type": "Metric",
        "semantic_role": "Experience"
    },
    "EVALUATION": {
        "weight": 10,
        "children": {},
        "terms": ["ndcg", "map", "mrr", "precision at k", "offline evaluation", "ab testing", "a/b test"],
        "entity_type": "Metric",
        "semantic_role": "Experience"
    },
    "EXPERIMENTATION": {
        "weight": 8,
        "children": {},
        "terms": ["experimentation", "online evaluation", "statistical significance"],
        "entity_type": "Metric",
        "semantic_role": "Experience"
    },
    "ASYNC_WRITING_CULTURE": {
        "weight": 8,
        "children": {},
        "terms": ["written communication", "async-first", "technical writing", "documentation culture", "rfc", "architecture decision record", "adr"],
        "evidence_patterns": ["wrote rfc", "wrote adr", "wrote design docs", "authored design doc", "remote-first", "asynchronous"],
        "entity_type": "Behavior",
        "semantic_role": "Preference"
    },
    "OPEN_SOURCE_CONTRIBUTIONS": {
        "weight": 5,
        "children": {},
        "terms": ["open-source contributions", "oss contributions", "open source", "open-source", "github contributor", "maintainer", "pull request", "contributor"],
        "evidence_patterns": ["merged pr", "contributed to", "core maintainer", "apache contributor"],
        "entity_type": "Behavior",
        "semantic_role": "Evidence"
    },
    "ML_INFRASTRUCTURE": {
        "weight": 7,
        "children": {},
        "terms": ["mlops", "model serving", "ml pipeline", "inference latency", "triton", "tensorrt"],
        "entity_type": "Technology",
        "semantic_role": "Skill"
    },
    "FOUNDING_TEAM": {
        "weight": 10,
        "children": {},
        "terms": ["founding engineer", "first engineer", "early engineer", "0 to 1", "zero to one", "founding member", "founder", "co-founder", "cofounder", "0-1", "0-to-1"],
        "evidence_patterns": ["employee #", "first hire", "seed stage", "series a", "pre-seed", "built the initial", "sole engineer"],
        "entity_type": "Organization",
        "semantic_role": "Experience"
    },
    "OWNERSHIP": {
        "weight": 9,
        "children": {},
        "terms": ["led development", "built from scratch", "system ownership", "owned delivery", "technical ownership", "end to end", "end-to-end"],
        "evidence_patterns": ["led", "owned", "responsible for", "delivered", "shipped", "designed", "architected", "spearheaded", "drove", "solely responsible"],
        "entity_type": "Behavior",
        "semantic_role": "Requirement"
    },
    "PRODUCT_ENGINEERING": {
        "weight": 8,
        "children": {},
        "terms": ["product engineer", "product-led", "saas", "consumer product", "b2b saas", "product mindset"],
        "evidence_patterns": ["worked closely with product", "user-facing", "customer-facing", "product requirements", "shipped product"],
        "entity_type": "BusinessSignal",
        "semantic_role": "Experience"
    },
    "MARKETPLACE_SYSTEMS": {
        "weight": 7,
        "children": {},
        "terms": ["marketplace", "two-sided market", "supply and demand", "matching engine"],
        "entity_type": "BusinessSignal",
        "semantic_role": "Experience"
    },
    "AMBIGUITY_TOLERANCE": {
        "weight": 9,
        "children": {},
        "terms": ["ambiguity tolerance", "unstructured environment"],
        "evidence_patterns": ["built from scratch", "greenfield", "zero-to-one", "0 to 1", "first engineer", "founding engineer", "prototype", "mvp", "rapid iteration", "agile environment"],
        "entity_type": "Behavior",
        "semantic_role": "Requirement"
    },
    "SHIPPING_VELOCITY": {
        "weight": 9,
        "children": {},
        "terms": ["shipping velocity", "fast paced environment"],
        "evidence_patterns": ["shipped", "fast-paced", "delivered", "startup", "tight deadlines", "rapidly deployed", "sprints", "continuous deployment", "ci/cd"],
        "entity_type": "Behavior",
        "semantic_role": "Requirement"
    },
    "SYSTEMS_THINKING": {
        "weight": 8,
        "children": {},
        "terms": ["systems thinking", "system design", "distributed systems architecture"],
        "evidence_patterns": ["architected", "designed the architecture", "system design", "scale", "bottlenecks", "microservices architecture", "system constraints"],
        "entity_type": "Behavior",
        "semantic_role": "Requirement"
    }
}

EXPERT_NEGATIVE = {
    "LANGCHAIN_ONLY_EXPERIENCE": {
        "weight": 9,
        "children": {},
        "terms": ["langchain wrappers", "langchain wrapper", "langchain only", "api wrappers", "api wrapper", "openai wrapper", "gpt wrapper"],
        "evidence_patterns": ["only used langchain", "no custom training", "prompt engineering only"],
        "entity_type": "Technology",
        "semantic_role": "NegativeSignal"
    },
    "CONSULTING_ONLY_BACKGROUND": {
        "weight": 9,
        "children": {},
        "terms": ["client delivery", "outsourced projects", "offshore development"],
        "evidence_patterns": ["consultant for", "external client", "agency work", "delivered to client"],
        "entity_type": "BusinessSignal",
        "semantic_role": "NegativeSignal"
    },
    "TITLE_CHASERS": {
        "weight": 7,
        "children": {},
        "terms": ["title chasers"],
        "evidence_patterns": ["vp in 1 year", "director after 6 months", "cxo title"],
        "entity_type": "Behavior",
        "semantic_role": "NegativeSignal"
    }
}
