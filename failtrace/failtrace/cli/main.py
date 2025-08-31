import argparse
import logging
import pickle
import time
from pathlib import Path
import json
import webbrowser
import shutil

import networkx as nx
from platformdirs import user_data_dir, user_documents_dir

from ..graph.builder import build_graph, detect_language
from ..utils.visualizer import visualize_graph
from ..analysis.mapper import load_test_logs, tag_graph_with_logs
from ..analysis.summarizer import build_test_summary
from ..analysis.critical_path_extractor import find_critical_paths
from ..llm.structured_prompt_builder import build_structured_prompt
from ..analysis.function_extractor import extract_critical_functions
from ..llm.prompt_generator import PromptGenerator
from ..llm.avalai_client import AvalAIClient
from ..llm.few_shots_loader import infer_languages_from_project, load_few_shots
from ..utils.report_renderer import render_report_html, ReportBuildError

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def _get_internal_output_dir() -> Path:
    out_dir = Path(user_data_dir("failtrace", "failtrace"))
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def _get_report_output_dir() -> Path:
    reports_dir = Path(user_documents_dir()) / "FailTraceReports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    return reports_dir


def _graph_cache_path(output_dir: str | Path) -> Path:
    return Path(output_dir).joinpath("cache", "graph.pkl")


def _save_graph(graph: nx.DiGraph, output_dir: str | Path) -> None:
    p = _graph_cache_path(output_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "wb") as f:
        pickle.dump(graph, f, protocol=pickle.HIGHEST_PROTOCOL)


def _load_graph(output_dir: str | Path) -> nx.DiGraph | None:
    p = _graph_cache_path(output_dir)
    if not p.is_file():
        return None
    try:
        with open(p, "rb") as f:
            return pickle.load(f)
    except Exception:
        return None


def _assemble_and_maybe_call_api(
    prompt_path: Path,
    functions_path: Path,
    model: str,
    dry_run: bool,
    output_dir: Path,
    project_path: str,
) -> None:
    langs = infer_languages_from_project(project_path)
    root_dir = Path(__file__).resolve().parents[2]
    fs_dir = root_dir / "failtrace" / "llm" / "few_shots"
    fs_examples = load_few_shots(fs_dir, langs, per_lang_limit=1)
    pg = PromptGenerator(
        structured_prompt_path=str(prompt_path),
        function_summaries_path=str(functions_path),
        few_shot_examples=fs_examples,
    )
    final_prompt = pg.build()
    (output_dir / "final_prompt.txt").write_text(final_prompt, encoding="utf-8")
    if dry_run:
        logger.info("✔ Final prompt built (dry-run, no API call).")
        return
    logger.info("✔ Sending prompt to AvalAI for analysis…")
    client = AvalAIClient(model=model)
    analysis = client.generate(final_prompt)
    (output_dir / "analysis_report.txt").write_text(analysis, encoding="utf-8")


def _emit_report(args, out_dir: Path) -> None:
    try:
        template_path = (
            Path(__file__).resolve().parents[1] / "report" / "report_template.html"
        )
        final = render_report_html(
            project_path=args.project,
            out_dir=str(out_dir),
            template_path=str(template_path),
        )

        report_dir = _get_report_output_dir()
        final_report = report_dir / f"report_{int(time.time())}.html"
        Path(final).replace(final_report)

        pkg_root = Path(__file__).resolve().parents[1]

        src_lib = pkg_root / "lib"
        dst_lib = report_dir / "lib"
        if dst_lib.exists():
            shutil.rmtree(dst_lib)
        if src_lib.exists():
            shutil.copytree(src_lib, dst_lib)

        src_report = pkg_root / "report"
        for asset in src_report.glob("*.css"):
            shutil.copy(asset, report_dir / asset.name)
        for asset in src_report.glob("*.js"):
            shutil.copy(asset, report_dir / asset.name)

        logger.info(f"✔ Report generated: {final_report}")
        if getattr(args, "open_report", False):
            webbrowser.open(f"file://{final_report}")
    except ReportBuildError as e:
        logger.error(f"✖ Failed to build report: {e}")
    except Exception as e:
        logger.error(f"✖ Unexpected error: {e}")


def _timed_step(step_num, total_steps, description, func, *args, **kwargs):
    start = time.perf_counter()
    logger.info(f"✔ {description}...")
    result = func(*args, **kwargs)
    elapsed = time.perf_counter() - start
    logger.info(
        f"Completed in {elapsed:.2f}s ({int((step_num/total_steps)*100)}% done)"
    )
    return result


def run_full(args) -> None:
    out_dir = _get_internal_output_dir()
    total_steps = 8
    lang = _timed_step(
        1, total_steps, "Detecting language", detect_language, args.project
    )
    graph = _timed_step(
        2, total_steps, "Building dependency graph", build_graph, args.project
    )
    _timed_step(
        3,
        total_steps,
        "Visualizing graph",
        visualize_graph,
        graph,
        str(out_dir / "graph.html"),
    )
    logs = _timed_step(
        4, total_steps, "Loading test logs", load_test_logs, args.log, lang
    )
    _timed_step(
        5,
        total_steps,
        "Tagging graph with logs",
        tag_graph_with_logs,
        graph,
        logs,
        lang,
    )
    _save_graph(graph, out_dir)
    summary = _timed_step(
        6, total_steps, "Summarizing test results", build_test_summary, graph
    )
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    prompt_path = out_dir / "llm_prompt.json"
    _timed_step(
        7,
        total_steps,
        "Building LLM structured prompt",
        build_structured_prompt,
        project_path=args.project,
        log_path=args.log,
        lang=lang,
        output_path=str(prompt_path),
    )
    functions_path = out_dir / "function_summaries.json"
    _timed_step(
        8,
        total_steps,
        "Extracting critical function code",
        extract_critical_functions,
        project_path=args.project,
        prompt_file=str(prompt_path),
        output_file=str(functions_path),
    )
    _assemble_and_maybe_call_api(
        prompt_path, functions_path, args.model, args.dry_run, out_dir, args.project
    )
    _emit_report(args, out_dir)


def run_quick(args) -> None:
    out_dir = _get_internal_output_dir()
    total_steps = 7
    lang = _timed_step(
        1, total_steps, "Detecting language", detect_language, args.project
    )
    graph = _timed_step(2, total_steps, "Loading cached graph", _load_graph, out_dir)
    if graph is None:
        graph = _timed_step(
            3, total_steps, "Building dependency graph", build_graph, args.project
        )
        logs = load_test_logs(args.log, lang)
        graph = tag_graph_with_logs(graph, logs, lang)
        _save_graph(graph, out_dir)
    logs = _timed_step(
        4, total_steps, "Loading test logs", load_test_logs, args.log, lang
    )
    _timed_step(
        5,
        total_steps,
        "Tagging graph with logs",
        tag_graph_with_logs,
        graph,
        logs,
        lang,
    )
    summary = _timed_step(
        6, total_steps, "Summarizing test results", build_test_summary, graph
    )
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    critical = _timed_step(
        7, total_steps, "Extracting critical paths", find_critical_paths, graph
    )
    prompt_path = out_dir / "llm_prompt.json"
    structured_prompt = {
        "meta": {
            "project_path": args.project,
            "log_path": args.log,
            "language": lang,
            "graph": {
                "nodes": graph.number_of_nodes(),
                "edges": graph.number_of_edges(),
            },
        },
        "summary": summary,
        "critical_paths": critical,
    }
    prompt_path.write_text(
        json.dumps(structured_prompt, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    functions_path = out_dir / "function_summaries.json"
    extract_critical_functions(args.project, str(prompt_path), str(functions_path))
    _assemble_and_maybe_call_api(
        prompt_path, functions_path, args.model, args.dry_run, out_dir, args.project
    )
    _emit_report(args, out_dir)


def parse_args():
    p = argparse.ArgumentParser("LLM-Test CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_common(sp):
        sp.add_argument(
            "-p", "--project", required=True, help="Path to your project directory"
        )
        sp.add_argument(
            "-l",
            "--log",
            required=True,
            help="Path to your test results file (XML/JSON/.trx)",
        )
        sp.add_argument(
            "--lang",
            choices=["python", "java", "csharp"],
            help="Project language (auto-detected if omitted)",
        )
        sp.add_argument(
            "--model", default="gpt-4o", help="AvalAI model name (e.g. gpt-4o-mini)"
        )
        sp.add_argument(
            "--dry-run",
            action="store_true",
            help="Only build final prompt, skip AvalAI API call",
        )
        sp.add_argument(
            "--open-report",
            action="store_true",
            help="Open generated report in default browser",
        )

    sp_full = sub.add_parser(
        "full", help="Build graph from scratch, then run the whole pipeline"
    )
    add_common(sp_full)
    sp_quick = sub.add_parser(
        "quick", help="Reuse cached graph; only retag with new logs and continue"
    )
    add_common(sp_quick)
    return p.parse_args()


def main():
    args = parse_args()
    if args.cmd == "full":
        run_full(args)
    elif args.cmd == "quick":
        run_quick(args)
    else:
        raise SystemExit(f"Unknown command: {args.cmd}")


if __name__ == "__main__":
    main()
