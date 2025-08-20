from typing import List, Tuple
import os
import re


def _ensure_python_filepath(path_part: str) -> str:

    if not isinstance(path_part, str) or not path_part.strip():
        return "unknown.py"

    p = path_part.strip().replace("\\", "/")
    if "/" not in p and "." in p:
        p = p.replace(".", "/")

    p = re.sub(r"/+", "/", p).strip("/")

    base = os.path.basename(p)
    if base.endswith(".py"):
        return p

    return f"{p}.py"


def _split_name(raw: str) -> Tuple[str, List[str]]:
    s = (raw or "").strip().replace("\\", "/")

    if "::" in s:
        path_part, func_part = s.split("::", 1)
        extra_parts = [p.strip() for p in func_part.split("::") if p.strip()]
        return path_part.strip(), extra_parts

    if "#" in s:
        path_part, method = s.split("#", 1)
        return path_part.strip(), [method.strip()] if method.strip() else []

    segs = s.rsplit(".", 1)
    if len(segs) == 2 and all(seg.strip() for seg in segs):
        return segs[0].strip(), [segs[1].strip()]

    return s, []


def normalize_test_name(raw_name: str, lang: str) -> str:
    if not raw_name or not isinstance(raw_name, str):
        return raw_name

    lang_lc = (lang or "").lower()
    path_part, extra_parts = _split_name(raw_name)

    path_part = path_part.replace("\\", "/").strip()

    if lang_lc == "python":
        filename = _ensure_python_filepath(path_part)
        parts: List[str] = [filename]
        parts.extend(p for p in extra_parts if p)
        return "::".join(parts)

    lower_path = path_part.lower()
    has_file_java = lower_path.endswith(".java")
    has_file_cs = lower_path.endswith(".cs")

    if has_file_java or has_file_cs:
        stem = os.path.splitext(os.path.basename(path_part))[0] or "Unknown"
        class_name = stem
    else:
        dotted = path_part.replace(".", "/")
        segments = [s for s in re.split(r"/+", dotted) if s]
        ignored = {
            "src",
            "main",
            "test",
            "tests",
            "java",
            "csharp",
            "bin",
            "obj",
            "build",
            "target",
        }
        core = [s for s in segments if s.lower() not in ignored]
        base = core[-1] if core else (segments[-1] if segments else "Unknown")
        class_name = base or "Unknown"

    if lang_lc == "java":
        ext = ".java"
    elif lang_lc == "csharp":
        ext = ".cs"
    else:
        ext = ""

    filename = f"{class_name}{ext}"

    parts: List[str] = [filename]
    if extra_parts:
        parts.append(class_name)
    parts.extend(p for p in extra_parts if p)

    return "::".join(parts)
