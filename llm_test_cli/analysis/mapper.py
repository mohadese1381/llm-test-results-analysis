# --- file: analysis/mapper.py ---
import re
import networkx as nx
from typing import List, Dict
from utils.normalize import normalize_test_name
from utils.logs_parser import TestLogParser


def load_test_logs(log_path: str, lang: str) -> List[Dict]:
    """
    بارگذاری لاگ‌های تست برای زبان مشخص (python, java, csharp).
    با پارسر مناسب (json/xml/trx) خروجی استاندارد  {'name','status','message'} برمی‌گرداند.
    """
    try:
        parser = TestLogParser.get_parser(lang, log_path)
        return parser.load(log_path)
    except Exception as e:
        print(f"[!] Failed to parse test logs ({log_path}): {e}")
        return []


def _strip_param_suffix(func_name: str) -> str:
    """
    حذف پسوندهای پارامتری از انتهای نام تابع:
      test_x[zero]           -> test_x
      test_x[param1-param2]  -> test_x
      test_x[0][a]           -> test_x
      test_x(arg1,arg2)      -> test_x   (xUnit/NUnit Theory)
    """
    if not isinstance(func_name, str):
        return func_name
    # حذف همه‌ی پسوندهای پشت‌سرهم [...] یا (...)
    return re.sub(r"(?:\[[^\]]*\]|\([^\)]*\))+$", "", func_name)


def tag_graph_with_logs(
    graph: nx.DiGraph, test_logs: List[Dict], lang: str
) -> nx.DiGraph:
    """
    برچسب‌گذاری گره‌های گراف بر اساس لاگ تست‌ها:
    - تطبیق دقیق نام لاگ با شناسه گره (بعد از normalize)
    - در صورت عدم تطبیق، تطبیق انتهایی با نام تابع/کلاس+تابع
    - تنظیم test_status: passed | failed | skipped | not_executed
    - افزودن error_message برای تست‌های شکست‌خورده
    """
    matched = 0
    unmatched = []

    lang_lc = (lang or "").lower()

    for log in test_logs:
        raw_name = log.get("name", "")
        status = (log.get("status", "unknown") or "unknown").lower()
        message = log.get("message", "") or ""

        if not raw_name:
            continue

        normalized = normalize_test_name(raw_name, lang_lc)

        # نسخه بدون پسوند پارامتری برای «تطبیق»
        parts = normalized.split("::")
        if parts:
            func_original = parts[-1]
            func_stripped = _strip_param_suffix(func_original)
            parts[-1] = func_stripped
            normalized_stripped = "::".join(parts)
        else:
            func_original = normalized
            func_stripped = _strip_param_suffix(func_original)
            normalized_stripped = normalized

        matched_node = None

        # 1) تطبیق دقیق با نام نرمال‌شده
        if normalized in graph.nodes:
            matched_node = normalized

        # 2) تطبیق دقیق با نسخه بدون پسوند پارامتری
        if matched_node is None and normalized_stripped in graph.nodes:
            matched_node = normalized_stripped

        # 3) تطبیق انتهایی با نام تابع (نسخه اصلی)
        if matched_node is None and func_original:
            for node_id in graph.nodes:
                if node_id.endswith(f"::{func_original}"):
                    matched_node = node_id
                    break

        # 4) تطبیق انتهایی با نام تابع (نسخه بدون پسوند پارامتری)
        if matched_node is None and func_stripped:
            for node_id in graph.nodes:
                if node_id.endswith(f"::{func_stripped}"):
                    matched_node = node_id
                    break

        # 5) (NEW) برای #C و Java: سافیکس دقیق '::<Class>::<Method>'
        if matched_node is None and lang_lc in {"csharp", "java"}:
            parts2 = normalized_stripped.split("::")
            if len(parts2) >= 2:
                maybe_method = parts2[-1]
                maybe_class = parts2[-2]
                cand_suffixes = [
                    f"::{maybe_class}::{maybe_method}",  # دقیق‌ترین
                    f"::{maybe_method}",  # fallback
                ]
                for suf in cand_suffixes:
                    for node_id in graph.nodes:
                        if node_id.endswith(suf):
                            matched_node = node_id
                            break
                    if matched_node:
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
        print("   first unmatched:", unmatched[:5])

    return graph
