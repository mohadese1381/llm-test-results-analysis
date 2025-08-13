import networkx as nx
from typing import Dict, Any, List


def build_test_summary(graph: nx.DiGraph) -> Dict[str, Any]:
    """
    ساخت خلاصه‌ای از وضعیت تست‌ها و گره‌های شکست‌خورده
    """
    summary = {
        "total_tests": 0,
        "executed_tests": 0,
        "passed_tests": 0,
        "failed_tests": 0,
        "skipped_tests": 0,
        "untagged_tests": 0,
        "failed_detail": [],
    }

    for node, data in graph.nodes(data=True):
        if not data.get("is_test"):
            continue

        summary["total_tests"] += 1
        status = data.get("test_status", "").lower()

        if status == "passed":
            summary["executed_tests"] += 1
            summary["passed_tests"] += 1
        elif status == "failed":
            summary["executed_tests"] += 1
            summary["failed_tests"] += 1
            summary["failed_detail"].append(
                {
                    "name": node,
                    "file": data.get("file"),
                    "line": data.get("line"),
                    "error": data.get("error_message", ""),
                    "doc": data.get("docstring", ""),
                }
            )
        elif status == "skipped":
            summary["executed_tests"] += 1
            summary["skipped_tests"] += 1
        else:
            summary["untagged_tests"] += 1

    return summary
