import networkx as nx
from typing import Dict, List, Any
from graph.graph_utils.path_enricher import enrich_path_with_metadata


def find_critical_paths(graph: nx.DiGraph) -> Dict[str, Dict[str, List[List[Dict[str, Any]]]]]:
    """
    مسیرهای بحرانی برای تست‌های شکست‌خورده را استخراج می‌کند (upstream/downstream)
    و خروجی enriched برمی‌گرداند.
    """
    critical_paths: Dict[str, Dict[str, List[List[Dict[str, Any]]]]] = {}

    failed_tests = [
        node for node, data in graph.nodes(data=True)
        if data.get("is_test") and data.get("test_status") == "failed"
    ]

    if not failed_tests:
         # Debugging output
        """ print("[critical] No failed tests found.") """
        return {}

    for failed_node in failed_tests:
        upstream = []
        downstream = []

        for node in graph.nodes:
            if node == failed_node:
                continue

            try:
                paths = nx.all_simple_paths(graph, source=node, target=failed_node, cutoff=6)
                for path in paths:
                    enriched_path = enrich_path_with_metadata(graph, path)
                    upstream.append(enriched_path)
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                continue

            try:
                paths = nx.all_simple_paths(graph, source=failed_node, target=node, cutoff=6)
                for path in paths:
                    enriched_path = enrich_path_with_metadata(graph, path)
                    downstream.append(enriched_path)
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                continue

        critical_paths[failed_node] = {
            "upstream": upstream,
            "downstream": downstream
        }
     # Debugging output 
    """ print(f"[critical] Found {len(critical_paths)} critical test nodes.") """
    return critical_paths
