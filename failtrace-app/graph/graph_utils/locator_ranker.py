from __future__ import annotations

import math
import re
from typing import List
import networkx as nx


def _extract_file_from_candidate(candidate: str) -> str:
    """
    از رشته‌ای مانند 'src/main/java/Foo.java>42' یا 'C:>path>Bar.cs>15'
    فقط بخش مسیر فایل را جدا می‌کند (بدون شماره خط).
    """
    if not candidate:
        return ""
    # حذف شماره خط انتهایی (">NNN")
    parts = candidate.split(">")
    if parts and parts[-1].isdigit():
        parts = parts[:-1]
    return ">".join(parts)


def rank_candidates_by_graph(
    graph: nx.DiGraph,
    failed_node_id: str,
    candidates: List[str],
) -> List[str]:
    """
    رتبه‌بندی candidates بر اساس فاصله آن‌ها در گراف از نود تست شکست‌خورده.

    ورودی‌ها:
        graph           : گراف جهت‌دار nx.DiGraph (ساختار موجود پروژه)
        failed_node_id  : شناسه‌ی گره تست شکست‌خورده
        candidates      : لیستی از رشته‌های 'file>line' از Heuristic Locator

    خروجی:
        همان candidates به ترتیب صعودی فاصله (پایدار، deterministic)
    """
    if not graph or not failed_node_id or not candidates:
        return candidates

    if failed_node_id not in graph.nodes:
        return candidates

    try:
        dist_from_failed = nx.single_source_shortest_path_length(graph, failed_node_id)
    except Exception:
        dist_from_failed = {}

    try:
        dist_to_failed = nx.single_source_shortest_path_length(
            graph.reverse(), failed_node_id
        )
    except Exception:
        dist_to_failed = {}

    ranked: List[tuple[float, int, str]] = []

    for idx, cand in enumerate(candidates):
        file_key = _extract_file_from_candidate(cand)

        matched_nodes = [
            node_id for node_id in graph.nodes if file_key and file_key in node_id
        ]

        best_distance = math.inf

        for node_id in matched_nodes:
            d1 = dist_from_failed.get(node_id, math.inf)
            d2 = dist_to_failed.get(node_id, math.inf)
            best_distance = min(best_distance, d1, d2)

        ranked.append((best_distance, idx, cand))

    ranked.sort(key=lambda x: (x[0], x[1]))

    return [cand for _, _, cand in ranked]
