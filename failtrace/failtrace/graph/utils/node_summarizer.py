import os
import networkx as nx
from typing import Dict, List


def extract_docstring(file_path: str, func_name: str) -> str:
    if not os.path.isfile(file_path):
        return ""

    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    in_func = False
    docstring = ""
    triple_count = 0

    for i, line in enumerate(lines):
        if f"def {func_name}" in line or f"class {func_name}" in line:
            in_func = True
            continue

        if in_func:
            if '"""' in line or "'''" in line:
                triple_count += line.count('"""') + line.count("'''")
                docstring += line.strip() + " "
                if triple_count >= 2:
                    break
            elif triple_count > 0:
                docstring += line.strip() + " "

    return docstring.strip()


def summarize_graph_node(graph: nx.DiGraph, node: str) -> Dict:
    data = graph.nodes[node]
    summary = {
        "node": node,
        "type": data.get("type", "unknown"),
        "file": data.get("file"),
        "line": data.get("start_line"),
        "is_test": data.get("is_test", False),
        "status": data.get("test_status", "not_executed"),
        "docstring": "",
    }

    file_path = data.get("file", "")
    if "::" in node:
        _, name = node.split("::", 1)
        name = name.split(".")[-1]
        summary["docstring"] = extract_docstring(file_path, name)

    return summary


def summarize_critical_paths(
    graph: nx.DiGraph, critical_paths: Dict[str, Dict[str, List[List[Dict]]]]
) -> Dict:

    summary = {}

    for failed_node, paths in critical_paths.items():
        summary[failed_node] = {"upstream": [], "downstream": []}

        for path in paths.get("upstream", []):
            summarized_path = [
                summarize_graph_node(graph, node["node"]) for node in path
            ]
            summary[failed_node]["upstream"].append(summarized_path)

        for path in paths.get("downstream", []):
            summarized_path = [
                summarize_graph_node(graph, node["node"]) for node in path
            ]
            summary[failed_node]["downstream"].append(summarized_path)

    return summary
