import networkx as nx
from typing import Dict, List, Any
from graph.graph_utils.path_enricher import enrich_path_with_metadata

# ✅ پوشه‌های غیرسورس که باید از مسیرهای بحرانی حذف شوند (حساس به حروف نیست)
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


def _keep_step(step: Dict[str, Any]) -> bool:
    """
    تصمیم می‌گیرد آیا یک گام از مسیر بحرانی نگه داشته شود یا نه.
    - گره‌های external حذف می‌شوند.
    - هر گرهی که file آن داخل مسیرهای محیط/غیرسورس باشد حذف می‌شود.
    """
    if not isinstance(step, dict):
        return False

    # حذف گره‌های خارجی
    if step.get("type") == "external":
        return False

    f = (step.get("file") or "").replace("\\", "/").lower()
    if not f:
        # اگر فایلی گزارش نشده، اجازه بده بماند (ممکن است رفرنسی بدون فایل باشد)
        return True

    # اگر هر کدام از زیررشته‌های ممنوعه در مسیر باشد، حذفش کن
    # هم شروع مسیر و هم وجود در میانه بررسی می‌شود
    path = f if f.startswith("/") else f"/{f}"
    for bad in _EXCLUDED_SUBSTRS:
        if bad in path:
            return False

    return True


def find_critical_paths(
    graph: nx.DiGraph,
) -> Dict[str, Dict[str, List[List[Dict[str, Any]]]]]:
    """
    مسیرهای بحرانی برای تست‌های شکست‌خورده را استخراج می‌کند (upstream/downstream)
    و خروجی enriched برمی‌گرداند.
    مسیرها بعد از غنی‌سازی، از نظر گره‌های external و مسیرهای محیط مجازی/غیرسورس
    فیلتر می‌شوند تا در مرحله‌ی استخراج فانکشن‌های بحرانی وارد نشوند.
    """
    critical_paths: Dict[str, Dict[str, List[List[Dict[str, Any]]]]] = {}

    failed_tests = [
        node
        for node, data in graph.nodes(data=True)
        if data.get("is_test") and data.get("test_status") == "failed"
    ]

    if not failed_tests:
        # Debugging output
        # print("[critical] No failed tests found.")
        return {}

    for failed_node in failed_tests:
        upstream: List[List[Dict[str, Any]]] = []
        downstream: List[List[Dict[str, Any]]] = []

        for node in graph.nodes:
            if node == failed_node:
                continue

            # ↑ Upstream: node → failed_node
            try:
                paths = nx.all_simple_paths(
                    graph, source=node, target=failed_node, cutoff=6
                )
                for path in paths:
                    enriched_path = enrich_path_with_metadata(graph, path)
                    # ✅ فیلتر گام‌های ناخواسته
                    filtered = [step for step in enriched_path if _keep_step(step)]
                    if filtered:
                        upstream.append(filtered)
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                pass

            # ↓ Downstream: failed_node → node
            try:
                paths = nx.all_simple_paths(
                    graph, source=failed_node, target=node, cutoff=6
                )
                for path in paths:
                    enriched_path = enrich_path_with_metadata(graph, path)
                    # ✅ فیلتر گام‌های ناخواسته
                    filtered = [step for step in enriched_path if _keep_step(step)]
                    if filtered:
                        downstream.append(filtered)
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                pass

        critical_paths[failed_node] = {"upstream": upstream, "downstream": downstream}

    return critical_paths
