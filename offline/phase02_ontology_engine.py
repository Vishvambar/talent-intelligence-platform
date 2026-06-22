import json
import os

ONTOLOGY = {
    "RETRIEVAL": [
        "retrieval", "information retrieval", "ir system",
        "semantic search", "semantic retrieval",
        "rag", "retrieval augmented generation",
        "recommendation system", "recommender system",
        "search relevance", "search ranking",
        "dense retrieval", "sparse retrieval",
        "neural retrieval", "document retrieval"
    ],
    "VECTOR_DB": [
        "qdrant", "pinecone", "milvus", "weaviate",
        "faiss", "chroma", "vespa", "opensearch",
        "elasticsearch knn", "vector database",
        "vector store", "ann", "approximate nearest neighbor",
        "hnsw", "ivf"
    ],
    "EMBEDDINGS": [
        "embedding", "embeddings", "sentence transformer",
        "sentence-transformers", "openai embeddings",
        "text embeddings", "e5", "bge", "ada",
        "dense vector", "semantic embedding",
        "contrastive learning", "bi-encoder",
        "cross-encoder"
    ],
    "EVALUATION": [
        "ndcg", "normalized discounted cumulative gain",
        "map", "mean average precision",
        "mrr", "mean reciprocal rank",
        "precision at k", "recall at k",
        "ab testing", "a/b test", "online evaluation",
        "offline evaluation", "ranking quality",
        "search evaluation", "relevance evaluation",
        "click-through rate", "ctr model"
    ],
    "PRODUCT_COMPANY": [
        "startup", "saas", "product company", "product-led",
        "b2b saas", "b2c", "consumer product",
        "tech company", "series a", "series b",
        "growth stage", "early stage"
    ],
    "FOUNDING_TEAM": [
        "founding engineer", "founding team", "founding member",
        "first engineer", "early engineer", "employee number",
        "employee #", "0 to 1", "zero to one",
        "built from scratch", "greenfield",
        "early employee", "initial team",
        "co-founder", "technical co-founder"
    ],
    "OWNERSHIP": [
        "led", "built", "architected", "designed",
        "shipped", "deployed", "scaled", "launched",
        "productionized", "owned", "drove", "delivered",
        "end to end", "end-to-end", "from scratch"
    ],
    "ML_AI": [
        "machine learning", "deep learning",
        "nlp", "natural language processing",
        "llm", "large language model",
        "transformer", "bert", "gpt",
        "fine-tuning", "finetuning",
        "pytorch", "tensorflow", "model training",
        "ml pipeline", "feature engineering",
        "model serving", "mlops"
    ]
}

ONTOLOGY_LOWER = {
    group: [term.lower() for term in terms]
    for group, terms in ONTOLOGY.items()
}

def compute_ontology_scores(text: str) -> dict:
    """
    Returns a dict of group_name -> coverage_score (0.0 to 1.0)
    for each ontology group based on how many terms appear in text.
    """
    text_lower = text.lower()
    scores = {}
    for group, terms in ONTOLOGY_LOWER.items():
        matches = sum(1 for term in terms if term in text_lower)
        scores[group] = min(1.0, matches / max(1, len(terms) * 0.3))
    return scores

def run():
    print("Starting Phase 2: Domain Ontology Engine...")
    
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    artifacts_dir = os.path.join(project_root, "data", "artifacts")
    os.makedirs(artifacts_dir, exist_ok=True)
    
    out_path = os.path.join(artifacts_dir, "ontology.json")
    with open(out_path, "w") as f:
        json.dump(ONTOLOGY_LOWER, f, indent=2)
        
    print(f"Ontology manually frozen and saved to {out_path}")
    
    # Run test verification
    print("\nVerification Test:")
    test_str = "I built a RAG system using Pinecone and evaluated with NDCG"
    print(f"Text: '{test_str}'")
    scores = compute_ontology_scores(test_str)
    for k, v in scores.items():
        if v > 0:
            print(f"  {k}: {v:.2f}")

if __name__ == "__main__":
    run()
