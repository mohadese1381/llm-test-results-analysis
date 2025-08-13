from __future__ import annotations
import os, time, logging
from typing import Optional
from openai import OpenAI
from openai._exceptions import APIError, RateLimitError, APITimeoutError

_DEFAULT_SYSTEM = (
    "Role: Senior QA/SE assistant integrated into a test pipeline.\n"
    "Goal: Perform rigorous root-cause analysis of FAILED tests using provided inputs, "
    "and return ONLY final JSON according to the schema. Do NOT reveal chain-of-thought.\n"
    "Inputs you may receive: (1) aggregated test summary with failed_detail, (2) critical call paths "
    "(upstream/downstream nodes), (3) trimmed code snippets of critical functions.\n"
    "Languages: python, java, csharp. Be language-aware but framework-agnostic.\n"
    "Requirements:\n"
    "- Identify which tests failed and the exact error text.\n"
    "- Map each failure to involved files/functions via critical paths.\n"
    "- Provide a precise root cause at code/config level (not generic).\n"
    "- Propose actionable fixes (code and/or integration/config). Be specific.\n"
    "- If signals indicate flaky/environmental issues, state it explicitly.\n"
    "- Be concise and factual; avoid speculation beyond evidence.\n"
    "- NO markdown, NO explanations, NO chain-of-thought in output.\n"
    "Output contract:\n"
    "{\n"
    '  "analysis": [\n'
    "    {\n"
    '      "test_name": "<string>",\n'
    '      "error": "<string>",\n'
    '      "call_path": ["<node_1>", "..."],\n'
    '      "locus": {\n'
    '        "files": ["<relpath>", "..."],\n'
    '        "functions": ["<file::Class::func>", "..."]\n'
    "      },\n"
    '      "root_cause": "<concise single sentence>",\n'
    '      "severity": "<low|medium|high>",\n'
    '      "suggested_fixes": ["<fix 1>", "<fix 2>"],\n'
    '      "rationale": ["<short evidence 1>", "<short evidence 2>", "<short evidence 3>"]\n'
    "    }\n"
    "  ]\n"
    "}\n"
    "Rules:\n"
    "- If a field is unknown, omit it; do NOT fabricate.\n"
    "- Keep rationale to ≤3 short bullets with evidence references (e.g., node names, error text). "
    "Do NOT include intermediate chain-of-thought or numbered reasoning steps.\n"
    "- Return JSON only. No backticks, no prose."
)


class AvalAIClient:
    def __init__(
        self,
        model: str = "gpt-4o",
        *,
        api_key_env: str = "AVALAI_API_KEY",
        base_url_env: str = "AVALAI_BASE_URL",
        default_base_url: str = "https://api.avalai.ir/v1",
        temperature: float = 0.2,
        max_tokens: int = 2000,
        system_profile: Optional[str] = None,
    ) -> None:
        api_key = os.getenv(api_key_env)
        if not api_key:
            raise RuntimeError(f"Set your {api_key_env} environment variable")
        base_url = os.getenv(base_url_env, default_base_url).rstrip("/")
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.system_profile = (system_profile or _DEFAULT_SYSTEM).strip()

    def generate(self, prompt: str, *, retries: int = 3) -> str:
        logging.info(
            f"[AvalAI] base_url={self.client.base_url} model={self.model} "
            f"temp={self.temperature} max_tokens={self.max_tokens}"
        )
        delay = 1.5
        last_err: Optional[Exception] = None
        for _ in range(retries):
            try:
                resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": self.system_profile},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                )
                return (resp.choices[0].message.content or "").strip()
            except (APITimeoutError, RateLimitError, APIError) as e:
                detail = getattr(e, "response", None)
                if detail is not None:
                    try:
                        payload = detail.json()
                    except Exception:
                        payload = {}
                    err = payload.get("error") or {}
                    err_code = err.get("code")
                    err_msg = err.get("message") or str(e)
                    logging.error(f"[AvalAI] API error (code={err_code}): {err_msg}")
                last_err = e
                time.sleep(delay)
                delay *= 2
        if last_err:
            raise last_err
        return ""
