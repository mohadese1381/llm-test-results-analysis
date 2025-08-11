from __future__ import annotations
import json
from pathlib import Path
from typing import Dict, Optional
import pickle
import networkx as nx

from graph.graph_builder import build_graph
from analysis.summarizer import build_test_summary
from analysis.critical_path_extractor import find_critical_paths
from utils.normalize import normalize_test_name


class PromptBuildError(RuntimeError):
    pass


def _read_json(p: Path) -> dict:
    if not p.is_file():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def _load_cached_graph(out_dir: Path) -> Optional[nx.DiGraph]:
    p = out_dir / "cache" / "graph.pkl"
    if not p.is_file():
        return None
    with open(p, "rb") as f:
        return pickle.load(f)


def _ensure_graph(project_path: str, out_dir: Path) -> nx.DiGraph:
    g = _load_cached_graph(out_dir)
    if g is None:
        g = build_graph(project_path)
    return g


def _apply_failed_from_summary(graph: nx.DiGraph, summary: Dict, lang: str) -> None:
    failed = [it.get("name", "") for it in summary.get("failed_detail", []) or []]
    norm = {normalize_test_name(n, lang) for n in failed if n}
    for nid, data in graph.nodes(data=True):
        if data.get("is_test"):
            tail = nid.split("::", 1)[-1]
            if tail in norm or any(tail.endswith(x) for x in norm):
                graph.nodes[nid]["test_status"] = "failed"


def _err_msg(summary: Dict, test_name: str) -> str:
    for f in summary.get("failed_detail", []) or []:
        if f.get("name") == test_name:
            return f.get("error") or ""
    return ""


def build_structured_prompt(
    project_path: str,
    log_path: str,
    lang: str,
    output_path: str = "output/llm_prompt.json",
) -> Dict:
    out_dir = Path(output_path).resolve().parent
    graph = _ensure_graph(project_path, out_dir)

    summary = _read_json(out_dir / "summary.json")
    if not summary:
        summary = build_test_summary(graph)

    _apply_failed_from_summary(graph, summary, lang)
    critical = find_critical_paths(graph)

    payload: Dict = {
        "meta": {
            "project_path": project_path,
            "language": lang,
            "graph": {
                "nodes": graph.number_of_nodes(),
                "edges": graph.number_of_edges(),
            },
        },
        "summary": summary,
        "critical_paths": {},
    }

    for test_name, paths in critical.items():
        payload["critical_paths"][test_name] = {
            "error": _err_msg(summary, test_name),
            "upstream": paths.get("upstream", []),
            "downstream": paths.get("downstream", []),
        }

    out_dir.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return payload
