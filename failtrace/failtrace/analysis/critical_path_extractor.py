import networkx as nx
from typing import Dict, List, Any, Tuple, Iterable
from ..graph.graph_utils.path_enricher import enrich_path_with_metadata

_EXCLUDED_SUBSTRS = (
    "/.venv/",
    "/venv/",
    "/env/",
    "/.tox/",
    "/site-packages/",
    "/dist-packages/",
    "/.pytest_cache/",
    "/__pycache__/",
)

_DEFAULT_MAX_PATHS_PER_DIR = 5
_DEFAULT_CUTOFF = 6


def _keep_step(step: Dict[str, Any]) -> bool:
    """
    آیا این گام نگه داشته شود؟
    - نودهای external حذف نمی‌شوند (برای تحلیل LLM لازم‌اند).
    - هر گرهی که file آن داخل مسیرهای محیط/غیرسورس باشد حذف می‌شود.
    """
    if not isinstance(step, dict):
        return False

    f = (step.get("file") or "").replace("\\", "/").lower()
    if not f:
        return True

    path = f if f.startswith("/") else f"/{f}"
    for bad in _EXCLUDED_SUBSTRS:
        if bad in path:
            return False

    return True


def _unique(seq: Iterable[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for x in seq:
        if x not in seen:
            out.append(x)
            seen.add(x)
    return out


def _attach_origin_for_external_step(graph: nx.DiGraph, step: Dict[str, Any]) -> None:
    """
    برای نود external یک «origin» اضافه می‌کند:
      - callers: فهرست فایل‌هایی که این نماد از آن‌ها فراخوانی شده (سرنخ import/alias).
      - اگر caller فایلی نداشته باشد، حذف می‌شود.
    """
    if step.get("type") != "external":
        return

    node_id = step.get("node")
    if not node_id or node_id not in graph:
        return

    callers_files: List[str] = []
    for u in graph.predecessors(node_id):
        f = (graph.nodes.get(u, {}) or {}).get("file")
        if f:
            callers_files.append(str(f).replace("\\", "/"))

    if not callers_files:
        for v in graph.successors(node_id):
            f = (graph.nodes.get(v, {}) or {}).get("file")
            if f:
                callers_files.append(str(f).replace("\\", "/"))

    callers_files = _unique(callers_files)
    if callers_files:
        step["origin"] = {"callers": callers_files[:5]}
    else:
        step["origin"] = {"callers": []}


def _augment_externals_with_origin(
    graph: nx.DiGraph, path: List[Dict[str, Any]]
) -> None:
    for step in path:
        if (
            isinstance(step, dict)
            and step.get("type") == "external"
            and "origin" not in step
        ):
            _attach_origin_for_external_step(graph, step)


def _path_signature(path: List[Dict[str, Any]]) -> Tuple[str, ...]:
    """امضای یکتا برای مسیر بر مبنای توالی node-id ها."""
    return tuple(
        step["node"] for step in path if isinstance(step, dict) and "node" in step
    )


def _informativeness_score(path: List[Dict[str, Any]]) -> Tuple[int, int]:
    """
    نمره‌ی مفید بودن مسیر:
    - تعداد گره‌های غیرتستی (بیشتر بهتر)
    - طول مسیر (بیشتر بهتر)
    """
    non_test = sum(1 for s in path if not s.get("is_test", False))
    return (non_test, len(path))


def _postprocess_paths(
    paths: List[List[Dict[str, Any]]],
    *,
    drop_short_downstream: bool,
    max_paths: int,
) -> List[List[Dict[str, Any]]]:
    """
    Dedup + Filter + Sort + Cap
    drop_short_downstream: اگر True باشد، مسیرهای با طول < 2 حذف می‌شوند.
    """
    uniq: Dict[Tuple[str, ...], List[Dict[str, Any]]] = {}

    for p in paths:
        if drop_short_downstream and len(p) < 2:
            continue
        sig = _path_signature(p)
        if not sig:
            continue
        old = uniq.get(sig)
        if old is None or _informativeness_score(p) > _informativeness_score(old):
            uniq[sig] = p

    sorted_paths = sorted(uniq.values(), key=_informativeness_score, reverse=True)
    return sorted_paths[:max_paths]


def find_critical_paths(
    graph: nx.DiGraph,
    *,
    cutoff: int = _DEFAULT_CUTOFF,
    max_paths_per_direction: int = _DEFAULT_MAX_PATHS_PER_DIR,
) -> Dict[str, Dict[str, List[List[Dict[str, Any]]]]]:
    """
    مسیرهای بحرانی برای تست‌های شکست‌خورده را استخراج می‌کند (upstream/downstream)
    و خروجی enriched برمی‌گرداند. این نسخه:
      - external ها را نگه می‌دارد و «origin» برایشان اضافه می‌کند.
      - مسیرهای تکراری را حذف و بهترین‌ها را نگه می‌دارد.
      - cutoff و سقف مسیرها قابل‌پیکربندی‌اند.
    """
    critical_paths: Dict[str, Dict[str, List[List[Dict[str, Any]]]]] = {}

    failed_tests = [
        node
        for node, data in graph.nodes(data=True)
        if data.get("is_test") and data.get("test_status") == "failed"
    ]

    if not failed_tests:
        return {}

    for failed_node in failed_tests:
        upstream_raw: List[List[Dict[str, Any]]] = []
        downstream_raw: List[List[Dict[str, Any]]] = []

        for node in graph.nodes:
            if node == failed_node:
                continue

            try:
                for path in nx.all_simple_paths(
                    graph, source=node, target=failed_node, cutoff=cutoff
                ):
                    enriched = enrich_path_with_metadata(graph, path)
                    _augment_externals_with_origin(graph, enriched)
                    filtered = [step for step in enriched if _keep_step(step)]
                    if filtered:
                        upstream_raw.append(filtered)
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                pass

            try:
                for path in nx.all_simple_paths(
                    graph, source=failed_node, target=node, cutoff=cutoff
                ):
                    enriched = enrich_path_with_metadata(graph, path)
                    _augment_externals_with_origin(graph, enriched)
                    filtered = [step for step in enriched if _keep_step(step)]
                    if filtered:
                        downstream_raw.append(filtered)
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                pass

        upstream = _postprocess_paths(
            upstream_raw, drop_short_downstream=False, max_paths=max_paths_per_direction
        )
        downstream = _postprocess_paths(
            downstream_raw,
            drop_short_downstream=True,
            max_paths=max_paths_per_direction,
        )

        critical_paths[failed_node] = {"upstream": upstream, "downstream": downstream}

    return critical_paths
