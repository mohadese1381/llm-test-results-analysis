import re
import networkx as nx
from typing import List, Dict
from ..utils.normalize import normalize_test_name
from ..utils.logs_parser import TestLogParser
from .locator import locate_from_error

ANSI_PATTERN = re.compile(r"(?:\x1B|\#x1B)\[[0-9;]*[A-Za-z]")


def _strip_ansi(text: str) -> str:
    if not isinstance(text, str):
        return text
    return ANSI_PATTERN.sub("", text)


def load_test_logs(log_path: str, lang: str) -> List[Dict]:

    try:
        parser = TestLogParser.get_parser(lang, log_path)
        logs = parser.load(log_path)
        for log in logs:
            if "message" in log and log["message"]:
                log["message"] = _strip_ansi(log["message"])
        return logs
    except Exception as e:
        print(f"[!] Failed to parse test logs ({log_path}): {e}")
        return []


def _strip_param_suffix(func_name: str) -> str:
    if not isinstance(func_name, str):
        return func_name
    return re.sub(r"(?:\[[^\]]*\]|\([^\)]*\))+$", "", func_name)


def tag_graph_with_logs(
    graph: nx.DiGraph, test_logs: List[Dict], lang: str
) -> nx.DiGraph:
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

        if normalized in graph.nodes:
            matched_node = normalized
        if matched_node is None and normalized_stripped in graph.nodes:
            matched_node = normalized_stripped
        if matched_node is None and func_original:
            for node_id in graph.nodes:
                if node_id.endswith(f"::{func_original}"):
                    matched_node = node_id
                    break
        if matched_node is None and func_stripped:
            for node_id in graph.nodes:
                if node_id.endswith(f"::{func_stripped}"):
                    matched_node = node_id
                    break
        if matched_node is None and lang_lc in {"csharp", "java"}:
            parts2 = normalized_stripped.split("::")
            if len(parts2) >= 2:
                maybe_method = parts2[-1]
                maybe_class = parts2[-2]
                cand_suffixes = [
                    f"::{maybe_class}::{maybe_method}",
                    f"::{maybe_method}",
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
                clean_msg = _strip_ansi(message)
                graph.nodes[matched_node]["error_message"] = clean_msg

                heur = locate_from_error(clean_msg, lang_lc)
                graph.nodes[matched_node]["heuristic_locations"] = heur.get(
                    "heuristic", []
                )
                graph.nodes[matched_node]["raw_locations"] = heur.get("raw_paths", [])

            matched += 1
        else:
            unmatched.append(raw_name)

    for node, data in graph.nodes(data=True):
        if data.get("is_test") and "test_status" not in data:
            graph.nodes[node]["test_status"] = "not_executed"

    return graph
