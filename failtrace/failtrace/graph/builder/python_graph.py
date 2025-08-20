import os
import libcst as cst
import networkx as nx
from typing import List, Dict, Optional
from libcst import parse_module
from libcst.metadata import PositionProvider, MetadataWrapper

_EXCLUDED_DIRS = {
    ".venv",
    "venv",
    "env",
    "site-packages",
    "__pycache__",
    ".tox",
    ".pytest_cache",
    "build",
    "dist",
}

_BUILTIN_DENYLIST = {
    "len",
    "str",
    "dict",
    "object",
    "print",
    "isinstance",
    "TypeError",
    "KeyError",
    "ValueError",
    "Exception",
    "parametrize",
    "xfail",
    "raises",
    "fixture",
    "skip",
    "getLogger",
    "info",
    "debug",
    "critical",
    "level",
    "remove",
    "replace",
    "add",
    "add_marker",
    "json",
    "get",
    "Iterator",
    "build",
    "datetime",
    "items",
    "assert_called_once",
    "assert_called_with",
    "patch",
    "spy",
    "configure",
}


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
        self.filename = filename.replace(os.sep, "/")
        self.current_class: Optional[str] = None
        self.function_stack: List[str] = []
        self.current_function: Optional[str] = None
        self.is_test_file = is_test_file

        self.imports: Dict[str, str] = {}
        self.local_var_types_stack: List[Dict[str, str]] = []

    def _node_id(self, parts: List[str]) -> str:
        return "::".join(parts)

    def _resolve_internal_targets_by_suffix(self, callee: str) -> List[str]:
        if not callee:
            return []
        suf = f"::{callee}"
        return [
            nid
            for nid, data in self.graph.nodes(data=True)
            if data.get("type") in {"function", "test"} and nid.endswith(suf)
        ]

    def _attr_chain(self, expr: cst.CSTNode) -> List[str]:
        out: List[str] = []

        def walk(n: cst.CSTNode):
            if isinstance(n, cst.Name):
                out.append(n.value)
            elif isinstance(n, cst.Attribute):
                walk(n.value)
                out.append(n.attr.value)
            elif isinstance(n, cst.Call):
                walk(n.func)

        walk(expr)
        return out

    def _qualify_first(self, chain: List[str]) -> List[str]:
        if not chain:
            return chain
        head = chain[0]
        fq = self.imports.get(head)
        if not fq:
            return chain
        return fq.split(".") + chain[1:]

    def _prefer_candidates(self, candidates: List[str]) -> List[str]:
        same, other, seen, out = [], [], set(), []
        for nid in candidates:
            data = self.graph.nodes[nid]
            (
                same
                if (data.get("file") or "").replace("\\", "/") == self.filename
                else other
            ).append(nid)
        for x in same + other:
            if x not in seen:
                seen.add(x)
                out.append(x)
        return out

    def _match_candidates(
        self, chain: List[str], var_types: Dict[str, str]
    ) -> List[str]:
        if not chain:
            return []
        method = chain[-1]
        class_name = chain[-2] if len(chain) >= 2 else None
        first = chain[0]
        cands: List[str] = []

        if len(chain) >= 2 and first in var_types:
            hinted = var_types[first]
            cands += [
                nid
                for nid, data in self.graph.nodes(data=True)
                if data.get("type") in {"function", "test"}
                and nid.endswith(f"::{hinted}::{method}")
            ]
        if class_name:
            cands += [
                nid
                for nid, data in self.graph.nodes(data=True)
                if data.get("type") in {"function", "test"}
                and nid.endswith(f"::{class_name}::{method}")
            ]
        if not cands:
            cands = self._resolve_internal_targets_by_suffix(method)
        return self._prefer_candidates(cands)

    def visit_Import(self, node: cst.Import) -> None:
        for alias in node.names:
            name = alias.name
            asname = alias.asname.name.value if alias.asname else None
            fq = ".".join(self._attr_chain(name))
            self.imports[asname or fq.split(".")[-1]] = fq

    def visit_ImportFrom(self, node: cst.ImportFrom) -> None:
        if node.module is None:
            return
        mod = ".".join(self._attr_chain(node.module))
        for alias in node.names:
            if isinstance(alias, cst.ImportAlias):
                tail = ".".join(self._attr_chain(alias.name))
                fq = f"{mod}.{tail}" if tail else mod
                self.imports[(alias.asname.name.value if alias.asname else tail)] = fq

    def visit_Assign(self, node: cst.Assign) -> None:
        if not self.current_function or not self.local_var_types_stack:
            return
        try:
            names: List[str] = []
            for t in node.targets:
                if isinstance(t.target, cst.Name):
                    names.append(t.target.value)
            if not names:
                return
            if isinstance(node.value, cst.Call):
                chain = self._qualify_first(self._attr_chain(node.value.func))
                if chain:
                    cls = chain[-1]
                    for var in names:
                        self.local_var_types_stack[-1][var] = cls
        except Exception:
            pass

    def visit_ClassDef(self, node: cst.ClassDef):
        self.current_class = node.name.value

    def leave_ClassDef(self, node: cst.ClassDef):
        self.current_class = None

    def visit_FunctionDef(self, node: cst.FunctionDef):
        func_name = node.name.value
        self.function_stack.append(func_name)
        parts = (
            [self.filename]
            + ([self.current_class] if self.current_class else [])
            + self.function_stack
        )
        func_id = self._node_id(parts)
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
                d = deco.decorator
                if isinstance(d, cst.Attribute) and d.attr.value == "parametrize":
                    self.graph.nodes[func_id]["is_parametrized"] = True

        self.local_var_types_stack.append({})

    def leave_FunctionDef(self, node: cst.FunctionDef):
        self.function_stack.pop()
        self.current_function = None
        if self.local_var_types_stack:
            self.local_var_types_stack.pop()

    def visit_Call(self, node: cst.Call):
        if not self.current_function:
            return
        chain = self._qualify_first(self._attr_chain(node.func))
        if not chain:
            return

        var_types = self.local_var_types_stack[-1] if self.local_var_types_stack else {}
        candidates = self._match_candidates(chain, var_types)
        if candidates:
            for tgt in candidates:
                if tgt == self.current_function:
                    continue
                if not self.graph.has_edge(self.current_function, tgt):
                    self.graph.add_edge(self.current_function, tgt)
            return

        callee_id = chain[-1]
        if callee_id in _BUILTIN_DENYLIST:
            return

        if not self.graph.has_node(callee_id):
            self.graph.add_node(callee_id, type="external")
        if "origin" not in self.graph.nodes[callee_id]:
            head = chain[0]
            origin_module = self.imports.get(head)
            self.graph.nodes[callee_id]["origin"] = {
                "language": "python",
                "module": origin_module,
                "symbol": ".".join(chain),
                "file": self.filename,
            }
        if not self.graph.has_edge(self.current_function, callee_id):
            self.graph.add_edge(self.current_function, callee_id)


def extract_python_graph(project_path: str) -> nx.DiGraph:
    graph = nx.DiGraph()
    for root, dirs, files in os.walk(project_path):
        dirs[:] = [d for d in dirs if d not in _EXCLUDED_DIRS]
        for file in files:
            if not file.endswith(".py"):
                continue
            file_path = os.path.join(root, file)
            norm_path = file_path.replace("\\", "/")
            if any(f"/{ex}/" in f"/{norm_path}/" for ex in _EXCLUDED_DIRS):
                continue
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
