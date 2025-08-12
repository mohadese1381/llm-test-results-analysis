from __future__ import annotations
from pathlib import Path
from datetime import datetime
import json
from collections import Counter
from typing import Dict, List, Tuple
import re


class ReportBuildError(RuntimeError):
    pass


# ---------- IO & parsing ----------


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


# ---------- Charts / metrics ----------


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


# --- normalize failure type for grouping
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


# ---- RISK BUBBLES ----
_SEV_IMPACT = {"low": 30, "medium": 65, "high": 90}  # Y axis
_SEV_BOOST = {"low": 0.05, "medium": 0.10, "high": 0.20}  # added to base prob


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _build_risk_bubbles(llm: dict, funcs: dict) -> List[dict]:
    """
    For each failed test in LLM analysis produce:
      - probability (%): base frequency of its failure_type + severity boost
      - impact (%): mapped from severity (low=30, medium=65, high=90)
      - r: bubble radius (UI only) = clamp(8 + 2*len(call_path), 8, 22)
      - risk: severity (low/medium/high)
    Tooltip in UI shows only probability/impact/risk.
    """
    if not isinstance(llm, dict) or not llm.get("analysis"):
        return []

    items: List[dict] = llm["analysis"]
    # frequency by normalized failure type
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

        # base probability from type frequency
        ft = _norm_failure_type((it.get("failure_type") or "").strip())
        if not ft:
            err = (it.get("error") or "").strip()
            head = err.split(":", 1)[0] if ":" in err else err
            ft = _norm_failure_type(head)
        base = freq.get(ft or "Other", 0) / total
        prob = _clamp(base + _SEV_BOOST[sev], 0.0, 1.0) * 100.0

        impact = float(_SEV_IMPACT[sev])

        path_len = len(it.get("call_path") or [])
        r = _clamp(8 + 2 * path_len, 8, 22)

        bubbles.append(
            {"probability": round(prob, 2), "impact": impact, "r": r, "risk": sev}
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


# ---------- Locations (file:line) ----------


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
            locs.append(f"{file_part}:{ln}")
        elif file_part:
            locs.append(file_part)
    if not locs:
        for f in locus.get("files", []) or []:
            if f:
                locs.append(f)
    seen = set()
    uniq: List[str] = []
    for s in locs:
        if s not in seen:
            seen.add(s)
            uniq.append(s)
    return uniq


# ---------- Insights / Failures ----------


def _normalize_cause(txt: str) -> str:
    if not txt:
        return ""
    s = txt.strip().lower()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[\.!]+$", "", s)
    return s


def _insights_and_risks_from_llm(
    llm: dict, failed_count: int
) -> Tuple[List[dict], List[dict]]:
    insights: List[dict] = []
    risks: List[dict] = []  # kept for backward compatibility (unused in UI)

    if isinstance(llm, dict) and llm.get("analysis"):
        items: List[dict] = llm["analysis"]
        groups: dict[str, dict] = {}
        for it in items:
            rc_raw = (it.get("root_cause") or "").strip()
            key = _normalize_cause(rc_raw) or _normalize_cause(
                (it.get("error") or "").split(":", 1)[0]
            )
            if key not in groups:
                groups[key] = {
                    "title": rc_raw or (it.get("error") or "Unspecified cause"),
                    "tests": [],
                    "files": Counter(),
                    "funcs": Counter(),
                }
            g = groups[key]
            tn = (it.get("test_name") or "").strip()
            if tn:
                g["tests"].append(tn)
        ordered = sorted(groups.values(), key=lambda g: len(g["tests"]), reverse=True)
        for g in ordered:
            insights.append(
                {"title": g["title"], "detail": f"{len(g['tests'])} failing test(s)"}
            )
        return insights, risks

    if failed_count > 0:
        insights.append(
            {"title": "Failures detected", "detail": f"{failed_count} failing test(s)."}
        )
    else:
        insights.append({"title": "All clear", "detail": "No failures in this run."})
    return insights, risks


def _failures_table(summary: dict, llm: dict, funcs: dict) -> List[dict]:
    rows: List[dict] = []
    lines_map = _line_lookup(funcs)
    if isinstance(llm, dict) and llm.get("analysis"):
        for it in llm["analysis"]:
            locus = it.get("locus") or {}
            files = locus.get("files", []) or []
            functions = locus.get("functions", []) or []
            locations = _locations_from_locus(locus, lines_map)
            rows.append(
                {
                    "id": it.get("test_name") or "",
                    "title": it.get("test_name") or "",
                    "type": "unit",
                    "message": it.get("error") or "",
                    "root_cause": it.get("root_cause") or "",
                    "severity": it.get("severity") or "",
                    "file": ", ".join(files) if files else "",
                    "location": ", ".join(locations) if locations else "",
                    "functions": functions,
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
                "root_cause": "",
                "severity": "",
                "functions": [],
                "suggested_fixes": [],
            }
        )
    return rows


# ---------- Report assembly ----------


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

    failures = _failures_table(summary, llm, funcs)
    insights, risks = _insights_and_risks_from_llm(llm, metrics["failed"])
    charts = _build_charts_data(summary, llm, funcs)

    return {
        "schemaVersion": "1.0.0",
        "project": {"name": proj_name, "date": datetime.now().date().isoformat()},
        "metrics": metrics,
        "insights": insights,
        "risks": risks,  # kept for backward compat (UI ignores)
        "failures": failures,
        "charts": charts,
    }


# ---------- HTML rendering ----------


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
