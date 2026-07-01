from typing import List, Dict

# Defines the allowed semantic types for specific canonical nodes in the ontology
ENTITY_RULES: Dict[str, Dict[str, List[str]]] = {
    "VECTOR_DB": {
        "expected_entity_type": ["Technology", "Framework"]
    },
    "EMBEDDINGS": {
        "expected_entity_type": ["Technology", "Metric"]
    },
    "COMPANY": {
        "expected_entity_type": ["Organization"]
    },
    "OWNERSHIP": {
        "expected_entity_type": ["Behavior", "BusinessSignal"]
    },
    "FOUNDING_TEAM": {
        "expected_entity_type": ["Organization", "Behavior"]
    },
    "RETRIEVAL": {
        "expected_entity_type": ["Technology", "Framework"]
    },
    "SEARCH_RELEVANCE": {
        "expected_entity_type": ["Technology", "Metric"]
    },
    "EVALUATION": {
        "expected_entity_type": ["Metric", "Research"]
    },
    "EXPERIMENTATION": {
        "expected_entity_type": ["Metric", "Research"]
    },
    "ASYNC_WRITING_CULTURE": {
        "expected_entity_type": ["Behavior"]
    },
    "OPEN_SOURCE_CONTRIBUTIONS": {
        "expected_entity_type": ["Behavior", "Person"]
    },
    "ML_INFRASTRUCTURE": {
        "expected_entity_type": ["Technology", "Framework"]
    },
    "PRODUCT_ENGINEERING": {
        "expected_entity_type": ["Technology", "BusinessSignal"]
    },
    "MARKETPLACE_SYSTEMS": {
        "expected_entity_type": ["Technology", "BusinessSignal"]
    }
}
