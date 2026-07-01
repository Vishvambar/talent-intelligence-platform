import json
import os
import re
import hashlib
from datetime import datetime
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(PROJECT_ROOT)

from config.ontology.expert_nodes import EXPERT_POSITIVE, EXPERT_NEGATIVE
from config.ontology.hierarchy import CANONICAL_NODE_MAP
from config.ontology.entity_validation import ENTITY_RULES

ARTIFACTS_DIR = os.path.join(PROJECT_ROOT, "data", "artifacts")
PHASE01_DIR = os.path.join(ARTIFACTS_DIR, "phase01")
PHASE02_DIR = os.path.join(ARTIFACTS_DIR, "phase02")
os.makedirs(PHASE02_DIR, exist_ok=True)

def hash_file(path: str) -> str:
    hasher = hashlib.sha256()
    if os.path.exists(path):
        with open(path, 'rb') as f:
            hasher.update(f.read())
        return hasher.hexdigest()
    return "unknown"

def find_cycle(node, graph, visited, rec_stack, path):
    visited.add(node)
    rec_stack.add(node)
    path.append(node)
    
    for neighbor in graph.get(node, {}).keys():
        if neighbor not in visited:
            cycle_path = find_cycle(neighbor, graph, visited, rec_stack, path)
            if cycle_path:
                return cycle_path
        elif neighbor in rec_stack:
            idx = path.index(neighbor)
            return path[idx:] + [neighbor]
            
    rec_stack.remove(node)
    path.pop()
    return None

def validate_ontology(positive_nodes: dict, negative_nodes: dict):
    all_nodes = {**positive_nodes, **negative_nodes}
    graph = {}
    
    for node, data in all_nodes.items():
        weight = data.get("weight", 5)
        if not (0 <= weight <= 10):
            raise ValueError(f"Node {node} has invalid weight {weight}. Must be between 0 and 10.")
            
        terms = data.get("terms", [])
        if not terms:
            raise ValueError(f"Node {node} is empty (no terms).")
            
        # Entity Validation
        entity_type = data.get("entity_type", "Technology")
        if node in ENTITY_RULES:
            allowed_types = ENTITY_RULES[node].get("expected_entity_type", [])
            if allowed_types and entity_type not in allowed_types:
                raise ValueError(f"Entity Validation Failed: '{node}' was assigned entity_type '{entity_type}', but must be one of {allowed_types}.")
            
        seen_in_node = set()
        for term in terms:
            term_lower = term.lower()
            if term_lower in seen_in_node:
                raise ValueError(f"Duplicate term found in node {node}: '{term}'")
            seen_in_node.add(term_lower)
            
        children = data.get("children", {})
        graph[node] = children
        
        for child in children:
            if child not in all_nodes:
                raise ValueError(f"Orphan node detected: '{child}' is a child of '{node}', but does not exist in the graph.")
        
    visited = set()
    rec_stack = set()
    for node in graph:
        if node not in visited:
            cycle = find_cycle(node, graph, visited, rec_stack, [])
            if cycle:
                cycle_str = " -> ".join(cycle)
                raise ValueError(f"Cycle detected in Ontology Graph:\n{cycle_str}")

def normalize_term(term: str) -> str:
    term = re.sub(r'([a-z])([A-Z])', r'\1 \2', term)
    return term.lower()

def compile_regex(term: str) -> str:
    norm = normalize_term(term)
    pieces = re.split(r'[\s\-_/.]+', norm)
    escaped_pieces = [re.escape(p) for p in pieces if p]
    pattern = r'[\s\-_/.]+'.join(escaped_pieces)
    return r"\b" + pattern + r"\b"

def build_canonical_graph():
    jd_req_path = os.path.join(PHASE01_DIR, "jd_requirements.json")
    if not os.path.exists(jd_req_path):
        raise FileNotFoundError(f"Missing {jd_req_path}. Run Phase 1 first.")
        
    with open(jd_req_path, 'r') as f:
        jd_reqs = json.load(f)
        
    jd_hash = hash_file(jd_req_path)
    
    positive_nodes = {}
    negative_nodes = {}
    
    SCORE_SCALE = 10
    
    def process_node(key, data, is_negative=False):
        key = key.upper()
        if key in CANONICAL_NODE_MAP:
            key = CANONICAL_NODE_MAP[key]
            
        terms = data.get("canonical_terms", []) + data.get("synonyms", [])
        if not terms:
            terms = [key.lower().replace("_", " ")]
            
        unique_terms = []
        seen = set()
        for t in terms:
            t_lower = t.lower()
            if t_lower not in seen:
                seen.add(t_lower)
                unique_terms.append(t)
                
        if unique_terms:
            if is_negative:
                weight = data.get("penalty_strength", data.get("penalty_weight", 0.5) * SCORE_SCALE)
            else:
                weight = data.get("importance", data.get("priority_weight", 0.5) * SCORE_SCALE)
            
            target_dict = negative_nodes if is_negative else positive_nodes
            
            ent_type = data.get("entity_type", "Technology")
            if key in ENTITY_RULES and ENTITY_RULES[key].get("expected_entity_type"):
                allowed = ENTITY_RULES[key]["expected_entity_type"]
                if ent_type not in allowed:
                    ent_type = allowed[0]
                    
            if key in target_dict:
                existing_terms = target_dict[key]["terms"]
                existing_lower = {t.lower() for t in existing_terms}
                for t in unique_terms:
                    if t.lower() not in existing_lower:
                        existing_terms.append(t)
                        existing_lower.add(t.lower())
                target_dict[key]["weight"] = max(target_dict[key]["weight"], weight)
                target_dict[key]["terms"] = existing_terms
                target_dict[key]["contributors"] = list(set(target_dict[key].get("contributors", []) + data.get("contributors", [])))
                target_dict[key]["entity_type"] = ent_type
            else:
                target_dict[key] = {
                    "weight": weight,
                    "children": {},
                    "parents": {},
                    "terms": unique_terms,
                    "entity_type": ent_type,
                    "semantic_role": data.get("semantic_role", "Requirement" if not is_negative else "NegativeSignal"),
                    "extraction_confidence": data.get("extraction_confidence", 0.8),
                    "aggregation_confidence": data.get("aggregation_confidence", 0.8),
                    "contributors": data.get("contributors", []),
                    "origin": "JD"
                }

    # 1. Load Recruiter Graph
    for key, data in jd_reqs.get("hard_requirements", {}).items(): process_node(key, data, False)
    for key, data in jd_reqs.get("preferred_requirements", {}).items(): process_node(key, data, False)
    for key, data in jd_reqs.get("negative_signals", {}).items(): process_node(key, data, True)
        
    hiring_intent = jd_reqs.get("hiring_intent", {})
    for section in ["technical_priorities", "behavioral_priorities", "business_priorities", "implicit_priorities"]:
        for key, data in hiring_intent.get(section, {}).items():
            process_node(key, data, False)
            for child, child_weight in data.get("children", {}).items():
                process_node(child, {"priority_weight": child_weight, "entity_type": data.get("entity_type", "Technology"), "semantic_role": data.get("semantic_role", "Skill")}, False)
                parent_key = CANONICAL_NODE_MAP.get(key.upper(), key.upper())
                child_key = CANONICAL_NODE_MAP.get(child.upper(), child.upper())
                
                if parent_key in positive_nodes:
                    positive_nodes[parent_key]["children"][child_key] = max(positive_nodes[parent_key]["children"].get(child_key, 0.0), child_weight)
                    if child_key in positive_nodes:
                        positive_nodes[child_key]["parents"][parent_key] = max(positive_nodes[child_key]["parents"].get(parent_key, 0.0), child_weight)
            
    # 2. Merge Expert Graphs
    def merge_expert(expert_dict, target_nodes):
        for key, data in expert_dict.items():
            if key in target_nodes:
                target_nodes[key]["weight"] = max(target_nodes[key]["weight"], data["weight"])
                for child, w in data.get("children", {}).items():
                    target_nodes[key]["children"][child] = max(target_nodes[key]["children"].get(child, 0.0), w)
                    if child in target_nodes:
                        target_nodes[child]["parents"][key] = max(target_nodes[child]["parents"].get(key, 0.0), w)
                existing_lower = {t.lower() for t in target_nodes[key]["terms"]}
                for t in data.get("terms", []) + data.get("evidence_patterns", []):
                    if t.lower() not in existing_lower:
                        target_nodes[key]["terms"].append(t)
                        existing_lower.add(t.lower())
            else:
                target_nodes[key] = {
                    "weight": data["weight"],
                    "children": data.get("children", {}).copy(),
                    "parents": {},
                    "terms": data.get("terms", []).copy() + data.get("evidence_patterns", []).copy(),
                    "entity_type": data.get("entity_type", "Technology"),
                    "semantic_role": data.get("semantic_role", "Skill"),
                    "extraction_confidence": 1.0,
                    "aggregation_confidence": 1.0,
                    "contributors": ["expert_ontology"],
                    "origin": "ExpertOntology"
                }
                
    merge_expert(EXPERT_POSITIVE, positive_nodes)
    merge_expert(EXPERT_NEGATIVE, negative_nodes)

    # Cross-link parents properly for newly injected expert nodes
    all_dicts = (positive_nodes, negative_nodes)
    for ndict in all_dicts:
        for parent_key, parent_data in ndict.items():
            for child_key, w in parent_data.get("children", {}).items():
                if child_key in ndict:
                    ndict[child_key]["parents"][parent_key] = max(ndict[child_key]["parents"].get(parent_key, 0.0), w)
                else:
                    # Auto-create orphans
                    default_type = "Technology"
                    if child_key in ENTITY_RULES and ENTITY_RULES[child_key].get("expected_entity_type"):
                        default_type = ENTITY_RULES[child_key]["expected_entity_type"][0]
                    process_node(child_key, {"priority_weight": 0.5, "entity_type": default_type, "semantic_role": "Skill"}, is_negative=(ndict is negative_nodes))
                    ndict[child_key]["parents"][parent_key] = w

    # 4. Compile regexes
    for node_dict in (positive_nodes, negative_nodes):
        for key, data in node_dict.items():
            data["regexes"] = [compile_regex(t) for t in data["terms"]]
            
    # 5. Validate DAG
    validate_ontology(positive_nodes, negative_nodes)
    
    ontology = {
        "POSITIVE_ONTOLOGY": positive_nodes,
        "NEGATIVE_ONTOLOGY": negative_nodes,
        "metadata": {
            "phase1_schema_version": jd_reqs.get("metadata", {}).get("schema_version", "unknown"),
            "expert_ontology_version": "v3.0",
            "merge_strategy_version": "v4.0_stageB",
            "generated_from_jd_hash": jd_hash,
            "generated_from_jd_timestamp": datetime.utcnow().isoformat() + "Z",
            "positive_nodes": len(positive_nodes),
            "negative_nodes": len(negative_nodes)
        }
    }
    
    out_path = os.path.join(PHASE02_DIR, "ontology.json")
    with open(out_path, 'w') as f:
        json.dump(ontology, f, indent=2)
        
    print(f"Ontology frozen and saved to {out_path} with {len(positive_nodes) + len(negative_nodes)} nodes.")
    return ontology

_ONTOLOGY_CACHE = None

def compute_candidate_graph_features(text: str, candidate_id: str = "unknown") -> tuple:
    global _ONTOLOGY_CACHE
    if _ONTOLOGY_CACHE is None:
        ont_path = os.path.join(PHASE02_DIR, "ontology.json")
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
    
    EPS = 1e-4
    candidate_graph_edges = []
    
    changed = True
    while changed:
        changed = False
        new_coverages = propagated_coverages.copy()
        
        for parent, data in all_nodes.items():
            children = data.get("children", {})
            if children:
                parent_importance = data.get("weight", 5.0) / 10.0
                parent_confidence = data.get("aggregation_confidence", 1.0)
                
                child_scores = []
                for c, edge_weight in children.items():
                    child_cov = propagated_coverages.get(c, 0.0)
                    proposed = edge_weight * parent_importance * child_cov * parent_confidence
                    child_scores.append(proposed)
                    
                if child_scores:
                    max_c = max(child_scores)
                    avg_c = sum(child_scores) / len(child_scores)
                    
                    new_val = max(propagated_coverages[parent], max_c, avg_c)
                    if new_val > new_coverages[parent] + EPS:
                        new_coverages[parent] = new_val
                        changed = True
                        
        propagated_coverages = new_coverages

    # Generate edge records for candidate_graph.parquet
    for parent, data in all_nodes.items():
        parent_cov = propagated_coverages.get(parent, 0.0)
        if parent_cov > 0:
            for child, edge_weight in data.get("children", {}).items():
                child_cov = propagated_coverages.get(child, 0.0)
                if child_cov > 0:
                    if base_coverages.get(parent, 0.0) > 0:
                        origin = "ResumeExplicit"
                    elif base_coverages.get(child, 0.0) > 0:
                        origin = "ResumeInferred"
                    else:
                        origin = data.get("origin", "OntologyExpansion")
                        
                    candidate_graph_edges.append({
                        "candidate_id": candidate_id,
                        "parent": parent,
                        "child": child,
                        "edge_weight": edge_weight,
                        "depth": 1,
                        "origin": origin
                    })

    # Stage C Feature Generation
    types = {}
    type_counts = {}
    
    # Graph Topology Stats
    matched_nodes = {n: cov for n, cov in propagated_coverages.items() if cov > 0}
    total_nodes = len(matched_nodes)
    matched_explicit_nodes = sum(1 for n, cov in base_coverages.items() if cov > 0)
    matched_expanded_nodes = total_nodes - matched_explicit_nodes
    expanded_ratio = matched_expanded_nodes / max(1, total_nodes)
    explicit_ratio = matched_explicit_nodes / max(1, total_nodes)
    
    graph_edge_count = len(candidate_graph_edges)
    leaf_node_count = sum(1 for n in matched_nodes if not all_nodes[n].get("children"))
    root_node_count = sum(1 for n in matched_nodes if not all_nodes[n].get("parents"))
    
    hub_node_count = sum(1 for n in matched_nodes if len(all_nodes[n].get("children", {})) >= 3)
    isolated_node_count = sum(1 for n in matched_nodes if not all_nodes[n].get("children") and not all_nodes[n].get("parents"))
    
    avg_node_weight = sum(all_nodes[n].get("weight", 5.0) for n in matched_nodes) / max(1, total_nodes)
    max_node_wt = max([all_nodes[n].get("weight", 5.0) for n in matched_nodes] + [0])
    avg_edge_wt = sum(e["edge_weight"] for e in candidate_graph_edges) / max(1, graph_edge_count)
    
    features.update({
        "total_nodes": total_nodes,
        "matched_explicit_nodes": matched_explicit_nodes,
        "matched_expanded_nodes": matched_expanded_nodes,
        "expanded_ratio": round(expanded_ratio, 3),
        "explicit_ratio": round(explicit_ratio, 3),
        "graph_edge_count": graph_edge_count,
        "leaf_node_count": leaf_node_count,
        "root_node_count": root_node_count,
        "hub_node_count": hub_node_count,
        "isolated_node_count": isolated_node_count,
        "average_node_weight": round(avg_node_weight, 3),
        "max_node_weight": round(max_node_wt, 3),
        "average_edge_weight": round(avg_edge_wt, 3)
    })

    # Initialize all node scores to 0.0 for consistent DataFrame width
    for node in all_nodes:
        features[f"{node.lower()}_score"] = 0.0

    for node, coverage in matched_nodes.items():
        data = all_nodes[node]
        normalized_score = min(1.0, coverage)
        features[f"{node.lower()}_score"] = round(normalized_score, 3)
        
        ent_type = data.get("entity_type", "Technology").lower()
        if ent_type not in types: types[ent_type] = 0.0; type_counts[ent_type] = 0
        types[ent_type] += normalized_score
        type_counts[ent_type] += 1

    # Candidate Coverage Vector
    for t in ["technology", "behavior", "business", "experience", "leadership", "research", "negative"]:
        features[f"{t}_node_count"] = type_counts.get(t, 0)
        features[f"{t}_coverage"] = round(types.get(t, 0.0) / max(1, type_counts.get(t, 1)), 3)

    return features, candidate_graph_edges

def process_candidates(candidates: list):
    out_path = os.path.join(ARTIFACTS_DIR, "candidate_features.jsonl")
    
    with open(out_path, "w") as f_out:
        for cand in candidates:
            cid = cand.get("candidate_id", "unknown")
            
            # Concatenate all candidate textual data deterministically
            text_chunks = []
            
            # 1. Profile Summary
            profile = cand.get("profile", {})
            text_chunks.append(profile.get("summary", ""))
            
            # 2. Skills
            for skill in cand.get("skills", []):
                text_chunks.append(skill.get("name", ""))
                
            # 3. Experience
            for exp in cand.get("experience", []):
                text_chunks.append(exp.get("title", ""))
                text_chunks.append(exp.get("description", ""))
                
            # 4. Projects
            for proj in cand.get("projects", []):
                text_chunks.append(proj.get("name", ""))
                text_chunks.append(proj.get("description", ""))
                
            # Combine into a single canonical document
            canonical_text = " \n ".join([str(c) for c in text_chunks if c])
            
            # Generate Deterministic Feature Vector
            features, _ = compute_candidate_graph_features(canonical_text, cid)
            features["candidate_id"] = cid
            
            # Write row to JSONL
            f_out.write(json.dumps(features) + "\n")
            
    print(f"Successfully processed {len(candidates)} candidates and wrote features to {out_path}.")

def process_candidates_stream(candidates_path: str):
    out_path = os.path.join(PHASE02_DIR, "candidate_features.jsonl")
    count = 0
    
    with open(candidates_path, "r") as f_in, open(out_path, "w") as f_out:
        if candidates_path.endswith(".jsonl"):
            for line in f_in:
                if not line.strip(): continue
                cand = json.loads(line)
                count += 1
                
                cid = cand.get("candidate_id", "unknown")
                text_chunks = []
                profile = cand.get("profile", {})
                text_chunks.append(profile.get("summary", ""))
                for skill in cand.get("skills", []):
                    text_chunks.append(skill.get("name", ""))
                for exp in cand.get("experience", []):
                    text_chunks.append(exp.get("title", ""))
                    text_chunks.append(exp.get("description", ""))
                for proj in cand.get("projects", []):
                    text_chunks.append(proj.get("name", ""))
                    text_chunks.append(proj.get("description", ""))
                
                canonical_text = " \n ".join([str(c) for c in text_chunks if c])
                features, _ = compute_candidate_graph_features(canonical_text, cid)
                features["candidate_id"] = cid
                
                f_out.write(json.dumps(features) + "\n")
                if count % 5000 == 0:
                    print(f"Processed {count} candidates...")
        else:
            candidates = json.load(f_in)
            process_candidates(candidates)
            count = len(candidates)
            
    print(f"Successfully processed {count} candidates and wrote features to {out_path}.")

def run():
    print("Executing Phase 2: Universal Candidate Representation Engine...")
    build_canonical_graph()
    
    candidates_path = os.path.join(PROJECT_ROOT, "data", "raw", "candidates.jsonl")
    if os.path.exists(candidates_path):
        process_candidates_stream(candidates_path)
    else:
        print(f"Warning: {candidates_path} not found. Trying sample_candidates.json...")
        sample_path = os.path.join(PROJECT_ROOT, "data", "raw", "sample_candidates.json")
        if os.path.exists(sample_path):
            with open(sample_path, "r") as f:
                candidates = json.load(f)
            process_candidates(candidates)
        else:
            print("No candidate data found.")

if __name__ == "__main__":
    run()
