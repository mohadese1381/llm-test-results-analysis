import os
import libcst as cst
import networkx as nx
from typing import List
from libcst import parse_module
from libcst.metadata import PositionProvider, MetadataWrapper


def is_test_file(tree: cst.Module) -> bool:
    for node in tree.body:
        if isinstance(node, cst.FunctionDef) and node.name.value.startswith("test_"):
            return True
        if isinstance(node, cst.ClassDef):
            for item in node.body.body:
                if isinstance(item, cst.FunctionDef) and item.name.value.startswith(
                    "test_"
                ):
                    return True
    return False


class FunctionCollector(cst.CSTVisitor):
    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(self, filename: str, is_test_file: bool, graph: nx.DiGraph):
        self.graph = graph
        self.filename = filename
        self.current_class = None
        self.function_stack: List[str] = []
        self.current_function = None
        self.is_test_file = is_test_file

    def visit_ClassDef(self, node: cst.ClassDef):
        self.current_class = node.name.value

    def leave_ClassDef(self, node: cst.ClassDef):
        self.current_class = None

    def visit_FunctionDef(self, node: cst.FunctionDef):
        func_name = node.name.value
        self.function_stack.append(func_name)

        name_parts = [self.filename.replace(os.sep, "/")]
        if self.current_class:
            name_parts.append(self.current_class)
        name_parts += self.function_stack
        func_id = "::".join(name_parts)

        self.current_function = func_id

        pos = self.get_metadata(PositionProvider, node)
        self.graph.add_node(
            func_id,
            type="test" if self.is_test_file else "function",
            file=self.filename,
            start_line=pos.start.line,
            end_line=pos.end.line,
            is_test=self.is_test_file,
        )

        if node.decorators:
            for deco in node.decorators:
                if isinstance(deco.decorator, cst.Attribute):
                    if deco.decorator.attr.value == "parametrize":
                        self.graph.nodes[func_id]["is_parametrized"] = True

    def leave_FunctionDef(self, node: cst.FunctionDef):
        self.function_stack.pop()
        self.current_function = None

    def visit_Call(self, node: cst.Call):
        if not self.current_function:
            return

        callee = None
        if isinstance(node.func, cst.Name):
            callee = node.func.value
        elif isinstance(node.func, cst.Attribute):
            callee = node.func.attr.value

        if callee:
            callee_id = callee
            if not self.graph.has_node(callee_id):
                self.graph.add_node(callee_id, type="external")
            self.graph.add_edge(self.current_function, callee_id)


def extract_python_graph(project_path: str) -> nx.DiGraph:
    graph = nx.DiGraph()

    for root, _, files in os.walk(project_path):
        for file in files:
            if not file.endswith(".py"):
                continue

            file_path = os.path.join(root, file)
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    source = f.read()
                    module = parse_module(source)
            except Exception:
                continue

            wrapper = MetadataWrapper(module)
            test_file = is_test_file(module)
            rel_path = os.path.relpath(file_path, project_path).replace(os.sep, "/")
            visitor = FunctionCollector(
                filename=rel_path, is_test_file=test_file, graph=graph
            )
            wrapper.visit(visitor)

    return graph
