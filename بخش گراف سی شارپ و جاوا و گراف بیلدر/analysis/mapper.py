import json
import networkx as nx
from typing import List, Dict
from utils.normalize import normalize_test_name


def load_test_logs(log_path: str) -> List[Dict]:
    """
    خواندن لاگ تست‌ها از فایل JSON و بازگرداندن لیستی از دیکشنری‌ها.
    پشتیبانی از خطاهای متداول فایل JSON.
    """
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            logs = json.load(f)
            if not isinstance(logs, list):
                raise ValueError("Test log file should contain a list of logs")
            return logs
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"[!] Failed to load test logs: {e}")
        return []


def tag_graph_with_logs(graph: nx.DiGraph, test_logs: List[Dict]) -> nx.DiGraph:
    """
    برچسب‌گذاری گره‌های گراف بر اساس لاگ تست‌ها:
    - تلاش برای تطبیق دقیق نام لاگ با id گره
    - در صورت عدم یافتن تطبیق دقیق، تطبیق انتهای id با نام تابع
    - برچسب test_status: passed, failed, not_executed
    - ذخیره پیام خطا در error_message
    """
    matched = 0
    unmatched = []

    for log in test_logs:
        raw_name = log.get("name", "")
        status = log.get("status", "unknown").lower()
        message = log.get("message") or log.get("traceback") or log.get("error") or ""

        if not raw_name:
            continue

        normalized = normalize_test_name(raw_name)

        # 1. تطبیق دقیق
        matched_node = None
        if normalized in graph.nodes:
            matched_node = normalized
        else:
            # 2. تطبیق انتهای id با نام تابع (after ::)
            func_name = normalized.split("::")[-1]
            for node_id in graph.nodes:
                if node_id.endswith(f"::{func_name}"):
                    matched_node = node_id
                    break

        if matched_node:
            graph.nodes[matched_node]["test_status"] = status
            if message:
                graph.nodes[matched_node]["error_message"] = message
            matched += 1
        else:
            unmatched.append(normalized)

    # برچسب‌گذاری تست‌های بدون لاگ
    for node, data in graph.nodes(data=True):
        if data.get("is_test") and "test_status" not in data:
            graph.nodes[node]["test_status"] = "not_executed"

    # Debugging output
    """ print(f"[tagger] Tagged tests: {matched}")
    if unmatched:
        print(f"[tagger] Unmatched tests ({len(unmatched)}):")
        for name in unmatched:
            print(f"  - {name}")

    total_tests = sum(1 for _, d in graph.nodes(data=True) if d.get("is_test"))
    executed = sum(
        1
        for _, d in graph.nodes(data=True)
        if d.get("test_status") in {"passed", "failed"}
    )
    not_executed = total_tests - executed
    print(f"[tagger] Total test nodes: {total_tests}")
    print(f"[tagger] Executed: {executed} / Not executed: {not_executed}") """

    return graph
