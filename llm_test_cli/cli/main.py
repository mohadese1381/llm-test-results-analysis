import argparse
import os
import logging
import pickle
from pathlib import Path
import json

import networkx as nx

from graph.graph_builder import build_graph, detect_language
from utils.visualizer import visualize_graph
from analysis.mapper import load_test_logs, tag_graph_with_logs
from analysis.summarizer import build_test_summary
from analysis.critical_path_extractor import find_critical_paths
from llm.structured_prompt_builder import build_structured_prompt
from llm.function_extractor import extract_critical_functions
from llm.prompt_generator import PromptGenerator
from llm.avalai_client import AvalAIClient
from llm.few_shots_loader import infer_languages_from_project, load_few_shots
from utils.normalize import normalize_test_name


# ----------------------------- logging -----------------------------
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


# ----------------------------- cache utils -----------------------------
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
            return pickle.load(f)  # type: ignore[no-any-return]
    except Exception as e:
        logger.warning(f"[cache] Failed to load cached graph ({p}): {e}")
        return None


# ----------------------------- helpers -----------------------------
def _log_examples(logs, lang: str) -> None:
    if not logs:
        return
    print("⟹ RAW LOG EXAMPLES:", logs[:5])
    print("⟹ NORMALIZED EXAMPLES:")
    for item in logs[:5]:
        raw = item.get("name", "")
        print(f"   {raw}  →  {normalize_test_name(raw, lang)}")


def _assemble_and_maybe_call_api(
    prompt_path: Path,
    functions_path: Path,
    model: str,
    dry_run: bool,
    output_dir: Path,
    project_path: str,
) -> None:
    # Few-shot
    langs = infer_languages_from_project(project_path)
    fs_examples = load_few_shots("llm/few_shots", langs, per_lang_limit=1)

    # Build final prompt text
    pg = PromptGenerator(
        structured_prompt_path=str(prompt_path),
        function_summaries_path=str(functions_path),
        few_shot_examples=fs_examples,
    )
    final_prompt = pg.build()
    (output_dir / "final_prompt.txt").write_text(final_prompt, encoding="utf-8")

    if dry_run:
        logger.info("[i] --dry-run set, skipping AvalAI API call.")
        return

    # Call AvalAI
    logger.info("→ Sending prompt to AvalAI for analysis…")
    client = AvalAIClient(model=model)
    analysis = client.generate(final_prompt)
    (output_dir / "analysis_report.txt").write_text(analysis, encoding="utf-8")


# ----------------------------- subcommands -----------------------------
def run_full(args) -> None:
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 0) Detect or override language
    lang = args.lang or detect_language(args.project)
    logger.info(f"→ Detected language: {lang}")

    # 1) Build dependency graph (fresh) + visualize + cache
    logger.info("→ Building dependency graph…")
    graph = build_graph(args.project)
    visualize_graph(graph, str(out_dir / "graph.html"))
    _save_graph(graph, out_dir)

    # 2) Load logs & tag graph (for local viz/debug)
    logger.info(f"→ Loading test logs from {args.log}…")
    logs = load_test_logs(args.log, lang)
    _log_examples(logs, lang)
    tag_graph_with_logs(graph, logs, lang)  # tagging only for the in-memory viz

    # ✅ 2.5) Summarize (also write summary.json in FULL mode)
    logger.info("→ Summarizing test results…")
    summary = build_test_summary(graph)
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # 3) Build structured prompt (this function builds graph internally again)
    logger.info("→ Building LLM structured prompt…")
    prompt_path = out_dir / "llm_prompt.json"
    build_structured_prompt(
        project_path=args.project,
        log_path=args.log,
        lang=lang,
        output_path=str(prompt_path),
    )

    # 4) Extract critical function code
    logger.info("→ Extracting critical function code…")
    functions_path = out_dir / "function_summaries.json"
    extract_critical_functions(
        project_path=args.project,
        prompt_file=str(prompt_path),
        output_file=str(functions_path),
    )

    # 5) Assemble final textual prompt & maybe call API
    logger.info("→ Assembling final prompt for LLM…")
    _assemble_and_maybe_call_api(
        prompt_path=prompt_path,
        functions_path=functions_path,
        model=args.model,
        dry_run=args.dry_run,
        output_dir=out_dir,
        project_path=args.project,
    )


def run_quick(args) -> None:
    """
    Quick path:
      - Load cached graph (or build once as fallback and cache it)
      - Load & tag NEW logs on that graph
      - Build summary + critical paths locally (بدون ساخت مجدد گراف)
      - Write llm_prompt.json
      - Extract functions + assemble + (optional) call API
    """
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 0) Detect or override language
    lang = args.lang or detect_language(args.project)
    logger.info(f"→ Detected language: {lang}")

    # 1) Load cached graph or build once if missing
    graph = _load_graph(out_dir)
    if graph is None:
        logger.info("→ No cached graph found; building once and caching it…")
        graph = build_graph(args.project)
        _save_graph(graph, out_dir)

    # 2) Load logs & tag (on cached graph)
    logger.info(f"→ Loading test logs from {args.log}…")
    logs = load_test_logs(args.log, lang)
    _log_examples(logs, lang)
    graph = tag_graph_with_logs(graph, logs, lang)

    # 3) Build summary & critical paths locally (fast)
    logger.info("→ Summarizing test results…")
    summary = build_test_summary(graph)
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    logger.info("→ Extracting critical paths…")
    critical = find_critical_paths(graph)

    # 4) Write llm_prompt.json (without rebuilding graph)
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
        json.dumps(structured_prompt, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # 5) Extract critical function code
    logger.info("→ Extracting critical function code…")
    functions_path = out_dir / "function_summaries.json"
    extract_critical_functions(
        project_path=args.project,
        prompt_file=str(prompt_path),
        output_file=str(functions_path),
    )

    # 6) Assemble + (optional) call API
    logger.info("→ Assembling final prompt for LLM…")
    _assemble_and_maybe_call_api(
        prompt_path=prompt_path,
        functions_path=functions_path,
        model=args.model,
        dry_run=args.dry_run,
        output_dir=out_dir,
        project_path=args.project,
    )


# ----------------------------- argparse -----------------------------
def parse_args():
    p = argparse.ArgumentParser("LLM-Test CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    # common flags for both commands
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
            "-o",
            "--output",
            default="output",
            help="Output directory for all artifacts",
        )
        sp.add_argument(
            "--model", default="gpt-4o", help="AvalAI model name (e.g. gpt-4o-mini)"
        )
        sp.add_argument(
            "--dry-run",
            action="store_true",
            help="Only build final prompt, skip AvalAI API call",
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


# ----------------------------- main -----------------------------
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
