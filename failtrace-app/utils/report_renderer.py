# utils/report_renderer.py
from __future__ import annotations
from pathlib import Path
from datetime import datetime
import json
from collections import Counter
from typing import Dict, List, Tuple


class ReportBuildError(RuntimeError):
    pass


# ------------------------- IO & Parsing -------------------------


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


# ------------------------- Aggregations (charts/metrics) -------------------------


def _build_tests_overview(summary: dict) -> dict:
    return {
        "passed": summary.get("passed_tests", 0),
        "failed": summary.get("failed_tests", 0),
        "skipped": summary.get("skipped_tests", 0),
        "flaky": summary.get("flaky_tests", 0),
    }


def _failure_types_from_summary(summary: dict) -> List[dict]:
    types = [f.get("type") or "Unknown" for f in summary.get("failed_detail", []) or []]
    counts = Counter(types)
    return [
        {"type": t, "count": c}
        for t, c in sorted(counts.items(), key=lambda x: x[1], reverse=True)
    ]


def _failure_types_from_llm(llm: dict) -> List[dict]:
    if not isinstance(llm, dict) or "analysis" not in llm:
        return []
    types: List[str] = []
    for it in llm.get("analysis", []) or []:
        err = (it or {}).get("error") or ""
        t = err.split(":")[0].strip() if ":" in err else err.strip()
        if t:
            types.append(t)
    counts = Counter(types)
    return [
        {"type": t, "count": c}
        for t, c in sorted(counts.items(), key=lambda x: x[1], reverse=True)
    ]


def _coverage_bars(summary: dict) -> dict:
    return {
        "lines": float(summary.get("coverage_lines", 0) or 0),
        "branches": float(summary.get("coverage_branches", 0) or 0),
    }


def _hotspots_from_llm(llm: dict) -> dict:
    files = Counter()
    funcs = Counter()
    if isinstance(llm, dict):
        for it in llm.get("analysis", []) or []:
            loc = (it or {}).get("locus") or {}
            for f in loc.get("files", []) or []:
                if f:
                    files[f] += 1
            for fn in loc.get("functions", []) or []:
                if fn:
                    funcs[fn] += 1
    top_files = [{"id": k, "count": v} for k, v in files.most_common(10)]
    top_funcs = [{"id": k, "count": v} for k, v in funcs.most_common(10)]
    return {"files": top_files, "functions": top_funcs}


def _build_charts_data(summary: dict, llm: dict) -> dict:
    ft_llm = _failure_types_from_llm(llm)
    ft_sum = _failure_types_from_summary(summary)
    failure_types = ft_llm or ft_sum
    return {
        "testsOverview": _build_tests_overview(summary),
        "failureTypes": failure_types,
        "coverageBars": _coverage_bars(summary),
    }


# ------------------------- Mapping (locations) -------------------------


def _line_lookup(funcs_json: dict) -> Dict[str, int]:
    """
    Build a lookup: "<relpath>::<Class>::<func>" -> line
    (function_summaries.json ساختار)
    """
    lines: Dict[str, int] = {}
    for k, v in (funcs_json or {}).items():
        try:
            lines[k] = int(v.get("line") or 0)
        except Exception:
            pass
    return lines


def _locations_from_locus(locus: dict, lines_map: Dict[str, int]) -> List[str]:
    """
    Resolve precise locations in "file:line" form.
    Priority:
      1) locus.functions → file::Class::func → (file, line) via function_summaries
      2) fallback to locus.files
    """
    locs: List[str] = []
    if not isinstance(locus, dict):
        return locs

    # Prefer function-level precision
    for fn in locus.get("functions", []) or []:
        ln = lines_map.get(fn, 0)
        file_part = fn.split("::", 1)[0] if "::" in fn else ""
        if file_part and ln:
            locs.append(f"{file_part}:{ln}")
        elif file_part:
            locs.append(file_part)

    # Fallback to files
    if not locs:
        for f in locus.get("files", []) or []:
            if f:
                locs.append(f)

    # Deduplicate preserving order
    seen = set()
    uniq: List[str] = []
    for s in locs:
        if s not in seen:
            seen.add(s)
            uniq.append(s)
    return uniq


# ------------------------- Insights, Risks, Failures table -------------------------


def _insights_and_risks_from_llm(
    llm: dict, failed_count: int
) -> Tuple[List[dict], List[dict], str]:
    insights: List[dict] = []
    risks: List[dict] = []
    rationales: List[str] = []

    if isinstance(llm, dict) and "analysis" in llm:
        for item in llm["analysis"]:
            tn = item.get("test_name", "")
            rc = item.get("root_cause", "")
            sev = (item.get("severity") or "").lower().strip()

            if tn or rc:
                title = f"تست: {tn}" if tn else "تحلیل شکست"
                detail = f"ریشه مشکل: {rc}" if rc else ""
                if sev:
                    detail = f"[شدت: {sev}] {detail}".strip()
                insights.append({"title": title, "detail": detail})

            if sev in {"high", "medium"}:
                risks.append(
                    {
                        "level": sev,
                        "title": "ریسک شکست در تست‌ها",
                        "action": "رفع سریع ریشه‌ها و افزودن تست پوششی",
                    }
                )

            r = item.get("rationale")
            if isinstance(r, list):
                rationales.extend([str(x).strip() for x in r if str(x).strip()])

    elif failed_count > 0:
        insights.append(
            {"title": "نیاز به رسیدگی", "detail": f"{failed_count} تست شکست خورد."}
        )
        risks.append(
            {
                "level": "medium",
                "title": "ریسک انتشار متوسط",
                "action": "اصلاح تست‌های شکست‌خورده",
            }
        )
    else:
        insights.append({"title": "کیفیت مطلوب", "detail": "هیچ شکست ثبت نشده است."})

    trace = " | ".join(rationales[:10])
    return insights, risks, trace


def _failures_table(summary: dict, llm: dict, funcs: dict) -> List[dict]:
    """
    شکل ردیف‌ها برای UI:
      - title (نام تست)
      - root_cause
      - location (file:line)
      - message (error)
      - suggested_fixes (list)
      - severity, functions, file, link (برای استفاده‌های آتی)
    """
    tbl: List[dict] = []
    lines_map = _line_lookup(funcs)

    # Prefer LLM analysis if present
    if isinstance(llm, dict) and "analysis" in llm and llm["analysis"]:
        for it in llm["analysis"]:
            locus = it.get("locus") or {}
            files = locus.get("files", []) or []
            functions = locus.get("functions", []) or []
            locations = _locations_from_locus(locus, lines_map)

            tbl.append(
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
                    "link": "",
                }
            )
        return tbl

    # Fallback to raw summary (no LLM output)
    for f in summary.get("failed_detail", []) or []:
        tbl.append(
            {
                "id": f.get("id") or f.get("name") or "",
                "title": f.get("name") or "",
                "type": f.get("type") or "unit",
                "message": f.get("error") or "",
                "file": f.get("file") or "",
                "location": f.get("file") or "",
                "link": f.get("link") or "",
                "root_cause": "",
                "severity": "",
                "functions": [],
                "suggested_fixes": [],
            }
        )
    return tbl


# ------------------------- Report assembly -------------------------


def _build_report_json(project_path: Path, out_dir: Path, model_name: str) -> dict:
    summary = _read_json(out_dir / "summary.json")
    prompt = _read_json(out_dir / "llm_prompt.json")
    funcs = _read_json(out_dir / "function_summaries.json")
    llm = _load_llm_analysis(out_dir)

    meta = prompt.get("meta") or {}
    proj_name = (Path(meta.get("project_path") or project_path).resolve()).name

    metrics = {
        "total": summary.get("total_tests", 0),
        "passed": summary.get("passed_tests", 0),
        "failed": summary.get("failed_tests", 0),
        "flaky": summary.get("flaky_tests", 0),
        "skipped": summary.get("skipped_tests", 0),
        "coverage": {
            "lines": summary.get("coverage_lines", 0),
            "branches": summary.get("coverage_branches", 0),
        },
        "durationSec": summary.get("duration_sec", 0),
    }

    failures = _failures_table(summary, llm, funcs)
    insights, risks, trace = _insights_and_risks_from_llm(llm, metrics["failed"])
    summary_text = (
        "در این اجرا کیفیت کلی مناسب است."
        if metrics["failed"] == 0
        else f"{metrics['failed']} تست شکست خورد؛ مسیرهای بحرانی را بررسی کنید."
    )
    charts = _build_charts_data(summary, llm)
    hotspots = _hotspots_from_llm(llm)

    return {
        "schemaVersion": "1.0.0",
        "project": {
            "name": proj_name,
            "runId": meta.get("graph", {}).get("nodes", 0),
            "date": datetime.now().date().isoformat(),
            "model": model_name,
            "build": "",
        },
        "summary": summary_text,
        "metrics": metrics,
        "insights": insights,
        "risks": risks,
        "failures": failures,
        "trace": trace,
        "charts": charts,
        "hotspots": hotspots,
        "raw": {
            "summary": summary,
            "llm_prompt": prompt,
            "function_summaries": {
                k: {"line": v.get("line", 0)} for k, v in (funcs or {}).items()
            },
        },
    }


# ------------------------- HTML rendering -------------------------


def render_report_html(
    project_path: str, out_dir: str, template_path: str, *, model_name: str = "gpt-4o"
) -> str:
    proj = Path(project_path).resolve()
    out = Path(out_dir).resolve()
    tpl = Path(template_path).resolve()
    if not tpl.is_file():
        raise ReportBuildError(f"Template not found: {tpl}")

    report_json = _build_report_json(proj, out, model_name)
    html_tpl = tpl.read_text(encoding="utf-8")

    # Prevent HTML-breaking sequences inside inline JSON
    json_safe = json.dumps(report_json, ensure_ascii=False).replace("<", "\\u003c")

    html = html_tpl.replace(
        "const REPORT = __REPORT_JSON__", f"const REPORT = {json_safe}"
    )
    final_path = proj / "final_report.html"
    final_path.write_text(html, encoding="utf-8")
    return str(final_path)
