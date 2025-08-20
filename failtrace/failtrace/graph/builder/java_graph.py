import os
from pathlib import Path
import networkx as nx
import javalang

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
_EXCLUDED_FILE_SUFFIXES = (".generated.java",)

_TEST_ANNOTATIONS = {
    "Test",
    "ParameterizedTest",
    "RepeatedTest",
    "org.junit.Test",
    "org.junit.jupiter.api.Test",
    "org.junit.jupiter.params.ParameterizedTest",
    "org.junit.jupiter.api.RepeatedTest",
    "org.junit.jupiter.api.TestFactory",
    "org.testng.annotations.Test",
}


def extract_java_graph(project_path: str) -> nx.DiGraph:
    graph = nx.DiGraph()
    project_dir = Path(project_path)

    for root, dirs, files in os.walk(project_dir):
        dirs[:] = [d for d in dirs if d not in _EXCLUDED_DIRS]

        for file in files:
            if not file.endswith(".java") or file.endswith(_EXCLUDED_FILE_SUFFIXES):
                continue

            file_path = Path(root) / file
            norm = file_path.as_posix()
            if any(f"/{ex}/" in f"/{norm}/" for ex in _EXCLUDED_DIRS):
                continue

            rel_path = file_path.relative_to(project_dir).as_posix()

            try:
                source = file_path.read_text(encoding="utf-8")
                tree = javalang.parse.parse(source)
            except Exception as e:
                print(f"Error parsing {file_path}: {e}")
                continue

            pkg = (tree.package.name + ".") if getattr(tree, "package", None) else ""

            imports = []
            try:
                imports = [
                    imp.path
                    for imp in getattr(tree, "imports", [])
                    if hasattr(imp, "path")
                ]
            except Exception:
                imports = []

            for _, cls in tree.filter(javalang.tree.ClassDeclaration):
                _collect_methods(graph, pkg, rel_path, cls, _TEST_ANNOTATIONS)

            for _, interface in tree.filter(javalang.tree.InterfaceDeclaration):
                _collect_methods(graph, pkg, rel_path, interface, _TEST_ANNOTATIONS)

            for _, method in tree.filter(javalang.tree.MethodDeclaration):
                _collect_edges(graph, pkg, rel_path, tree, method, imports)

    return graph


def _collect_methods(graph, pkg, rel_path, type_node, test_annotations):
    type_name = type_node.name
    for method in type_node.methods:
        method_name = method.name
        method_id = f"{pkg}{rel_path}::{type_name}::{method_name}"

        annos = getattr(method, "annotations", None) or []
        is_test = any(
            (getattr(anno, "name", None) in test_annotations)
            or (
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


def _collect_edges(graph, pkg, rel_path, tree, method, imports):
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

    for _, inv in method.filter(javalang.tree.MethodInvocation):
        callee = inv.member
        matched = False
        for node_id in graph.nodes:
            if node_id.endswith(f"::{callee}"):
                graph.add_edge(caller_id, node_id)
                matched = True
                break
        if matched:
            continue

        ext_key = f"external::{callee}"
        if not graph.has_node(ext_key):
            graph.add_node(ext_key, type="external")
        if "origin" not in graph.nodes[ext_key]:
            graph.nodes[ext_key]["origin"] = {
                "language": "java",
                "package": (
                    tree.package.name if getattr(tree, "package", None) else None
                ),
                "imports": imports,
                "qualifier": getattr(inv, "qualifier", None),
                "symbol": callee,
                "file": rel_path,
            }
        if not graph.has_edge(caller_id, ext_key):
            graph.add_edge(caller_id, ext_key)
