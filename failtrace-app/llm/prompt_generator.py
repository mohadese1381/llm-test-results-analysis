import json
from typing import Any, Dict, List, Optional


class PromptGenerator:
    """
    Assemble a best‐practice prompt for analyzing failed tests
    via a large language model.
    """

    # 1) Define system role & overall instructions up front.
    _SYSTEM_INSTRUCTION = """\
You are a senior software engineer and AI analyst. \
Your job is to deeply analyze failed unit tests or integration tests, trace through the critical call paths, \
and pinpoint root causes in the code. \
You will answer in STRICT JSON using the schema below, and include your step-by-step reasoning.\
"""

    # 2) Specify the exact JSON schema we expect.
    _OUTPUT_SCHEMA = {
        "analysis": [
            {
                "test_name": "<string>",
                "error": "<string>",
                "call_path": ["<func1>", "..."],
                "reasoning": ["<step 1 chain-of-thought>", "..."],
                "root_cause": "<one-sentence summary>",
                "suggested_fixes": ["<fix 1>", "<fix 2>"]
            }
        ]
    }

    def __init__(
        self,
        structured_prompt_path: str,
        function_summaries_path: str,
        few_shot_examples: Optional[List[Dict[str, str]]] = None,
    ):
        with open(structured_prompt_path, encoding="utf-8") as f:
            self._data: Dict[str, Any] = json.load(f)

        with open(function_summaries_path, encoding="utf-8") as f:
            self._funcs: Dict[str, Any] = json.load(f)

        self._few_shot = few_shot_examples or []

    def build(self) -> str:
        parts = [
            self._SYSTEM_INSTRUCTION.strip(),
            self._render_graph_summary(),
            self._render_test_summary(),
            self._render_critical_paths(),
            self._render_function_snippets(),
        ]

        if self._few_shot:
            parts.append(self._render_few_shot())

        parts.append(self._render_output_instruction())
        return "\n\n".join(parts)

    def _render_graph_summary(self) -> str:
        meta = self._data["meta"]
        nodes = meta["graph"]["nodes"]
        edges = meta["graph"]["edges"]
        return f"GRAPH SUMMARY: {nodes} nodes, {edges} edges."

    def _render_test_summary(self) -> str:
        s = self._data["summary"]
        lines = [
            "TEST SUMMARY:",
            f"• Total: {s['total_tests']}",
            f"• Executed: {s['executed_tests']} (✅{s['passed_tests']}, ❌{s['failed_tests']}, ⚠️{s['skipped_tests']})",
        ]
        if s.get("failed_detail"):
            lines.append("• Failures detail:")
            for f in s["failed_detail"]:
                err = f["error"] or "<no message>"
                lines.append(f"  - {f['name']}: {err}")
        return "\n".join(lines)

    def _render_critical_paths(self) -> str:
        out = ["CRITICAL PATHS for each failed test:"]
        for test, info in self._data["critical_paths"].items():
            out.append(f"\nTest: {test}")
            out.append(f"Error: {info.get('error','')}")
            # pick the longest downstream path for clarity
            for direction in ("upstream","downstream"):
                out.append(f"{direction.capitalize()}:")
                for path in info.get(direction, []):
                    seq = " → ".join(n["node"] for n in path)
                    out.append(f"  • {seq}")
        return "\n".join(out)

    def _render_function_snippets(self) -> str:
        out = ["FUNCTION SNIPPETS:"]
        for key, v in self._funcs.items():
            code = v["code"].splitlines()
            snippet = code[:8] + (["    ..."] if len(code) > 8 else [])
            block = "\n".join(f"    {l}" for l in snippet)
            out.append(f"\n{key} (line {v['line']}):\n\"\"\"\n{v['docstring']}\n\"\"\"\n{block}")
        return "\n".join(out)

    def _render_few_shot(self) -> str:
        lines = ["FEW-SHOT EXAMPLES:"]
        for ex in self._few_shot:
            lines.append(f"\nINPUT:\n{ex['input']}\nOUTPUT:\n{ex['output']}")
        return "\n".join(lines)

    def _render_output_instruction(self) -> str:
        schema = json.dumps(self._OUTPUT_SCHEMA, indent=2, ensure_ascii=False)
        return (
            "Now produce your analysis as JSON ONLY, strictly following this schema:\n"
            f"```json\n{schema}\n```\n"
            "Include numbered `reasoning` steps to expose your chain-of-thought."
        )
