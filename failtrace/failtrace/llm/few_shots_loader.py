from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Iterable, List
import json

EXT_TO_LANG: Dict[str, str] = {
    ".py": "python",
    ".java": "java",
    ".cs": "csharp",
}


def infer_languages_from_project(project_root: str) -> List[str]:
    """
    با پیمایش پوشهٔ پروژه، زبان‌های موجود را کشف می‌کند.
    خروجی: لیست یکتا از {"python","java","csharp"} بر اساس پسوند فایل‌ها.
    """
    root = Path(project_root)
    langs: Dict[str, bool] = {"python": False, "java": False, "csharp": False}

    for p in root.rglob("*"):
        if not p.is_file():
            continue
        ext = p.suffix.lower()
        lang = EXT_TO_LANG.get(ext)
        if lang:
            langs[lang] = True

    return [k for k, v in langs.items() if v]


def load_few_shots(
    fs_dir: str, langs: Iterable[str], per_lang_limit: int = 2
) -> List[Dict[str, str]]:
    """
    از پوشهٔ few_shots برای زبان‌های داده‌شده مثال‌ها را می‌خواند.
    هر فایل باید آرایه‌ای از {input, output} باشد.
    per_lang_limit: حداکثر مثال در هر زبان (برای جلوگیری از بزرگ‌شدن پرامپت).
    """
    out: List[Dict[str, str]] = []
    base = Path(fs_dir)

    for lang in langs:
        files = sorted(base.glob(f"{lang}_*.json"))
        count = 0
        for f in files:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            for ex in data:
                if isinstance(ex, dict) and "input" in ex and "output" in ex:
                    out.append({"input": ex["input"], "output": ex["output"]})
                    count += 1
                    if count >= per_lang_limit:
                        break
            if count >= per_lang_limit:
                break

    return out
