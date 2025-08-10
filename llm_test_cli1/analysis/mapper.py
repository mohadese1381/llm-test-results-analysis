import networkx as nx
from typing import List, Dict
from utils.normalize import normalize_test_name
from utils.logs_parser import TestLogParser


def load_test_logs(log_path: str, lang: str) -> List[Dict]:
    """
    بارگذاری لاگ‌های تست برای زبان مشخص (python, java, csharp).
    از روی پسوند (json, xml, trx) پارسر مناسب انتخاب و خروجی
    لیستی از {'name', 'status', 'message'} تولید می‌شود.
    """
    try:
        parser = TestLogParser.get_parser(lang, log_path)
        return parser.load(log_path)
    except Exception as e:
        print(f"[!] Failed to parse test logs ({log_path}): {e}")
        return []


def tag_graph_with_logs(
    graph: nx.DiGraph, test_logs: List[Dict], lang: str
) -> nx.DiGraph:
    """
    برچسب‌گذاری گره‌های گراف بر اساس لاگ تست‌ها:
    - تطبیق دقیق نام لاگ با شناسه گره
    - در صورت عدم تطبیق دقیق، تطبیق انتهای شناسه با نام تابع
    - تنظیم test_status: passed | failed | skipped | not_executed
    - افزودن error_message برای تست‌های شکست‌خورده
    """
    matched = 0
    unmatched = []

    for log in test_logs:
        raw_name = log.get("name", "")
        status = log.get("status", "unknown").lower()
        message = log.get("message", "")

        if not raw_name:
            continue

        normalized = normalize_test_name(raw_name, lang)

        # 1) تطبیق دقیق
        matched_node = normalized if normalized in graph.nodes else None

        # 2) تطبیق انتهای شناسه (method name)
        if matched_node is None:
            func = normalized.split("::")[-1]
            for node_id in graph.nodes:
                if node_id.endswith(f"::{func}"):
                    matched_node = node_id
                    break

        if matched_node:
            graph.nodes[matched_node]["test_status"] = status
            if message:
                graph.nodes[matched_node]["error_message"] = message
            matched += 1
        else:
            unmatched.append(raw_name)

    # برچسب‌گذاری تست‌های بدون لاگ
    for node, data in graph.nodes(data=True):
        if data.get("is_test") and "test_status" not in data:
            graph.nodes[node]["test_status"] = "not_executed"
    print(f"⟹ TAGGER: matched={matched}, unmatched={len(unmatched)}")
    if unmatched:
         print('   first unmatched:', unmatched[:5])
    return graph
