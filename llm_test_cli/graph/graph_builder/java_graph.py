# graph/java_graph.py
import os
from pathlib import Path
import networkx as nx
import javalang

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
        - Skips generated files (*.generated.java).
        - Detects test methods using annotations: @Test, @ParameterizedTest, @RepeatedTest, @TestNG.Test.
        - Supports methods in classes and interfaces.
    """
    graph = nx.DiGraph()
    project_dir = Path(project_path)
    test_annotations = {'Test', 'ParameterizedTest', 'RepeatedTest', 'org.testng.annotations.Test'}

    for root, _, files in os.walk(project_dir):
        for file in files:
            # Skip non-Java and generated files
            if not file.endswith('.java') or file.endswith('.generated.java'):
                continue
            file_path = Path(root) / file
            rel_path = file_path.relative_to(project_dir).as_posix()

            # Read and parse file
            try:
                source = file_path.read_text(encoding='utf-8')
                tree = javalang.parse.parse(source)
            except Exception as e:
                print(f"Error parsing {file_path}: {e}")
                continue

            # Extract package name
            pkg = tree.package.name + '.' if hasattr(tree, 'package') and tree.package else ''

            # First pass: Collect method declarations from classes
            for _, cls in tree.filter(javalang.tree.ClassDeclaration):
                _collect_methods(graph, pkg, rel_path, cls, test_annotations)

            # First pass: Collect method declarations from interfaces
            for _, interface in tree.filter(javalang.tree.InterfaceDeclaration):
                _collect_methods(graph, pkg, rel_path, interface, test_annotations)

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
        is_test = any(
            anno.name in test_annotations or
            (isinstance(anno.name, javalang.tree.MemberReference) and anno.name.qualifier == 'Test')
            for anno in (method.annotations or [])
        )
        start = getattr(method, 'position', None)
        start_line = start.line if start else None
        end_line = None
        if method.body:
            last_stmt = method.body[-1] if isinstance(method.body, list) else method.body
            pos = getattr(last_stmt, 'position', start)
            end_line = pos.line if pos else None

        graph.add_node(
            method_id,
            type='test' if is_test else 'function',
            file=rel_path,
            start_line=start_line,
            end_line=end_line,
            is_test=is_test
        )

def _collect_edges(graph, pkg, rel_path, tree, method):
    """
    For a given MethodDeclaration, add edges from this method to all invoked methods.
    """
    # Build caller ID
    caller_type = None
    for ancestor in tree.types:
        if isinstance(ancestor, (javalang.tree.ClassDeclaration, javalang.tree.InterfaceDeclaration)):
            caller_type = ancestor.name
            break
    caller_name = method.name
    caller_id = f"{pkg}{rel_path}::{caller_type}::{caller_name}" if caller_type else None
    if not caller_id or caller_id not in graph:
        return

    # Add edges for each MethodInvocation
    for _, inv in method.filter(javalang.tree.MethodInvocation):
        callee = inv.member
        # Suffix match to find the right node
        for node_id in graph.nodes:
            if node_id.endswith(f"::{callee}"):
                graph.add_edge(caller_id, node_id)
                break
