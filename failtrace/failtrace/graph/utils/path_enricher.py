import networkx as nx
from typing import Any, Dict, List, Optional, DefaultDict
from collections import defaultdict


def _top_origin_from_node(node_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:

    origins = node_data.get("origins")
    if isinstance(origins, list) and origins:
        return dict(origins[0])
    return None


def enrich_path_with_metadata(
    graph: nx.DiGraph, path: List[Any]
) -> List[Dict[str, Any]]:

    suffix_index: DefaultDict[str, List[str]] = defaultdict(list)
    for nid, data in graph.nodes(data=True):
        if data.get("type") in {"function", "test"} and isinstance(nid, str):
            simple = nid.rsplit("::", 1)[-1]
            suffix_index[simple].append(nid)

    def _extract_raw(node_any: Any) -> Any:
        return node_any.get("node") if isinstance(node_any, dict) else node_any

    def _external_simple_name(key: str) -> str:

        if not isinstance(key, str):
            return ""
        if key.startswith("external::"):
            tail = key[len("external::") :]
            return tail.split("/", 1)[0] if tail else ""
        if key.startswith("project::"):
            return key[len("project::") :]
        if key.startswith("nuget::"):
            return key[len("nuget::") :]
        return key

    enriched: List[Dict[str, Any]] = []
    prev_node_id: Optional[str] = None

    for node_any in path:
        raw = _extract_raw(node_any)

        data0 = graph.nodes.get(raw, {}) if isinstance(raw, str) else {}

        node_id = raw
        external_key: Optional[str] = None
        resolved_from_external = False
        origin = None

        if data0.get("type") == "external":
            external_key = str(raw)
            simple = _external_simple_name(external_key)
            candidates = suffix_index.get(simple, []) if simple else []

            if candidates:
                node_id = candidates[0]
                resolved_from_external = True
                data = graph.nodes.get(node_id, {})
            else:
                data = data0
                if (
                    prev_node_id
                    and isinstance(prev_node_id, str)
                    and graph.has_edge(prev_node_id, external_key)
                ):
                    ed = graph.get_edge_data(prev_node_id, external_key) or {}
                    origin = ed.get("origin")

                if origin is None:
                    origin = _top_origin_from_node(data0)
        else:
            data = data0

        if origin is None and isinstance(node_id, str) and external_key:
            if prev_node_id and graph.has_edge(prev_node_id, external_key):
                ed = graph.get_edge_data(prev_node_id, external_key) or {}
                if "origin" in ed:
                    origin = ed["origin"]

        enriched.append(
            {
                "node": node_id,
                "type": data.get("type"),
                "file": data.get("file"),
                "line": data.get("start_line") or data.get("line"),
                "is_test": data.get("is_test", False),
                "status": data.get("test_status", "not_executed"),
                "docstring": data.get("docstring", ""),
                **({"origin": origin} if origin is not None else {}),
                **({"external_key": external_key} if external_key is not None else {}),
                **({"resolved_from_external": True} if resolved_from_external else {}),
            }
        )

        prev_node_id = node_id if isinstance(node_id, str) else None

    return enriched
