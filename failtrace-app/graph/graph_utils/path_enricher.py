import networkx as nx
from typing import Any, Dict, List

def enrich_path_with_metadata(
    graph: nx.DiGraph,
    path: List[Any]
) -> List[Dict[str, Any]]:
    """
    غنی‌سازی مسیرها با متادیتای گراف و نگاشت external bare names به شناسه‌های واقعی:
     - node: شناسه‌ی گره (resolve برای External bare names)
     - type, file, line, is_test, status, docstring
    """
    enriched = []
    for node in path:
        raw = node["node"] if isinstance(node, dict) else node

        # اگر bare external name است، سعی می‌کنیم match کنیم به یک تابع پایتونی
        data0 = graph.nodes.get(raw, {})
        if data0.get("type") == "external":
            candidates = [
                nid
                for nid, d in graph.nodes(data=True)
                if d.get("type") == "function" and nid.endswith(f"::{raw}")
            ]
            node_id = candidates[0] if candidates else raw
        else:
            node_id = raw

        data = graph.nodes.get(node_id, {})

        enriched.append({
            "node":      node_id,
            "type":      data.get("type"),
            "file":      data.get("file"),
            "line":      data.get("start_line") or data.get("line"),
            "is_test":   data.get("is_test", False),
            "status":    data.get("test_status", "not_executed"),
            "docstring": data.get("docstring", ""),
        })

    return enriched
