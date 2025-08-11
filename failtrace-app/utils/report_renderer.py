from __future__ import annotations
from pathlib import Path
from datetime import datetime
import json
from collections import Counter


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


def _build_charts_data(summary: dict) -> dict:
    passed = summary.get("passed_tests", 0)
    failed = summary.get("failed_tests", 0)
    skipped = summary.get("skipped_tests", 0)
    flaky = summary.get("flaky_tests", 0)
    failure_types = [
        f.get("type") or "Unknown" for f in summary.get("failed_detail", []) or []
    ]
    failure_counts = dict(Counter(failure_types))
    return {
        "testsOverview": {
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "flaky": flaky,
        },
        "failureTypes": [
            {"type": t, "count": c}
            for t, c in sorted(failure_counts.items(), key=lambda x: x[1], reverse=True)
        ],
    }


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
    failures = [
        {
            "id": f.get("id") or f.get("name") or "",
            "title": f.get("name") or "",
            "type": f.get("type") or "unit",
            "message": f.get("error") or "",
            "file": f.get("file") or "",
            "link": f.get("link") or "",
        }
        for f in summary.get("failed_detail", []) or []
    ]
    insights, risks, trace = [], [], ""
    if isinstance(llm, dict) and "analysis" in llm:
        for item in llm["analysis"]:
            insights.append(
                {
                    "title": f"تست: {item.get('test_name','')}",
                    "detail": f"ریشه مشکل: {item.get('root_cause','')}",
                }
            )
        if metrics["failed"] > 0:
            risks.append(
                {
                    "level": "medium",
                    "title": "وجود تست‌های شکست‌خورده",
                    "action": "رسیدگی به ریشه‌ها/کاهش flaky",
                }
            )
        try:
            steps = []
            for item in llm["analysis"]:
                r = item.get("reasoning")
                if isinstance(r, list):
                    steps.extend(r[:3])
            trace = " | ".join(steps[:10])
        except Exception:
            trace = ""
    else:
        if metrics["failed"] == 0:
            insights.append(
                {"title": "کیفیت مطلوب", "detail": "هیچ شکست ثبت نشده است."}
            )
        else:
            insights.append(
                {
                    "title": "نیاز به رسیدگی",
                    "detail": f"{metrics['failed']} تست شکست خورد.",
                }
            )
            risks.append(
                {
                    "level": "medium",
                    "title": "ریسک انتشار متوسط",
                    "action": "اصلاح تست‌های شکست‌خورده",
                }
            )
    summary_text = (
        "در این اجرا کیفیت کلی مناسب است."
        if metrics["failed"] == 0
        else f"{metrics['failed']} تست شکست خورد؛ مسیرهای بحرانی را بررسی کنید."
    )
    charts = _build_charts_data(summary)
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
        "raw": {
            "summary": summary,
            "llm_prompt": prompt,
            "function_summaries": {
                k: {"line": v.get("line", 0)} for k, v in (funcs or {}).items()
            },
        },
    }


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
    json_safe = json.dumps(report_json, ensure_ascii=False).replace("<", "\\u003c")
    html = html_tpl.replace(
        "const REPORT = __REPORT_JSON__", f"const REPORT = {json_safe}"
    )
    final_path = proj / "final_report.html"
    final_path.write_text(html, encoding="utf-8")
    return str(final_path)
