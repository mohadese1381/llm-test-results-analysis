from __future__ import annotations
import json
from typing import Any, Dict, List, Optional


class PromptGenerator:
    _SYSTEM = (
        "You are an expert software QA/SE assistant. Analyze failed tests across Python/Java/C# projects, "
        "using the provided test summary, critical call paths, and code snippets. "
        "Perform internal step-by-step reasoning but DO NOT reveal chain-of-thought. "
        "Output only the final JSON that follows the required schema. "
        "Explain root causes in detail, suggest fixes, and provide evidence-based rationale. "
        "For each failed test, you MUST provide a concise `failure_type`. "
        "Prefer the simple exception name without package/namespace (e.g., AssertionError, AttributeError, "
        "NullPointerException). If no clear exception, choose a short category like: Timeout, Network, "
        "Configuration, Mocking, DataMismatch, Resource, Flaky, Other."
    )

    _OUTPUT_SCHEMA = {
        "analysis": [
            {
                "test_name": "<string>",
                "error": "<string>",
                "call_path": ["<node_1>", "..."],
                "locus": {
                    "files": ["<relpath>", "..."],
                    "functions": ["<file::Class::func>", "..."],
                },
                "failure_type": "<short normalized type, e.g. AssertionError | NullPointerException | Timeout | Other>",
                "root_cause": "<precise details in at least one sentence to 3 sentences at most>",
                "severity": "<low|medium|high>",
                "suggested_fixes": ["<actionable fix 1>", "<actionable fix 2>"],
                "rationale": ["<short high-level evidence, no CoT>", "..."],
            }
        ]
    }

    def __init__(
        self,
        structured_prompt_path: str,
        function_summaries_path: str,
        few_shot_examples: Optional[List[Dict[str, str]]] = None,
        *,
        max_snippet_lines: int = 10,
    ):
        with open(structured_prompt_path, encoding="utf-8") as f:
            self._data: Dict[str, Any] = json.load(f)
        with open(function_summaries_path, encoding="utf-8") as f:
            self._funcs: Dict[str, Any] = json.load(f)
        self._few_shot = few_shot_examples or []
        self._max_snip = max_snippet_lines

    def build(self) -> str:
        parts = [
            self._render_instruction(),
            self._render_context_summary(),
            self._render_critical_paths_text(),
            self._render_function_snippets(),
        ]
        if self._few_shot:
            parts.append(self._render_few_shot())
        parts.append(self._render_output_contract())
        return "\n\n".join(p for p in parts if p)

    def _render_instruction(self) -> str:
        return (
            f"{self._SYSTEM}\n"
            "Your tasks:\n"
            "1) Identify which tests failed and what the exact error messages are.\n"
            "2) Map failures to project areas using the provided critical paths.\n"
            "3) Produce a concise root-cause analysis per failed test.\n"
            "4) Propose concrete fixes (code-level and/or config/integration).\n"
            "5) If signals suggest flaky/environmental issues, state it explicitly.\n"
            "6) Set `failure_type` to a SHORT normalized label (exception simple name or category). "
            "Examples: AssertionError, AttributeError, NullPointerException, Timeout, Network, Configuration, Mocking, Other.\n"
            "Do not include chain-of-thought or step-by-step reasoning in the output; only final JSON."
        )

    def _render_context_summary(self) -> str:
        s = self._data["summary"]
        total = s.get("total_tests", 0)
        passed = s.get("passed_tests", 0)
        failed = s.get("failed_tests", 0)
        skipped = s.get("skipped_tests", 0)
        lines = [
            "TEST SUMMARY:",
            f"- Total: {total} | Passed: {passed} | Failed: {failed} | Skipped: {skipped}",
        ]
        if s.get("failed_detail"):
            lines.append("- Failures:")
            for f in s["failed_detail"]:
                err = f.get("error") or "<no message>"
                lines.append(f"  • {f.get('name','')}: {err}")
        return "\n".join(lines)

    def _render_critical_paths_text(self) -> str:
        out = ["CRITICAL PATHS:"]
        for test, info in self._data.get("critical_paths", {}).items():
            out.append(f"\nTest: {test}")
            err = info.get("error") or ""
            if err:
                out.append(f"Error: {err}")
            for direction in ("upstream", "downstream"):
                paths = info.get(direction, [])
                if not paths:
                    continue
                out.append(f"{direction.capitalize()}:")
                for path in paths:
                    seq = " → ".join(n.get("node", "?") for n in path)
                    out.append(f"  • {seq}")
        return "\n".join(out)

    def _render_function_snippets(self) -> str:
        if not self._funcs:
            return ""
        out = ["FUNCTION SNIPPETS (trimmed):"]
        for key, v in self._funcs.items():
            code = (v.get("code") or "").splitlines()
            head = code[: self._max_snip]
            if len(code) > self._max_snip:
                head.append("    ...")
            block = "\n".join(f"    {l}" for l in head)
            doc = (v.get("docstring") or "").strip()
            line = v.get("line")
            out.append(f'\n{key} (line {line}):\n"""\n{doc}\n"""\n{block}')
        return "\n".join(out)

    def _render_few_shot(self) -> str:
        lines = ["FEW-SHOT EXAMPLES (style only):"]
        for ex in self._few_shot:
            ip = ex.get("input", "").strip()
            op = ex.get("output", "").strip()
            if not ip or not op:
                continue
            lines.append(f"\nINPUT:\n{ip}\nOUTPUT:\n{op}")
        return "\n".join(lines)

    def _render_output_contract(self) -> str:
        schema = json.dumps(self._OUTPUT_SCHEMA, indent=2, ensure_ascii=False)
        return (
            "RESPONSE FORMAT:\n"
            "Return JSON only. Do not add commentary, markdown fences or chain-of-thought. "
            "Keep `rationale` to ≤3 short bullets.\n"
            f"Schema:\n{schema}"
        )
