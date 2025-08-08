# --- file: utils/normalize.py ---
from typing import List


def normalize_test_name(raw_name: str, lang: str) -> str:
    """
    Normalize test names so they match graph node-IDs.

    • Python  : test_file.TestClass::test_method → test_file.py::TestClass::test_method
    • Java    : com.acme.ClassTest#method       → ClassTest.java::ClassTest::method
    • C#      : Namespace.Class.Method          → Class.cs::Class::Method
    """
    if not raw_name or not isinstance(raw_name, str):
        return raw_name

    # 1) unify slashes, trim
    name = raw_name.strip().replace("\\", "/")

    # 2) split path-part vs method-part
    if "::" in name:  # e.g. pytest / xUnit
        path_part, func_part = name.split("::", 1)
        extra_parts: List[str] = func_part.split("::")
    elif "#" in name:  # JUnit5
        path_part, method = name.split("#", 1)
        extra_parts = [method]
    else:  # Java/C#: package.Class.method
        segs = name.rsplit(".", 1)
        path_part, extra_parts = (segs[0], [segs[1]]) if len(segs) == 2 else (name, [])

    # 3) strip unimportant folders
    raw_segs = path_part.replace(".", "/").split("/")
    ignored = {"tests", "test", "src", "main", "java", "python", "csharp"}
    core_segs = [s for s in raw_segs if s.lower() not in ignored]
    base = core_segs[-1] if core_segs else "unknown"

    # 4) choose file extension
    ext_map = {"python": ".py", "java": ".java", "csharp": ".cs"}
    ext = ext_map.get(lang.lower(), "")

    # ── language-specific filename ──────────────────────────────────────────────
    if lang.lower() == "python":
        file_base = path_part.split(".")[0]  # e.g. test_math_utils
        filename = file_base + ".py"
        class_name = path_part.split(".")[-1] if "." in path_part else None
    else:  # Java / C#
        filename = base + ext
        class_name = base  # keep class for later

    # 5) assemble parts with '::'
    parts: List[str] = [filename]

    if lang.lower() == "python" and class_name:
        parts.append(class_name)  # add TestClass
    elif lang.lower() in {"java", "csharp"} and extra_parts:
        parts.append(class_name)  # add Class for Java/C#

    parts.extend(extra_parts)  # finally method name(s)

    return "::".join(filter(None, parts))
