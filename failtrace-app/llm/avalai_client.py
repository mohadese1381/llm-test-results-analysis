from __future__ import annotations

import os
import time
import logging
from typing import Optional

from openai import OpenAI
from openai._exceptions import APIError, RateLimitError, APITimeoutError


class AvalAIClient:
    """
    OpenAI-compatible client for AvalAI.
    Env:
      - AVALAI_API_KEY: required
      - AVALAI_BASE_URL: optional (default: https://api.avalai.ir/v1)
    """

    def __init__(
        self,
        model: str = "gpt-4o",                    
        *,
        api_key_env: str = "AVALAI_API_KEY",
        base_url_env: str = "AVALAI_BASE_URL",
        default_base_url: str = "https://api.avalai.ir/v1",
        temperature: float = 0.2,
        max_tokens: int = 2000,
    ) -> None:
        api_key = os.getenv(api_key_env)
        if not api_key:
            raise RuntimeError(f"Set your {api_key_env} environment variable")

        base_url = os.getenv(base_url_env, default_base_url).rstrip("/")
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    def generate(self, prompt: str, *, retries: int = 3) -> str:
        """
        Send a single-turn prompt. Returns assistant text or empty string.
        Retries on transient errors with exponential backoff.
        """
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
                        {
                            "role": "system",
                            "content": (
                                "You are a precise software analysis assistant. "
                                "Analyze the provided test failures, identify root causes, "
                                "and suggest concrete fixes."
                            ),
                        },
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
                    err = (payload.get("error") or {})
                    err_code = err.get("code")
                    err_msg  = err.get("message") or str(e)
                    logging.error(f"[AvalAI] API error (code={err_code}): {err_msg}")

                    if err_code in {"insufficient_tier", "model_not_found"}:
                        logging.error(
                            "Selected model is not available on your plan. "
                            "Use a permitted model for Tier 1 (e.g., gpt-4o) or upgrade your plan."
                        )

                last_err = e
                time.sleep(delay)
                delay *= 2

        if last_err:
            raise last_err
        return ""
