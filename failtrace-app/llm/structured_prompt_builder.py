import json
import os
from typing import Dict

from graph.graph_builder import build_graph
from utils.file_ops import load_json
from analysis.mapper import load_test_logs, tag_graph_with_logs
from analysis.summarizer import build_test_summary
from analysis.critical_path_extractor import find_critical_paths


def get_error_message(summary: Dict, test_name: str) -> str:
    """
    جستجو در لیست تست‌های شکست‌خورده برای یافتن پیام خطا
    """
    for failed in summary.get("failed_detail", []):
        if failed["name"] == test_name:
            return failed.get("error", "")
    return ""


def build_structured_prompt(
    project_path: str, log_path: str, output_path: str = "output/llm_prompt.json"
) -> Dict:
    """
    ساخت یک prompt ساختاریافته شامل:
    - اطلاعات پروژه
    - خلاصه تست‌ها
    - مسیرهای بحرانی تست‌های شکست‌خورده
    """

    # 1. ساخت گراف پروژه و تگ‌گذاری آن با لاگ‌ها
    graph = build_graph(project_path)
    logs = load_test_logs(log_path)
    graph = tag_graph_with_logs(graph, logs)

    # 2. خلاصه تست‌ها و مسیرهای بحرانی
    summary = build_test_summary(graph)
    critical_paths = find_critical_paths(graph)

    # 3. ساخت ساختار نهایی prompt
    structured_prompt: Dict = {
        "meta": {
            "project_path": project_path,
            "log_path": log_path,
            "graph": {
                "nodes": graph.number_of_nodes(),
                "edges": graph.number_of_edges(),
            },
        },
        "summary": summary,
        "critical_paths": {},
    }

    # 4. افزودن مسیرهای بحرانی (enriched paths مستقیماً استفاده می‌شوند)
    for test_name, paths in critical_paths.items():
        summarized_upstream = paths.get("upstream", [])
        summarized_downstream = paths.get("downstream", [])

        structured_prompt["critical_paths"][test_name] = {
            "error": get_error_message(summary, test_name),
            "upstream": summarized_upstream,
            "downstream": summarized_downstream,
        }

    # 5. ذخیره فایل نهایی
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(structured_prompt, f, indent=2, ensure_ascii=False)
     # Debugging output
    """ print(f"[✓] LLM structured prompt saved to: {output_path}") """
    return structured_prompt
