from __future__ import annotations
from pathlib import Path
from datetime import datetime
import json
from collections import Counter
from typing import Dict, List, Tuple
import re
import hashlib
import pickle

import networkx as nx
from ..graph.utils.locator_ranker import rank_candidates_by_graph


class ReportBuildError(RuntimeError):
    pass


def _read_json(p: Path) -> dict:
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        raise ReportBuildError(f"Invalid JSON: {p} ({e})")


def _extract_first_json_block(text: str) -> dict | None:
    stack, start = 0, -1
    for i, ch in enumerate(text):
        if ch == "{":
            if stack == 0:
                start = i
            stack += 1
        elif ch == "}":
            stack -= 1
            if stack == 0 and start != -1:
                blob = text[start : i + 1]
                try:
                    return json.loads(blob)
                except Exception:
                    return None
    return None


def _load_llm_analysis(out_dir: Path) -> dict:
    p = out_dir / "analysis_report.txt"
    if not p.is_file():
        return {}
    raw = p.read_text(encoding="utf-8")
    try:
        return json.loads(raw)
    except Exception:
        pass
    return _extract_first_json_block(raw) or {}


def _build_tests_overview(summary: dict) -> dict:
    return {
        "passed": int(summary.get("passed_tests", 0) or 0),
        "failed": int(summary.get("failed_tests", 0) or 0),
        "skipped": int(summary.get("skipped_tests", 0) or 0),
    }


def _failure_types_from_summary(summary: dict) -> List[dict]:
    types = [f.get("type") or "Unknown" for f in (summary.get("failed_detail") or [])]
    counts = Counter(types)
    return [{"type": t, "count": c} for t, c in counts.most_common()]


def _norm_failure_type(s: str) -> str:
    if not s:
        return ""
    s = s.strip()
    if "." in s:
        s = s.split(".")[-1]
    aliases = {
        "AssertionFailedError": "AssertionError",
        "ComparisonFailure": "AssertionError",
        "TimeoutException": "Timeout",
        "SocketTimeoutException": "Timeout",
        "RequestTimeout": "Timeout",
        "ConnectException": "Network",
        "ConnectionError": "Network",
        "HTTPError": "Network",
        "ConfigError": "Configuration",
        "ConfigurationError": "Configuration",
    }
    return aliases.get(s, s)


def _failure_types_from_llm(llm: dict) -> List[dict]:
    if not isinstance(llm, dict) or "analysis" not in llm:
        return []
    bucket: Counter[str] = Counter()
    for it in llm.get("analysis") or []:
        ft = _norm_failure_type((it or {}).get("failure_type") or "")
        if not ft:
            err = (it or {}).get("error") or ""
            head = err.split(":", 1)[0].strip() if ":" in err else err.strip()
            ft = _norm_failure_type(head)
        if not ft:
            ft = "Other"
        bucket[ft] += 1
    return [{"type": t, "count": c} for t, c in bucket.most_common()]


_SEV_IMPACT = {"low": 30, "medium": 65, "high": 90}
_SEV_BOOST = {"low": 0.05, "medium": 0.10, "high": 0.20}


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _stable_hash(val: str) -> float:
    h = hashlib.md5(val.encode("utf-8")).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


def _build_risk_bubbles(llm: dict, funcs: dict) -> List[dict]:
    if not isinstance(llm, dict) or not llm.get("analysis"):
        return []

    items: List[dict] = llm["analysis"]
    types: List[str] = []
    for it in items:
        ft = _norm_failure_type((it.get("failure_type") or "").strip())
        if not ft:
            err = (it.get("error") or "").strip()
            head = err.split(":", 1)[0] if ":" in err else err
            ft = _norm_failure_type(head)
        types.append(ft or "Other")
    freq = Counter(types)
    total = max(1, len(items))

    bubbles: List[dict] = []
    for it in items:
        sev = (it.get("severity") or "").strip().lower()
        sev = sev if sev in {"low", "medium", "high"} else "medium"

        ft = _norm_failure_type((it.get("failure_type") or "").strip())
        if not ft:
            err = (it.get("error") or "").strip()
            head = err.split(":", 1)[0] if ":" in err else err
            ft = _norm_failure_type(head)

        sig = f"{it.get('test_name','')}::{ft}"
        stable_factor = _stable_hash(sig) * 0.02
        base = freq.get(ft or "Other", 0) / total
        prob = _clamp(base + _SEV_BOOST[sev] + stable_factor, 0.0, 1.0) * 100.0

        impact = float(_SEV_IMPACT[sev])
        path_len = len(it.get("call_path") or [])
        r = _clamp(8 + 2 * path_len, 8, 22)

        bubbles.append(
            {
                "probability": round(prob, 2),
                "impact": impact,
                "r": r,
                "risk": sev,
                "test_name": it.get("test_name", ""),
            }
        )
    return bubbles


def _build_charts_data(summary: dict, llm: dict, funcs: dict) -> dict:
    ft_llm = _failure_types_from_llm(llm)
    ft_sum = _failure_types_from_summary(summary)
    return {
        "testsOverview": _build_tests_overview(summary),
        "failureTypes": ft_llm or ft_sum,
        "riskBubbles": _build_risk_bubbles(llm, funcs),
    }


def _line_lookup(funcs_json: dict) -> Dict[str, int]:
    lines: Dict[str, int] = {}
    for k, v in (funcs_json or {}).items():
        try:
            lines[k] = int(v.get("line") or 0)
        except Exception:
            pass
    return lines


def _locations_from_locus(locus: dict, lines_map: Dict[str, int]) -> List[str]:
    locs: List[str] = []
    if not isinstance(locus, dict):
        return locs
    for fn in locus.get("functions", []) or []:
        ln = int(lines_map.get(fn, 0) or 0)
        file_part = fn.split("::", 1)[0] if "::" in fn else ""
        if file_part and ln:
            locs.append(f"{file_part}>{ln}")
        elif file_part:
            locs.append(file_part)
    if not locs:
        for f in locus.get("files", []) or []:
            if f:
                locs.append(f.replace("\\", ">").replace("/", ">").replace("::", ">"))
    seen = set()
    uniq: List[str] = []
    for s in locs:
        if s not in seen:
            seen.add(s)
            uniq.append(s)
    return uniq


def _load_cached_graph(out_dir: Path) -> nx.DiGraph | None:
    try:
        pkl = out_dir / "cache" / "graph.pkl"
        if pkl.is_file():
            with open(pkl, "rb") as f:
                return pickle.load(f)
    except Exception:
        pass
    return None


def _match_graph_node(graph: nx.DiGraph | None, test_name: str) -> str | None:
    if not graph or not test_name:
        return None
    if test_name in graph.nodes:
        return test_name
    parts = test_name.split("::")
    method = parts[-1] if parts else test_name
    for node_id in graph.nodes:
        if node_id.endswith(f"::{method}"):
            return node_id
    return None


def _normalize_chain(s: str) -> str:
    if not s:
        return ""
    s = s.replace("\\", ">").replace("/", ">").replace("::", ">")
    s = re.sub(r">(>)+", ">", s)
    s = re.sub(r"^\s*>|>\s*$", "", s)
    return s.strip()


def _clean_test_label(test_name: str) -> str:

    s = (test_name or "").strip()
    if not s:
        return ""
    parts = s.split("::")
    return parts[-1] if parts else s


def _default_bullets_for_item(it: dict, freq: Counter) -> List[str]:

    bullets: List[str] = []
    sev = (it.get("severity") or "medium").strip().lower()
    ft = _norm_failure_type(it.get("failure_type") or "")
    freq_ft = freq.get(ft or "Other", 0)
    if ft in {"AssertionError", "DataMismatch"}:
        bullets.append(
            "ریسک عدم‌انطباق نیازمندی‌ها؛ نیاز به بازبینی قراردادهای تست/بیزینس."
        )
    elif ft in {"AttributeError", "NullPointerException", "Configuration"}:
        bullets.append(
            "ریسک ناپایداری در مرزهای ماژول؛ نیاز به Fail-fast و ولیدیشن ورودی."
        )
    elif ft in {"Timeout", "Network"}:
        bullets.append("ریسک عملکرد/اتصال؛ نیاز به ایزوله‌سازی تست و بودجه‌ زمان.")
    elif ft in {"Mocking"}:
        bullets.append(
            "ریسک پوشش ناکافی تست‌های دابل؛ استانداردسازی الگوهای mock لازم است."
        )
    else:
        bullets.append("ریسک پایداری؛ نیاز به سخت‌گیرانه‌تر شدن تست‌های رگرسیون.")
    if sev == "high":
        bullets.append("اثر مستقیم بر readiness انتشار؛ اولویت رفع بالا.")
    elif sev == "medium":
        bullets.append("اثر قابل‌توجه بر Lead Time؛ برنامه‌ریزی رفع در اسپرینت جاری.")
    else:
        bullets.append("اثر محدود؛ می‌توان به‌صورت فرصت بهبود پیگیری کرد.")
    if freq_ft >= 2:
        bullets.append(
            "الگوی تکرارشونده؛ احتمالاً نیاز به اقدام سیستمی/ری‌فکتور در ناحیه مرتبط."
        )
    return bullets


def _insights_and_risks_from_llm(
    llm: dict, failed_count: int
) -> Tuple[List[dict], List[dict]]:

    insights: List[dict] = []
    risks: List[dict] = []

    if isinstance(llm, dict) and llm.get("analysis"):
        items: List[dict] = llm["analysis"]
        types = [_norm_failure_type((it.get("failure_type") or "")) for it in items]
        freq = Counter(types)

        for it in items:
            title = _clean_test_label(it.get("test_name") or "")
            bullets = it.get("insight_bullets") or []
            bullets = [str(b).strip() for b in bullets if str(b).strip()]
            if not bullets:
                bullets = _default_bullets_for_item(it, freq)
            insights.append({"title": title, "detail": bullets})
        return insights, risks

    if failed_count > 0:
        return (
            [
                {
                    "title": "Failures detected",
                    "detail": [f"{failed_count} failing test(s)."],
                }
            ],
            risks,
        )
    return ([{"title": "All clear", "detail": ["No failures in this run."]}], risks)


def _failures_table(summary: dict, llm: dict, funcs: dict) -> List[dict]:
    rows: List[dict] = []
    lines_map = _line_lookup(funcs)
    cached_graph: nx.DiGraph | None = globals().get("_CACHED_GRAPH_FOR_FAIL_TABLE")

    if isinstance(llm, dict) and llm.get("analysis"):
        for it in llm["analysis"]:
            test_name = it.get("test_name") or ""
            locus = it.get("locus") or {}

            llm_suspects = []
            sus = locus.get("suspects") or []
            if isinstance(sus, list):
                llm_suspects.extend([_normalize_chain(x or "") for x in sus if x])

            llm_locations_from_locus = _locations_from_locus(locus, lines_map)
            loc_llm: List[str] = []
            for x in llm_suspects + llm_locations_from_locus:
                x = _normalize_chain(x)
                if x and x not in loc_llm:
                    loc_llm.append(x)

            loc_h: List[str] = [
                _normalize_chain(x) for x in (it.get("heuristic_locations") or []) if x
            ]
            if not loc_h:
                loc_h = llm_locations_from_locus[:]

            loc_g: List[str] = []
            if cached_graph is not None:
                node_id = _match_graph_node(cached_graph, test_name)
                if node_id:
                    if not loc_h:
                        from_node = list(
                            cached_graph.nodes[node_id].get("heuristic_locations") or []
                        )
                        loc_h = [_normalize_chain(x) for x in from_node if x]
                    if loc_h:
                        loc_g = rank_candidates_by_graph(cached_graph, node_id, loc_h)

            legacy_location = ", ".join(loc_g or loc_h or loc_llm)

            rows.append(
                {
                    "id": test_name,
                    "title": test_name,
                    "type": "unit",
                    "message": it.get("error") or "",
                    "root_cause": it.get("root_cause") or "",
                    "severity": it.get("severity") or "",
                    "file": ", ".join(locus.get("files", []) or []),
                    "location": legacy_location,
                    "location_layers": {
                        "heuristic": loc_h,
                        "graph_ranked": loc_g or loc_h,
                        "llm": loc_llm,
                    },
                    "functions": locus.get("functions", []) or [],
                    "suggested_fixes": it.get("suggested_fixes") or [],
                }
            )
        return rows

    for f in summary.get("failed_detail", []) or []:
        rows.append(
            {
                "id": f.get("id") or f.get("name") or "",
                "title": f.get("name") or "",
                "type": f.get("type") or "unit",
                "message": f.get("error") or "",
                "file": f.get("file") or "",
                "location": f.get("file") or "",
                "location_layers": {"heuristic": [], "graph_ranked": [], "llm": []},
                "root_cause": "",
                "severity": "",
                "functions": [],
                "suggested_fixes": [],
            }
        )
    return rows


def _build_report_json(project_path: Path, out_dir: Path) -> dict:
    summary = _read_json(out_dir / "summary.json")
    prompt = _read_json(out_dir / "llm_prompt.json")
    funcs = _read_json(out_dir / "function_summaries.json")
    llm = _load_llm_analysis(out_dir)

    meta = prompt.get("meta") or {}
    proj_name = (Path(meta.get("project_path") or project_path).resolve()).name

    metrics = {
        "total": int(summary.get("total_tests", 0) or 0),
        "passed": int(summary.get("passed_tests", 0) or 0),
        "failed": int(summary.get("failed_tests", 0) or 0),
        "skipped": int(summary.get("skipped_tests", 0) or 0),
        "durationSec": float(summary.get("duration_sec", 0) or 0),
    }

    global _CACHED_GRAPH_FOR_FAIL_TABLE
    try:
        _CACHED_GRAPH_FOR_FAIL_TABLE = _load_cached_graph(out_dir)
    except Exception:
        _CACHED_GRAPH_FOR_FAIL_TABLE = None

    failures = _failures_table(summary, llm, funcs)
    insights, risks = _insights_and_risks_from_llm(llm, metrics["failed"])
    charts = _build_charts_data(summary, llm, funcs)

    return {
        "schemaVersion": "1.0.0",
        "project": {"name": proj_name, "date": datetime.now().date().isoformat()},
        "metrics": metrics,
        "insights": insights,
        "risks": risks,
        "failures": failures,
        "charts": charts,
    }


def render_report_html(project_path: str, out_dir: str, template_path: str) -> str:
    proj = Path(project_path).resolve()
    out = Path(out_dir).resolve()
    tpl = Path(template_path).resolve()
    if not tpl.is_file():
        raise ReportBuildError(f"Template not found: {tpl}")

    report_json = _build_report_json(proj, out)
    html_tpl = tpl.read_text(encoding="utf-8")
    json_safe = json.dumps(report_json, ensure_ascii=False).replace("<", "\\u003c")
    html = html_tpl.replace(
        "const REPORT = __REPORT_JSON__", f"const REPORT = {json_safe}"
    )
    final_path = tpl.parent / "final_report.html"
    final_path.write_text(html, encoding="utf-8")
    return str(final_path)
