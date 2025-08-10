# --- file: cli/main.py ---
import argparse
import os
import logging
from pathlib import Path

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


def parse_args():
    p = argparse.ArgumentParser("LLM-Test CLI")
    p.add_argument(
        "-p", "--project", required=True, help="Path to your project directory"
    )
    p.add_argument(
        "-l",
        "--log",
        required=True,
        help="Path to your test results file (XML or JSON or .trx)",
    )
    p.add_argument(
        "--lang",
        choices=["python", "java", "csharp"],
        help="Project language (auto-detected if omitted)",
    )
    p.add_argument(
        "-o", "--output", default="output", help="Output directory for all artifacts"
    )
    p.add_argument(
        "--model", default="gpt-4o", help="AvalAI model name (e.g. gpt-4o-mini)"
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Only build final prompt, skip AvalAI API call",
    )
    return p.parse_args()


def main():
    args = parse_args()
    os.makedirs(args.output, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    # 0) Detect or override project language
    lang = args.lang or detect_language(args.project)
    logging.info(f"→ Detected language: {lang}")

    # 1) Build dependency graph
    logging.info("→ Building dependency graph…")
    graph = build_graph(args.project)
    visualize_graph(graph, os.path.join(args.output, "graph.html"))

    # 2) Load & tag logs
    logging.info(f"→ Loading test logs from {args.log}…")
    logs = load_test_logs(args.log, lang)
    # hi
    print("⟹ RAW LOG EXAMPLES:", logs[:5])
    print("⟹ NORMALIZED EXAMPLES:")
    for item in logs[:5]:
        raw = item["name"]
        print(f"   {raw}  →  {normalize_test_name(raw, lang)}")
    # Pass 'lang' into tag_graph_with_logs
    graph = tag_graph_with_logs(graph, logs, lang)

    # 3) Test summary
    logging.info("→ Summarizing test results…")
    summary = build_test_summary(graph)
    with open(os.path.join(args.output, "summary.json"), "w", encoding="utf-8") as f:
        import json

        json.dump(summary, f, indent=2, ensure_ascii=False)

    # 4) Critical paths
    logging.info("→ Extracting critical paths…")
    critical = find_critical_paths(graph)

    # 5) Structured prompt
    logging.info("→ Building LLM structured prompt…")
    prompt_path = os.path.join(args.output, "llm_prompt.json")
    build_structured_prompt(
        project_path=args.project, log_path=args.log, lang=lang, output_path=prompt_path
    )

    # 6) Function extraction
    logging.info("→ Extracting critical function code…")
    functions_path = os.path.join(args.output, "function_summaries.json")
    extract_critical_functions(
        project_path=args.project, prompt_file=prompt_path, output_file=functions_path
    )

    # 7) Assemble final textual prompt
    logging.info("→ Assembling final prompt for LLM…")
    langs = infer_languages_from_project(args.project)
    fs_examples = load_few_shots("llm/few_shots", langs, per_lang_limit=1)
    pg = PromptGenerator(
        structured_prompt_path=prompt_path,
        function_summaries_path=functions_path,
        few_shot_examples=fs_examples,
    )
    final_prompt = pg.build()
    with open(
        os.path.join(args.output, "final_prompt.txt"), "w", encoding="utf-8"
    ) as f:
        f.write(final_prompt)

    # 8) If dry-run, skip API
    if args.dry_run:
        logging.info("[i] --dry-run set, skipping AvalAI API call.")
        return

    # 9) Invoke AvalAI
    logging.info("→ Sending prompt to AvalAI for analysis…")
    client = AvalAIClient(model=args.model)
    analysis = client.generate(final_prompt)
    with open(
        os.path.join(args.output, "analysis_report.txt"), "w", encoding="utf-8"
    ) as f:
        f.write(analysis)


if __name__ == "__main__":
    main()
