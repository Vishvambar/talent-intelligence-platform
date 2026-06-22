import json
import os
import re
import hashlib
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARTIFACTS_DIR = os.path.join(PROJECT_ROOT, "data", "artifacts")

# Frozen Expert Rules (V12)
EXPERT_ONTOLOGY = {
    "RETRIEVAL": {
        "weight": 10,
        "children": ["VECTOR_DB", "EMBEDDINGS", "SEARCH_RELEVANCE"],
        "terms": ["retrieval", "ir system", "semantic search", "rag", "retrieval augmented generation", "information retrieval"]
    },
    "VECTOR_DB": {
        "weight": 8,
        "children": [],
        "terms": ["qdrant", "pinecone", "milvus", "faiss", "vector database", "weaviate", "chroma"]
    },
    "EMBEDDINGS": {
        "weight": 8,
        "children": [],
        "terms": ["embedding", "embeddings", "sentence transformer", "openai embeddings", "bge", "e5", "dense vector", "cross-encoder"]
    },
    "SEARCH_RELEVANCE": {
        "weight": 9,
        "children": ["EVALUATION"],
        "terms": ["search relevance", "search ranking", "ranking model", "relevance ranking", "ranking algorithms", "search quality", "ranking", "relevance"]
    },
    "EVALUATION": {
        "weight": 10,
        "children": [],
        "terms": ["ndcg", "map", "mrr", "precision at k", "offline evaluation", "ab testing", "a/b test"]
    },
    "EXPERIMENTATION": {
        "weight": 8,
        "children": [],
        "terms": ["experimentation", "online evaluation", "statistical significance"]
    },
    "ASYNC_WRITING_CULTURE": {
        "weight": 8,
        "children": [],
        "terms": ["written communication", "async-first", "technical writing", "documentation culture", "rfc", "architecture decision record", "adr"]
    },
    "OPEN_SOURCE_CONTRIBUTIONS": {
        "weight": 5,
        "children": [],
        "terms": ["open-source contributions", "oss contributions", "open source", "open-source", "github contributor", "maintainer", "pull request", "contributor"]
    },
    "ML_INFRASTRUCTURE": {
        "weight": 7,
        "children": [],
        "terms": ["mlops", "model serving", "ml pipeline", "inference latency", "triton", "tensorrt"]
    },
    "FOUNDING_TEAM": {
        "weight": 10,
        "children": [],
        "terms": ["founding engineer", "first engineer", "early engineer", "0 to 1", "zero to one", "founding member", "founder", "co-founder", "cofounder", "0-1", "0-to-1"]
    },
    "OWNERSHIP": {
        "weight": 9,
        "children": [],
        "terms": ["led development", "built from scratch", "architected", "system ownership", "owned delivery", "technical ownership", "shipped", "end to end", "end-to-end"]
    },
    "PRODUCT_ENGINEERING": {
        "weight": 8,
        "children": [],
        "terms": ["product engineer", "product-led", "saas", "consumer product", "b2b saas", "product mindset"]
    },
    "MARKETPLACE_SYSTEMS": {
        "weight": 7,
        "children": [],
        "terms": ["marketplace", "two-sided market", "supply and demand", "matching engine"]
    },
    "LANGCHAIN_ONLY_EXPERIENCE": {
        "weight": 9,
        "children": [],
        "terms": ["langchain wrappers", "langchain wrapper", "langchain only", "api wrappers", "api wrapper", "openai wrapper", "gpt wrapper"]
    },
    "CONSULTING_ONLY_BACKGROUND": {
        "weight": 9,
        "children": [],
        "terms": ["client delivery", "outsourced projects", "offshore development"]
    }
}

BANNED_COMPANIES = {"tcs", "infosys", "accenture", "cognizant", "wipro", "capgemini", "ibm"}

def hash_file(path: str) -> str:
    hasher = hashlib.sha256()
    with open(path, 'rb') as f:
        hasher.update(f.read())
    return hasher.hexdigest()

def validate_ontology(positive_nodes: dict, negative_nodes: dict):
    all_nodes = {**positive_nodes, **negative_nodes}
    
    for node, data in all_nodes.items():
        # Weight bounds
        weight = data.get("weight", 5)
        if not (1 <= weight <= 10):
            raise ValueError(f"Node {node} has invalid weight {weight}. Must be between 1 and 10.")
            
        # Empty nodes
        terms = data.get("terms", [])
        if not terms:
            raise ValueError(f"Node {node} is empty (no terms).")
            
        seen_in_node = set()
        # Company names & intra-node duplicates
        for term in terms:
            term_lower = term.lower()
            for banned in BANNED_COMPANIES:
                if banned in term_lower:
                    raise ValueError(f"Node {node} contains banned company name: {banned} in term '{term}'")
            
            if term_lower in seen_in_node:
                raise ValueError(f"Duplicate term found in node {node}: '{term}'")
            seen_in_node.add(term_lower)

def compile_regex(term: str) -> str:
    escaped = re.escape(term.lower())
    return r"\b" + escaped + r"\b"

def bootstrap_ontology():
    jd_req_path = os.path.join(ARTIFACTS_DIR, "jd_requirements.json")
    if not os.path.exists(jd_req_path):
        raise FileNotFoundError(f"Missing {jd_req_path}. Run Phase 1 first.")
        
    with open(jd_req_path, 'r') as f:
        jd_reqs = json.load(f)
        
    jd_hash = hash_file(jd_req_path)
    
    positive_nodes = {}
    negative_nodes = {}
    
    CANONICAL_NODE_MAP = {
        "EVALUATION_FRAMEWORKS": "EVALUATION",
        "EMBEDDINGS_RETRIEVAL": "EMBEDDINGS",
        "PRODUCT_ENGINEERING_BACKGROUND": "PRODUCT_ENGINEERING",
        "VECTOR_DATABASES": "VECTOR_DB"
    }
    
    def process_node(key, data, is_negative=False):
        key = key.upper()
        if key in CANONICAL_NODE_MAP:
            key = CANONICAL_NODE_MAP[key]
            
        terms = data.get("canonical_terms", []) + data.get("synonyms", [])
        
        # Deduplicate terms case-insensitively
        unique_terms = []
        seen = set()
        for t in terms:
            t_lower = t.lower()
            if t_lower not in seen:
                seen.add(t_lower)
                unique_terms.append(t)
                
        if unique_terms:
            weight_key = "penalty_strength" if is_negative else "importance"
            weight = data.get(weight_key, 5)
            
            target_dict = negative_nodes if is_negative else positive_nodes
            
            if key in target_dict:
                # Merge into existing canonical node (case-insensitive)
                existing_terms = target_dict[key]["terms"]
                existing_lower = {t.lower() for t in existing_terms}
                for t in unique_terms:
                    if t.lower() not in existing_lower:
                        existing_terms.append(t)
                        existing_lower.add(t.lower())
                target_dict[key]["weight"] = max(target_dict[key]["weight"], weight)
                target_dict[key]["terms"] = existing_terms
            else:
                target_dict[key] = {
                    "weight": weight,
                    "children": [],
                    "terms": unique_terms
                }

    # Process JD Requirements
    for key, data in jd_reqs.get("hard_requirements", {}).items():
        process_node(key, data, False)
        
    for key, data in jd_reqs.get("preferred_requirements", {}).items():
        process_node(key, data, False)
        
    for key, data in jd_reqs.get("negative_signals", {}).items():
        process_node(key, data, True)
            
    # Merge Expert Ontology
    for key, data in EXPERT_ONTOLOGY.items():
        if key in positive_nodes:
            positive_nodes[key]["weight"] = max(positive_nodes[key]["weight"], data["weight"])
            positive_nodes[key]["children"] = list(set(positive_nodes[key]["children"] + data["children"]))
            
            existing_lower = {t.lower() for t in positive_nodes[key]["terms"]}
            for t in data["terms"]:
                if t.lower() not in existing_lower:
                    positive_nodes[key]["terms"].append(t)
                    existing_lower.add(t.lower())
                    
        elif key in negative_nodes:
            negative_nodes[key]["weight"] = max(negative_nodes[key]["weight"], data["weight"])
            negative_nodes[key]["children"] = list(set(negative_nodes[key]["children"] + data["children"]))
            
            existing_lower = {t.lower() for t in negative_nodes[key]["terms"]}
            for t in data["terms"]:
                if t.lower() not in existing_lower:
                    negative_nodes[key]["terms"].append(t)
                    existing_lower.add(t.lower())
                    
        else:
            unique_terms = []
            seen = set()
            for t in data["terms"]:
                t_lower = t.lower()
                if t_lower not in seen:
                    seen.add(t_lower)
                    unique_terms.append(t)
            
            if unique_terms:
                new_data = data.copy()
                new_data["terms"] = unique_terms
                positive_nodes[key] = new_data

    # Compile regexes
    for node_dict in (positive_nodes, negative_nodes):
        for key, data in node_dict.items():
            data["regexes"] = [compile_regex(t) for t in data["terms"]]
            
    # Validation step
    validate_ontology(positive_nodes, negative_nodes)
    
    ontology = {
        "POSITIVE_ONTOLOGY": positive_nodes,
        "NEGATIVE_ONTOLOGY": negative_nodes,
        "metadata": {
            "version": "v12",
            "generated_from_jd_hash": jd_hash,
            "generated_from_jd_timestamp": datetime.utcnow().isoformat() + "Z",
            "ontology_nodes": len(positive_nodes) + len(negative_nodes),
            "positive_nodes": len(positive_nodes),
            "negative_nodes": len(negative_nodes)
        }
    }
    
    out_path = os.path.join(ARTIFACTS_DIR, "ontology.json")
    with open(out_path, 'w') as f:
        json.dump(ontology, f, indent=2)
        
    print(f"Ontology frozen and saved to {out_path} with {ontology['metadata']['ontology_nodes']} nodes.")
    return ontology

# Global cache for feature extraction
_ONTOLOGY_CACHE = None

def compute_ontology_feature_vector(text: str) -> dict:
    global _ONTOLOGY_CACHE
    if _ONTOLOGY_CACHE is None:
        ont_path = os.path.join(ARTIFACTS_DIR, "ontology.json")
        if not os.path.exists(ont_path):
            raise FileNotFoundError("ontology.json not found. Run Phase 2 first.")
        with open(ont_path, 'r') as f:
            _ONTOLOGY_CACHE = json.load(f)
            
    text_lower = text.lower()
    features = {}
    base_coverages = {}
    
    def get_coverage(data):
        regexes = data.get("regexes", [])
        if not regexes:
            return 0.0
        matches = sum(1 for r in regexes if re.search(r, text_lower))
        return matches / len(regexes)

    for node, data in _ONTOLOGY_CACHE.get("POSITIVE_ONTOLOGY", {}).items():
        base_coverages[node] = get_coverage(data)
        
    for node, data in _ONTOLOGY_CACHE.get("NEGATIVE_ONTOLOGY", {}).items():
        base_coverages[node] = get_coverage(data)

    propagated_coverages = base_coverages.copy()
    all_nodes = {**_ONTOLOGY_CACHE.get("POSITIVE_ONTOLOGY", {}), **_ONTOLOGY_CACHE.get("NEGATIVE_ONTOLOGY", {})}
    
    # Propagate 3 levels deep
    for _ in range(3):
        new_coverages = propagated_coverages.copy()
        for node, data in all_nodes.items():
            children = data.get("children", [])
            if children:
                child_scores = [propagated_coverages.get(c, 0.0) for c in children]
                max_child = max(child_scores) if child_scores else 0.0
                new_coverages[node] = max(propagated_coverages[node], 0.5 * max_child)
        propagated_coverages = new_coverages

    # Generate Feature Vector (Normalized 0.0 to 1.0)
    for node, data in all_nodes.items():
        coverage = propagated_coverages.get(node, 0.0)
        
        # Clamp at 1.0 just in case
        normalized_score = min(1.0, coverage)
        
        feature_name = f"{node.lower()}_score"
        features[feature_name] = round(normalized_score, 3)
        
        # Also expose raw match count for debugging/transparency
        matches = sum(1 for r in data.get("regexes", []) if re.search(r, text_lower))
        features[f"{node.lower()}_matches"] = matches

    return features

def run():
    print("Executing Phase 2 Implementation...")
    bootstrap_ontology()
    
    print("\n--- Auditing Phase 2 Coverage ---")
    
    cand1 = "Pinecone FAISS Qdrant"
    print(f"Test 1 - Candidate: '{cand1}'")
    fv1 = compute_ontology_feature_vector(cand1)
    print(f"  vector_db_score: {fv1.get('vector_db_score', 0)}")
    print(f"  retrieval_score: {fv1.get('retrieval_score', 0)}")
    
    cand2 = "Built LangChain wrappers only"
    print(f"\nTest 2 - Candidate: '{cand2}'")
    fv2 = compute_ontology_feature_vector(cand2)
    print(f"  langchain_only_experience_score: {fv2.get('langchain_only_experience_score', 0)}")
    
    cand3 = "Roadmap planning"
    print(f"\nTest 3 - Candidate: '{cand3}'")
    fv3 = compute_ontology_feature_vector(cand3)
    print(f"  evaluation_score: {fv3.get('evaluation_score', 0)}")

if __name__ == "__main__":
    run()
