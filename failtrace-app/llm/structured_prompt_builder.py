import json
import os
import math
from typing import Dict, List, Any, Tuple

from graph.graph_builder import build_graph
from utils.file_ops import load_json
from analysis.mapper import load_test_logs, tag_graph_with_logs
from analysis.summarizer import build_test_summary
from analysis.critical_path_extractor import find_critical_paths


def get_error_message(summary: Dict, test_name: str) -> str:
    for failed in summary.get("failed_detail", []):
        if failed.get("name") == test_name:
            return failed.get("error", "")
    return ""


def _compute_base_k(num_nodes: int) -> int:
    if num_nodes <= 0:
        return 3
    denom = math.log1p(1200.0)
    ratio = math.log1p(float(num_nodes)) / denom
    base = 3 + int(math.floor(9.0 * max(0.0, min(1.0, ratio))))
    return max(3, min(12, base))


def _compute_alpha(num_nodes: int, num_edges: int) -> float:
    if num_nodes <= 0:
        return 0.7
    avg_out = (float(num_edges) / float(num_nodes)) if num_nodes else 0.0
    t = min(1.0, max(0.0, avg_out / 8.0))
    return 0.55 + 0.30 * t


def _k_for_test(unique_loci_count: int, base_k: int, alpha: float) -> int:
    if unique_loci_count <= 0:
        return 0
    return min(base_k, max(3, int(round(alpha * unique_loci_count))))


def _last_internal_non_test(
    step_path: List[Dict[str, Any]],
) -> Tuple[str | None, str | None]:
    for step in reversed(step_path):
        if not isinstance(step, dict):
            continue
        if step.get("is_test", False):
            continue
        if step.get("type") == "external":
            continue
        node_id = step.get("node")
        file = step.get("file")
        if node_id:
            return node_id, file
    return None, None


def _freq_counts(
    downstream_paths: List[List[Dict[str, Any]]],
) -> Tuple[Dict[str, int], Dict[str, int]]:
    func_freq: Dict[str, int] = {}
    file_freq: Dict[str, int] = {}
    for path in downstream_paths:
        nid, f = _last_internal_non_test(path)
        if nid:
            func_freq[nid] = func_freq.get(nid, 0) + 1
        if f:
            file_freq[f] = file_freq.get(f, 0) + 1
    return func_freq, file_freq


def _top_k(freq: Dict[str, int], k: int) -> List[str]:
    if k <= 0 or not freq:
        return []
    items = sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))
    return [key for key, _ in items[:k]]


def _build_hotspots_for_test(
    downstream_paths: List[List[Dict[str, Any]]], base_k: int, alpha: float
) -> Dict[str, List[str]]:
    func_freq, file_freq = _freq_counts(downstream_paths)
    U = len(func_freq)
    if U == 0:
        return {"functions": [], "files": []}
    k_test = _k_for_test(U, base_k, alpha)
    return {"functions": _top_k(func_freq, k_test), "files": _top_k(file_freq, k_test)}


def build_structured_prompt(
    project_path: str,
    log_path: str,
    lang: str,
    output_path: str = "output/llm_prompt.json",
) -> Dict:
    graph = build_graph(project_path)
    logs = load_test_logs(log_path, lang)
    graph = tag_graph_with_logs(graph, logs, lang)

    summary = build_test_summary(graph)
    critical_paths_raw = find_critical_paths(graph)

    nodes = graph.number_of_nodes()
    edges = graph.number_of_edges()
    meta = {
        "project_path": project_path,
        "log_path": log_path,
        "language": lang,
        "graph": {"nodes": nodes, "edges": edges},
    }

    base_k = _compute_base_k(nodes)
    alpha = _compute_alpha(nodes, edges)

    enriched_critical: Dict[str, Dict[str, Any]] = {}
    hotspots: Dict[str, Dict[str, List[str]]] = {}

    for test_name, paths in critical_paths_raw.items():
        up = paths.get("upstream", []) or []
        down = paths.get("downstream", []) or []
        enriched_critical[test_name] = {
            "error": get_error_message(summary, test_name),
            "upstream": up,
            "downstream": down,
        }
        hotspots[test_name] = _build_hotspots_for_test(down, base_k, alpha)

    structured_prompt: Dict[str, Any] = {
        "meta": meta,
        "summary": summary,
        "critical_paths": enriched_critical,
        "hotspots": hotspots,
    }

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(structured_prompt, f, indent=2, ensure_ascii=False)

    return structured_prompt
