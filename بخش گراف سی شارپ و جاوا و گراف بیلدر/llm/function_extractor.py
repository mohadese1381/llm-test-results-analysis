import os
import json
import ast
from typing import Dict, Tuple, Set


def extract_functions_from_file(file_path: str) -> Dict[str, Dict[str, str]]:
    if not os.path.isfile(file_path):
        return {}

    functions = {}

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            source_code = f.read()
        tree = ast.parse(source_code)
        lines = source_code.splitlines()

        class_stack = []

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                name = node.name
                parent_class = None
                for parent in ast.iter_child_nodes(tree):
                    if isinstance(
                        parent, ast.ClassDef
                    ) and node in ast.iter_child_nodes(parent):
                        parent_class = parent.name
                        break

                full_name = f"{parent_class}::{name}" if parent_class else name

                docstring = ast.get_docstring(node) or ""
                start = node.lineno
                end = getattr(node, "end_lineno", None)
                code = "\n".join(lines[start - 1 : end]) if end else ""
                functions[full_name] = {
                    "line": start,
                    "docstring": docstring.strip(),
                    "code": code.strip(),
                }

    except Exception as e:
        print(f"[!] Failed to extract from {file_path}: {e}")

    return functions


def extract_critical_functions(
    project_path: str,
    prompt_file: str,
    output_file: str = "output/function_summaries.json"
) -> None:
    """
    استخراج کد توابع مسیر بحرانی از فایل structured prompt و ذخیره‌سازی برای LLM.
    """

    with open(prompt_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    used_functions: Set[Tuple[str, str]] = set()

    # جمع‌آوری توابع موردنیاز از مسیرهای بحرانی
    for test_name, paths in data.get("critical_paths", {}).items():
        for direction in ("upstream", "downstream"):
            for path in paths.get(direction, []):
                for node in path:
                    if not node.get("is_test") and node.get("file") and node.get("node"):
                        used_functions.add((node["node"], node["file"]))

    result = {}

    for func_name, rel_file in used_functions:
        abs_path = os.path.join(project_path, rel_file)
        if not os.path.exists(abs_path):
            continue

        extracted = extract_functions_from_file(abs_path)

        matched_key = None
        for key in extracted.keys():
            if key == func_name or key.endswith(f"::{func_name}") or func_name.endswith(f"::{key}"):
                matched_key = key
                break

        if matched_key:
            key_out = f"{rel_file}::{matched_key}"
            result[key_out] = {
                "file": rel_file,
                "line": extracted[matched_key]["line"],
                "docstring": extracted[matched_key]["docstring"],
                "code": extracted[matched_key]["code"]
            }

    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
        # Debugging output
    """ print(f"[✓] Extracted {len(result)} function(s) to: {output_file}") """