import os
import json
import ast
import re
from pathlib import Path
from typing import Dict, Tuple, Set, List, Optional

# نیاز به نصب javalang برای جاوا (اختیاری؛ بدون آن فقط پایتون و سی‌شارپ کار می‌کنند)
try:
    import javalang
except ImportError:
    javalang = None
    print("[!] javalang not installed. Java parsing will be limited to Python/C#.")


# =========================
# Helpers
# =========================


def _read_text(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        print(f"[!] Cannot read {path}: {e}")
        return None


def _find_csharp_signature_index(lines: List[str], start_idx: int) -> int:
    """از start_idx جلو می‌رویم تا به امضای متد برسیم"""
    i = start_idx
    while i < len(lines):
        s = lines[i].strip()
        if s.startswith("["):
            i += 1
            continue
        if s.startswith(("public", "private", "protected", "internal", "async")):
            return i
        i += 1
    return start_idx


def _find_attribute_block_start(lines: List[str], sig_idx: int) -> int:
    """از خط امضا به عقب برمی‌گردیم تا ابتدای بلاک attribute پیدا شود"""
    j = sig_idx - 1
    while j >= 0 and lines[j].lstrip().startswith("["):
        j -= 1
    return j + 1


def _brace_slice(lines: List[str], start_idx: int) -> str:
    """
    کد را از ابتدای بلاک attribute (در صورت وجود) تا انتهای بدنه/امضا برمی‌گرداند.
    بدنه از امضای متد دنبال می‌شود؛ ولی attributeهای قبل از امضا هم در خروجی هستند.
    """
    if not lines:
        return ""

    sig_idx = _find_csharp_signature_index(lines, start_idx)
    attr_start = _find_attribute_block_start(lines, sig_idx)

    buf: List[str] = []
    depth = 0
    started = False

    i = sig_idx
    while i < len(lines):
        line = lines[i]
        buf.append(line)

        st = line.strip()
        if "=>" in line:  # expression-bodied
            break
        if st.endswith(";"):  # امضای اینترفیس یا متد بدون بدنه
            break

        if "{" in line:
            depth += line.count("{")
            started = True
        if "}" in line:
            depth -= line.count("}")
            if started and depth <= 0:
                break

        i += 1

    prefix = "".join(lines[attr_start:sig_idx])
    return (prefix + "".join(buf)).rstrip()


def _split_test_qualified_name(raw: str) -> Tuple[str, str]:
    s = (raw or "").strip()

    if "::" in s:
        parts = [p for p in s.split("::") if p]
        if len(parts) >= 2:
            return parts[-2], parts[-1]

    if "#" in s:
        left, right = s.rsplit("#", 1)
        cls = left.split(".")[-1]
        return cls, right

    parts = [p for p in s.split(".") if p]
    if len(parts) >= 2:
        return parts[-2], parts[-1]

    return "UnknownClass", s


def _find_candidate_files(project_path: str, filename: str) -> List[str]:
    result = []
    for root, _, files in os.walk(project_path):
        for f in files:
            if f.lower() == filename.lower():
                result.append(os.path.join(root, f))
    return result


def _find_by_relpath_suffix(project_path: str, relpath_like: str) -> Optional[str]:
    if not relpath_like:
        return None
    target_suffix = relpath_like.replace("\\", "/").lower().lstrip("./")
    best: Optional[str] = None
    best_len = 0
    for root, _, files in os.walk(project_path):
        for f in files:
            cand = os.path.join(root, f)
            norm = cand.replace("\\", "/").lower()
            if norm.endswith(target_suffix) and len(target_suffix) > best_len:
                best = cand
                best_len = len(target_suffix)
    return best


# =========================
# Python extractor
# =========================


class _PyClassFuncVisitor(ast.NodeVisitor):
    def __init__(self, lines: List[str]):
        self.lines = lines
        self.stack: List[str] = []
        self.out: Dict[str, Dict[str, str]] = {}

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        class_name = self.stack[-1] if self.stack else None
        full = f"{class_name}::{node.name}" if class_name else node.name
        doc = ast.get_docstring(node) or ""
        start = node.lineno
        end = getattr(node, "end_lineno", None)
        code = (
            "\n".join(self.lines[start - 1 : end])
            if end
            else "\n".join(self.lines[start - 1 :])
        )
        self.out[full] = {"line": start, "docstring": doc.strip(), "code": code.strip()}

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.visit_FunctionDef(node)


def extract_python_functions(file_path: str) -> Dict[str, Dict[str, str]]:
    text = _read_text(file_path)
    if text is None:
        return {}
    try:
        tree = ast.parse(text)
    except Exception as e:
        print(f"[!] Python parse error in {file_path}: {e}")
        return {}
    visitor = _PyClassFuncVisitor(text.splitlines())
    visitor.visit(tree)
    return visitor.out


# =========================
# Java extractor
# =========================
def extract_java_functions(file_path: str) -> Dict[str, Dict[str, str]]:
    """
    نسخه‌ی پایدار: به‌جای tree.filter روی tuple، برای هر نوع جداگانه فیلتر می‌زنیم
    تا در همه‌ی نسخه‌های javalang درست کار کند.
    """
    out: Dict[str, Dict[str, str]] = {}
    if javalang is None:
        return out

    text = _read_text(file_path)
    if text is None:
        return out

    try:
        tree = javalang.parse.parse(text)
    except Exception as e:
        print(f"[!] Java parse error in {file_path}: {e}")
        return out

    lines = text.splitlines()

    # --- کلاس‌ها ---
    for _, cls in tree.filter(javalang.tree.ClassDeclaration):
        cls_name = cls.name

        # متدها
        for m in getattr(cls, "methods", []):
            start = m.position.line if m.position else 1
            idx = max(0, start - 1)
            code = _brace_slice(lines, idx)
            full = f"{cls_name}::{m.name}"
            out[full] = {"line": start, "docstring": "", "code": code}

        # سازنده‌ها
        for ctor in getattr(cls, "constructors", []):
            start = ctor.position.line if ctor.position else 1
            idx = max(0, start - 1)
            code = _brace_slice(lines, idx)
            full = f"{cls_name}::{cls_name}"
            out[full] = {"line": start, "docstring": "", "code": code}

    # --- اینترفیس‌ها ---
    for _, interface in tree.filter(javalang.tree.InterfaceDeclaration):
        cls_name = interface.name
        for m in getattr(interface, "methods", []):
            start = m.position.line if m.position else 1
            idx = max(0, start - 1)
            code = _brace_slice(lines, idx)
            full = f"{cls_name}::{m.name}"
            out[full] = {"line": start, "docstring": "", "code": code}

    # در صورت نیاز می‌تونی این لاگ رو نگه داری:
    # print(f"[DEBUG] Java extracted {len(out)} items from {file_path}")
    return out


# =========================
# C# extractor
# =========================

_CS_NAMESPACE_RE = re.compile(r"\bnamespace\s+([A-Za-z_][\w\.]*)")
_CS_TYPE_RE = re.compile(r"\b(class|struct|record|interface)\s+([A-Za-z_]\w*)")
_CS_METHOD_RE = re.compile(
    r"""(?x)
    ^\s*
    (?:\[[^\]]*\]\s*)*
    (?:(?:public|private|protected|internal)\s+
       (?:static|sealed|abstract|virtual|override|async|extern|unsafe|readonly|partial\s+)*\s*
    )?
    [A-Za-z_][\w<>\[\]\?,\s\.]*
    \s+
    (?P<name>[A-Za-z_][\w\.]*)
    \s*\(
    [^)]*
    \)
    \s*
    (?P<body>\{|=>|;)
    """,
    re.MULTILINE,
)
_CS_CTOR_RE = re.compile(
    r"""(?x)
    ^\s*
    (?:\[[^\]]*\]\s*)*
    (?:(?:public|private|protected|internal)\s+)?
    (?P<name>[A-Za-z_]\w*)
    \s*\(
    [^)]*
    \)
    \s*
    (?P<body>\{|=>|;)? 
    """,
    re.MULTILINE,
)


def extract_csharp_functions(file_path: str) -> Dict[str, Dict[str, str]]:
    text = _read_text(file_path)
    if text is None:
        return {}

    lines = text.splitlines()

    type_positions: List[Tuple[int, str]] = []
    for tm in _CS_TYPE_RE.finditer(text):
        type_name = tm.group(2)
        type_positions.append((tm.start(), type_name))
    type_positions.sort()

    def _owner_type_at(pos: int) -> Optional[str]:
        lo, hi = 0, len(type_positions) - 1
        best = None
        while lo <= hi:
            mid = (lo + hi) // 2
            if type_positions[mid][0] <= pos:
                best = type_positions[mid][1]
                lo = mid + 1
            else:
                hi = mid - 1
        return best

    out: Dict[str, Dict[str, str]] = {}

    method_pattern = re.compile(
        _CS_METHOD_RE.pattern, re.MULTILINE | re.DOTALL | re.VERBOSE
    )
    for mm in method_pattern.finditer(text):
        mname_full = mm.group("name")
        mname = mname_full.split(".")[-1]
        owner = _owner_type_at(mm.start()) or ""
        full = f"{owner}::{mname}" if owner else mname
        start_line = text.count("\n", 0, mm.start()) + 1
        code = _brace_slice(lines, max(0, start_line - 1))
        out[full] = {"line": start_line, "docstring": "", "code": code}

    ctor_pattern = re.compile(
        _CS_CTOR_RE.pattern, re.MULTILINE | re.DOTALL | re.VERBOSE
    )
    for cm in ctor_pattern.finditer(text):
        owner = _owner_type_at(cm.start())
        if not owner:
            continue
        if cm.group("name") != owner:
            continue
        start_line = text.count("\n", 0, cm.start()) + 1
        code = _brace_slice(lines, max(0, start_line - 1))
        full = f"{owner}::{owner}"
        out[full] = {"line": start_line, "docstring": "", "code": code}

    return out


# =========================
# Dispatch
# =========================

LANGUAGE_EXTRACTORS = {
    ".py": extract_python_functions,
    ".java": extract_java_functions,
    ".cs": extract_csharp_functions,
}


def extract_functions_from_file(file_path: str) -> Dict[str, Dict[str, str]]:
    ext = os.path.splitext(file_path)[1].lower()
    extractor = LANGUAGE_EXTRACTORS.get(ext)
    if not extractor:
        print(f"[!] Unsupported file type: {file_path}")
        return {}
    try:
        return extractor(file_path)
    except Exception as e:
        print(f"[!] Failed to extract from {file_path}: {e}")
        return {}


# =========================
# Critical functions + Fallback
# =========================


def _infer_lang_from_path(project_path: str) -> str:
    exts = set()
    for root, _, files in os.walk(project_path):
        for f in files:
            exts.add(os.path.splitext(f)[1].lower())
    if ".cs" in exts:
        return "csharp"
    if ".java" in exts:
        return "java"
    if ".py" in exts:
        return "python"
    return "unknown"


def _strip_params(name: str) -> str:
    import re

    return re.sub(r"(\[.*?\]|\(.*?\)|\{.*?\})$", "", name).strip()


def _guess_targets_from_failed_tests(summary: Dict, lang: str) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    failed = summary.get("failed_detail") or []

    for item in failed:
        raw = (item.get("name") or "").strip()
        if not raw:
            continue

        cls, meth = _split_test_qualified_name(raw)
        meth = _strip_params(meth)

        if lang == "csharp":
            simple_type = cls.split(".")[-1].split("+")[0] if cls else ""
            func_name = f"{simple_type or cls}::{meth}" if meth else ""
            file_guess = f"{simple_type or 'Unknown'}.cs"
            if func_name and file_guess:
                out.append((func_name, file_guess))

        elif lang == "java":
            simple_type = cls.split(".")[-1] if cls else ""
            func_name = f"{simple_type or cls}::{meth}" if meth else ""
            file_guess = f"{cls.replace('.', '/')}.java" if cls else ""
            if func_name and file_guess:
                out.append((func_name, file_guess))

        elif lang == "python":
            if "::" in raw:
                parts = raw.split("::")
                file_guess = parts[0].replace("\\", "/")
                func_guess = (
                    "::".join(_strip_params(p) for p in parts[1:])
                    if len(parts) > 1
                    else ""
                )
                if file_guess.endswith(".py") and func_guess:
                    out.append((func_guess, file_guess))
            else:
                dots = raw.split(".")
                if len(dots) >= 2:
                    module = ".".join(dots[:-1])
                    func = _strip_params(dots[-1])
                    file_guess = module.replace(".", "/") + ".py"
                    if func and file_guess.endswith(".py"):
                        out.append((func, file_guess))

    return out


def extract_critical_functions(
    project_path: str,
    prompt_file: str,
    output_file: str = "output/function_summaries.json",
) -> None:
    project_root = Path(project_path)

    with open(prompt_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    used_functions: Set[Tuple[str, str]] = set()

    crit = data.get("critical_paths") or {}
    for _test_name, paths in crit.items():
        for direction in ("upstream", "downstream"):
            for path in paths.get(direction, []) or []:
                for node in path:
                    if (
                        not node.get("is_test")
                        and node.get("file")
                        and node.get("node")
                    ):
                        used_functions.add((node["node"], node["file"]))

    if not used_functions:
        lang = (_infer_lang_from_path(project_path) or "").lower()
        summary = data.get("summary") or {}
        guesses = _guess_targets_from_failed_tests(summary, lang)
        for func_name, file_name in guesses:
            used_functions.add((func_name, file_name))

    result: Dict[str, Dict[str, str]] = {}

    for func_name, rel_file in used_functions:
        rel_file_norm = rel_file.replace("\\", "/")
        abs_path = project_root.joinpath(rel_file_norm).resolve()

        if not abs_path.is_file():
            by_suffix = _find_by_relpath_suffix(str(project_root), rel_file_norm)
            if by_suffix:
                abs_path = Path(by_suffix).resolve()
                rel_file_norm = os.path.relpath(
                    str(abs_path), str(project_root)
                ).replace("\\", "/")
            else:
                candidates = _find_candidate_files(
                    str(project_root), os.path.basename(rel_file_norm)
                )
                if not candidates:
                    continue
                abs_path = Path(candidates[0]).resolve()
                rel_file_norm = os.path.relpath(
                    str(abs_path), str(project_root)
                ).replace("\\", "/")

        extracted = extract_functions_from_file(str(abs_path))
        if not extracted:
            continue

        matched_key: Optional[str] = None
        for key in extracted.keys():
            if (
                key == func_name
                or key.endswith(f"::{func_name}")
                or func_name.endswith(f"::{key}")
            ):
                matched_key = key
                break

        if matched_key is None:
            target_method = func_name.split("::")[-1]
            for key in extracted.keys():
                if key.split("::")[-1] == target_method:
                    matched_key = key
                    break

        if matched_key:
            result_key = f"{rel_file_norm}::{matched_key}"
            result[result_key] = {
                "file": rel_file_norm,
                "line": extracted[matched_key]["line"],
                "docstring": extracted[matched_key]["docstring"],
                "code": extracted[matched_key]["code"],
            }

    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"[✓] Extracted {len(result)} function(s) -> {output_file}")
