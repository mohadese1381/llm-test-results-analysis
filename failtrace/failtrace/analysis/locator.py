from __future__ import annotations

import re
from typing import List, Tuple, Dict

# ───────────────────────── Regex ها (پوشش کامل‌تر) ─────────────────────────

# ویندوز با درایو:  C:\path\to\file.py:24
_WIN_DRIVE = re.compile(r"([A-Za-z]:\\[^:\n]+):(\d+)")

# ویندوز بدون درایو (بک‌اسلش):  tests\unit\file.py:24
# چندین بخش با '\' و در انتها فایل با پسوند معتبر
_WIN_NODRIVE = re.compile(r"((?:[^:\n]+\\)+[^:\n]+\.(?:py|java|cs)):(\d+)")

# UNC:  \\server\share\path\file.cs:10
_UNC = re.compile(r"(\\\\[^\n:]+):(\d+)")

# POSIX:  ./path/to/file.py:24  یا  path/to/file.java:80
_POSIX = re.compile(r"((?:\./)?[^:\n]+\.(?:py|java|cs)):(\d+)")

# MSBuild (Windows):  C:\path\file.cs(24,5)
_MSBUILD_WIN = re.compile(r"([A-Za-z]:\\[^()\n]+\.(?:cs|vb))\((\d+)(?:,\d+)?\)")

# MSBuild (POSIX):  ./src/file.py(24,5)
_MSBUILD_POSIX = re.compile(r"((?:\./)?[^()\n]+\.(?:cs|vb|java|py))\((\d+)(?:,\d+)?\)")

# جاوا داخل پرانتز:  (Foo.java:12)
_JAVA_PAREN = re.compile(r"\(([^():\n]+\.java):(\d+)\)")

# traceback پایتون:  File "C:\...\file.py", line 24
_PY_FILE_LINE = re.compile(r'File\s+"([^"\n]+\.py)",\s+line\s+(\d+)')

# ترتیب جست‌وجو مهم نیست اما فرمت‌های پرکاربرد را جلوتر گذاشتیم
_PATTERNS: List[re.Pattern[str]] = [
    _MSBUILD_WIN,
    _MSBUILD_POSIX,
    _JAVA_PAREN,
    _PY_FILE_LINE,
    _WIN_DRIVE,
    _WIN_NODRIVE,
    _UNC,
    _POSIX,
]

_ANCHORS = ("tests", "src", "source", "app", "lib")


def _strip_drive_prefix(chain: str) -> str:
    """حذف پیشوند درایو ویندوز مثل 'C:>' از ابتدای زنجیره."""
    return re.sub(r"^[A-Za-z]:>", "", chain, count=1)


def _shorten_to_anchor(chain: str) -> str:
    """
    اگر یکی از ریشه‌های رایج پروژه (tests/src/source/app/lib) در مسیر بود،
    از همان نقطه به بعد را نگه می‌داریم تا مسیر کوتاه و پروژه‌-محور شود.
    """
    parts = [p for p in chain.split(">") if p]
    if not parts:
        return chain
    for i, seg in enumerate(parts):
        if seg in _ANCHORS or any(
            seg.endswith("/" + a) or seg.endswith("\\" + a) for a in _ANCHORS
        ):
            return ">".join(parts[i:])
        for a in _ANCHORS:
            if seg == a:
                return ">".join(parts[i:])
    return chain


def _normalize_to_chain(path: str) -> str:
    """
    نرمال‌سازی مسیر به جداکننده یکتا '>' و حذف اضافات.
    """
    if not path:
        return ""
    chain = path.replace("\\", ">").replace("/", ">").replace("::", ">")
    chain = re.sub(r">(>)+", ">", chain)
    chain = re.sub(r"^\s*>|>\s*$", "", chain)
    chain = chain.strip()
    chain = _strip_drive_prefix(chain)
    chain = _shorten_to_anchor(chain)
    return chain


def _dedupe_by_tail(chains: List[str]) -> List[str]:
    """
    حذف تکراری با حفظ ترتیب؛ کلید یکتا = حداکثر ۴ سگمنت انتهایی (برای حذف نسخه‌های با/بی‌درایو).
    """
    seen = set()
    out: List[str] = []
    for c in chains:
        parts = [p for p in c.split(">") if p]
        tail_key = tuple(parts[-4:])
        if tail_key in seen:
            continue
        seen.add(tail_key)
        out.append(c)
    return out


def extract_file_lines(error_text: str, lang: str) -> List[Tuple[str, int]]:
    """
    از متن خطا مسیرها و شماره خطوط را استخراج می‌کند.
    پشتیبانی از: Windows (با/بی‌درایو)، UNC، POSIX، MSBuild، Java (paren)، Python traceback.
    """
    if not error_text:
        return []

    results: List[Tuple[str, int]] = []
    for pat in _PATTERNS:
        for m in pat.finditer(error_text):
            try:
                path = m.group(1).strip()
                line = int(m.group(2))
                results.append((path, line))
            except Exception:
                continue
    return results


def normalize_path_chain(path: str) -> str:
    """
    مسیر ورودی را به جداکننده یکتا '>' نرمال می‌کند
    و پیشوند درایو را حذف و (در صورت امکان) به یکی از لنگرهای پروژه کوتاه می‌کند.
    """
    return _normalize_to_chain(path)


def locate_from_error(error_text: str, lang: str) -> Dict[str, List[str]]:
    """
    مکان‌یابی خطا از روی پیام خطا.

    خروجی:
    {
      "heuristic": ["tests>unit>file.py>24", ...],
      "raw_paths": ["C:\\...\\tests\\unit\\file.py:24", ...]
    }
    """
    file_lines = extract_file_lines(error_text, lang)

    raw_paths: List[str] = []
    chains: List[str] = []

    for path, line in file_lines:
        raw_paths.append(f"{path}:{line}")
        chain = _normalize_to_chain(path)
        if chain:
            chains.append(f"{chain}>{line}")

    heuristic = _dedupe_by_tail(chains)

    return {
        "heuristic": heuristic,
        "raw_paths": _dedupe_by_tail(raw_paths),
    }
