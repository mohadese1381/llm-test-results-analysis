# --- file: graph/java_graph.py ---
import os
from pathlib import Path
import networkx as nx
import javalang

# ✅ دایرکتوری‌هایی که نباید وارد گراف شوند (خروجی بیلد/ابزار/IDE/کش/وابستگی‌ها)
_EXCLUDED_DIRS = {
    "target",
    "build",
    "out",
    "bin",
    ".gradle",
    ".idea",
    ".mvn",
    ".git",
    ".github",
    "generated",
    "generated-sources",
    "generated-test-sources",
}

# ✅ الگوهای رایج برای فایل/دایرکتوری‌های جنریت‌شده
_EXCLUDED_FILE_SUFFIXES = (".generated.java",)

# ✅ پوشش کامل‌تر annotationهای تست (JUnit4/JUnit5/TestNG)
_TEST_ANNOTATIONS = {
    # generic / short
    "Test",
    "ParameterizedTest",
    "RepeatedTest",
    # JUnit 4
    "org.junit.Test",
    # JUnit 5
    "org.junit.jupiter.api.Test",
    "org.junit.jupiter.params.ParameterizedTest",
    "org.junit.jupiter.api.RepeatedTest",
    "org.junit.jupiter.api.TestFactory",
    # TestNG
    "org.testng.annotations.Test",
}


def extract_java_graph(project_path: str) -> nx.DiGraph:
    """
    Build a directed graph of method dependencies in a Java project.

    Parameters:
        project_path (str): Path to the root directory of the Java project.

    Returns:
        nx.DiGraph: A directed graph where:
            - Nodes represent methods in format: "<package>::<relpath>::<class/interface>::<method>"
            - Edges represent method calls (MethodInvocation)
            - Node attributes: type ('test' or 'function'), file, start_line, end_line, is_test

    Notes:
        - Skips generated files (*.generated.java) and common build/output/vendor dirs.
        - Detects test methods using annotations: JUnit4/JUnit5/TestNG.
        - Supports methods in classes and interfaces.
    """
    graph = nx.DiGraph()
    project_dir = Path(project_path)

    for root, dirs, files in os.walk(project_dir):
        # ✅ prune دایرکتوری‌های ناخواسته قبل از ورود
        dirs[:] = [d for d in dirs if d not in _EXCLUDED_DIRS]

        for file in files:
            # Skip non-Java and explicit generated files
            if not file.endswith(".java") or file.endswith(_EXCLUDED_FILE_SUFFIXES):
                continue

            file_path = Path(root) / file
            # ✅ ایمنی مضاعف: اگر مسیر شامل فولدرهای ممنوعه بود، رد کن
            norm = file_path.as_posix()
            if any(f"/{ex}/" in f"/{norm}/" for ex in _EXCLUDED_DIRS):
                continue

            rel_path = file_path.relative_to(project_dir).as_posix()

            # Read and parse file
            try:
                source = file_path.read_text(encoding="utf-8")
                tree = javalang.parse.parse(source)
            except Exception as e:
                print(f"Error parsing {file_path}: {e}")
                continue

            # Extract package name
            pkg = (tree.package.name + ".") if getattr(tree, "package", None) else ""

            # First pass: Collect method declarations from classes
            for _, cls in tree.filter(javalang.tree.ClassDeclaration):
                _collect_methods(graph, pkg, rel_path, cls, _TEST_ANNOTATIONS)

            # First pass: Collect method declarations from interfaces
            for _, interface in tree.filter(javalang.tree.InterfaceDeclaration):
                _collect_methods(graph, pkg, rel_path, interface, _TEST_ANNOTATIONS)

            # Second pass: Find method calls
            for _, method in tree.filter(javalang.tree.MethodDeclaration):
                _collect_edges(graph, pkg, rel_path, tree, method)

    return graph


def _collect_methods(graph, pkg, rel_path, type_node, test_annotations):
    """
    Add all methods of a ClassDeclaration or InterfaceDeclaration node as graph nodes.
    """
    type_name = type_node.name
    for method in type_node.methods:
        method_name = method.name
        method_id = f"{pkg}{rel_path}::{type_name}::{method_name}"

        # ✅ robust annotation check (covers qualified names and short names)
        annos = getattr(method, "annotations", None) or []
        is_test = any(
            (
                # annotation used as simple name
                getattr(anno, "name", None)
                in test_annotations
            )
            or (
                # qualified MemberReference: e.g., org.junit.jupiter.api.Test
                hasattr(anno, "name")
                and hasattr(anno.name, "qualifier")
                and f"{anno.name.qualifier}.{anno.name.member}" in test_annotations
            )
            for anno in annos
        )

        start = getattr(method, "position", None)
        start_line = start.line if start else None
        end_line = None
        if method.body:
            last_stmt = (
                method.body[-1] if isinstance(method.body, list) else method.body
            )
            pos = getattr(last_stmt, "position", start)
            end_line = pos.line if pos else None

        graph.add_node(
            method_id,
            type="test" if is_test else "function",
            file=rel_path,
            start_line=start_line,
            end_line=end_line,
            is_test=is_test,
        )


def _collect_edges(graph, pkg, rel_path, tree, method):
    """
    For a given MethodDeclaration, add edges from this method to all invoked methods.
    """
    # Build caller ID
    caller_type = None
    for ancestor in tree.types:
        if isinstance(
            ancestor,
            (javalang.tree.ClassDeclaration, javalang.tree.InterfaceDeclaration),
        ):
            caller_type = ancestor.name
            break

    caller_name = method.name
    caller_id = (
        f"{pkg}{rel_path}::{caller_type}::{caller_name}" if caller_type else None
    )
    if not caller_id or caller_id not in graph:
        return

    # Add edges for each MethodInvocation
    for _, inv in method.filter(javalang.tree.MethodInvocation):
        callee = inv.member
        # Suffix match to find the right node: ::<method>
        for node_id in graph.nodes:
            if node_id.endswith(f"::{callee}"):
                graph.add_edge(caller_id, node_id)
                break
