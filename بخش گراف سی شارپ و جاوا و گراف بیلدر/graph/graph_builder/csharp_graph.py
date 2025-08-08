from __future__ import annotations
import os
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
import networkx as nx
from tree_sitter import Language, Parser
import xml.etree.ElementTree as ET
import logging

# ---------------------------------------------------------------------------
# Initialization (API ≥0.25)
# ---------------------------------------------------------------------------
try:
    from tree_sitter_c_sharp import language as _cs_capsule

    CSHARP_LANG = Language(_cs_capsule())
except ImportError:
    from tree_sitter_languages import get_language  # type: ignore

    CSHARP_LANG = get_language("c_sharp")
PARSER = Parser(CSHARP_LANG)

# ---------------------------------------------------------------------------
# Configuration & Logging
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Test attributes (NUnit/MSTest/xUnit)
# ---------------------------------------------------------------------------
TEST_ATTRS = {
    "Test",
    "TestMethod",
    "Fact",
    "Theory",
    "TestCase",
    "TestCaseSource",
    "ParameterizedTest",
    "Ignore",
    "TestClass",
    "TestFixture",
    "DataTestMethod",
}


# ---------------------------------------------------------------------------
# Helper: AST walk, text extraction
# ---------------------------------------------------------------------------
def _walk(node):
    cursor = node.walk()
    reached = False
    while not reached:
        yield cursor.node
        if cursor.goto_first_child():
            continue
        if cursor.goto_next_sibling():
            continue
        while True:
            if not cursor.goto_parent():
                reached = True
                break
            if cursor.goto_next_sibling():
                break


def _text(src: bytes, node) -> str:
    return (
        src[node.start_byte : node.end_byte].decode("utf-8", "ignore") if node else ""
    )


def _first(node, typ: str):
    for i in range(node.child_count):
        ch = node.child(i)
        if ch.type == typ:
            return ch
    return None


# ---------------------------------------------------------------------------
# Extractors: namespace, decl, type, name, test, params, return, async, args
# ---------------------------------------------------------------------------
def _namespace(root, src: bytes) -> str:
    for n in _walk(root):
        if n.type == "namespace_declaration":
            nm = n.child_by_field_name("name")
            return _text(src, nm).strip() if nm else "<global>"
    return "<global>"


def _decl_name(node, src: bytes) -> Optional[str]:
    nm = node.child_by_field_name("name") or _first(node, "identifier")
    return _text(src, nm).strip() if nm else None


def _enclosing_type(node, src: bytes) -> Optional[str]:
    cur = node.parent
    while cur:
        if cur.type in (
            "class_declaration",
            "struct_declaration",
            "interface_declaration",
            "record_declaration",
        ):
            return _decl_name(cur, src)
        cur = cur.parent
    return None


def _method_name(node, src: bytes) -> Optional[str]:
    nm = node.child_by_field_name("name") or _first(node, "identifier")
    return _text(src, nm).strip() if nm else None


def _is_test(node, src: bytes) -> bool:
    # Detect test via attributes or naming
    for i in range(node.child_count):
        ch = node.child(i)
        if ch.type == "attribute_list":
            for j in range(ch.child_count):
                attr = ch.child(j)
                if attr.type == "attribute":
                    name = attr.child_by_field_name("name")
                    if name and _text(src, name).split(".")[-1] in TEST_ATTRS:
                        return True
    nm = _method_name(node, src)
    return bool(nm and nm.lower().startswith("test"))


def _param_count(node) -> int:
    pl = node.child_by_field_name("parameter_list") or _first(node, "parameter_list")
    if not pl:
        return 0
    return sum(1 for ch in pl.children if ch.type == "parameter")


def _arg_count(node) -> int:
    al = node.child_by_field_name("argument_list") or _first(node, "argument_list")
    if not al:
        return 0
    return sum(1 for ch in al.children if ch.type == "argument")


def _return_type(node, src: bytes) -> str:
    if node.type == "constructor_declaration":
        return "void"
    t = (
        node.child_by_field_name("type")
        or _first(node, "predefined_type")
        or _first(node, "identifier")
    )
    return _text(src, t).strip() if t else "void"


def _is_async(node, src: bytes) -> bool:
    return any(
        ch.type == "modifier" and _text(src, ch).strip() == "async"
        for ch in node.children
    )


def _last_ident(node, src: bytes) -> Optional[str]:
    if not node:
        return None
    if node.type == "identifier":
        return _text(src, node).strip()
    nm = node.child_by_field_name("name")
    if nm:
        return _last_ident(nm, src)
    last = None
    for i in range(node.child_count):
        v = _last_ident(node.child(i), src)
        if v:
            last = v
    return last


# ---------------------------------------------------------------------------
# Inheritance resolution (direct & indirect)
# ---------------------------------------------------------------------------
def _collect_all_bases(
    type_key: str, base_map: Dict[str, List[str]], visited: Optional[Set[str]] = None
) -> Set[str]:
    if visited is None:
        visited = set()
    direct = base_map.get(type_key, [])
    for b in direct:
        if b not in visited:
            visited.add(b)
            for key in base_map:
                if key.endswith(f"::{b}"):
                    visited |= _collect_all_bases(key, base_map, visited)
    return visited


# ---------------------------------------------------------------------------
# Parse .csproj for external references
# ---------------------------------------------------------------------------
def _parse_csproj_refs(project_path: Path) -> Tuple[Set[str], Set[str]]:
    proj_refs: Set[str] = set()
    pkg_refs: Set[str] = set()
    for csproj in project_path.rglob("*.csproj"):
        try:
            tree = ET.parse(csproj)
            root = tree.getroot()
            for pr in root.findall(".//ProjectReference"):
                include = pr.get("Include") or ""
                name = Path(include).stem
                proj_refs.add(name)
            for pref in root.findall(".//PackageReference"):
                name = pref.get("Include")
                if name:
                    pkg_refs.add(name)
        except ET.ParseError as e:
            logger.warning(f"Failed to parse {csproj}: {e}")
    return proj_refs, pkg_refs


# ---------------------------------------------------------------------------
# Main: two-pass + disambiguation + inheritance + parallelism + externals
# ---------------------------------------------------------------------------
def extract_csharp_graph(project_path: str) -> nx.DiGraph:
    base = Path(project_path)
    graph = nx.DiGraph()
    name_index: Dict[str, List[str]] = {}
    base_map: Dict[str, List[str]] = {}

    # project references
    proj_refs, pkg_refs = _parse_csproj_refs(base)
    logger.info(f"Project refs: {proj_refs}, Package refs: {pkg_refs}")

    # collect all .cs files, ignore generated
    files = [
        p for p in base.rglob("*.cs") if not p.name.endswith((".g.cs", ".Designer.cs"))
    ]

    # Pass 1: nodes & base types (parallel)
    def process_file_pass1(path: Path):
        try:
            src = path.read_bytes()
            tree = PARSER.parse(src)
            ns = _namespace(tree.root_node, src)
            rel = path.relative_to(base).as_posix()
            local_bases: Dict[str, List[str]] = {}
            local_names: List[Tuple[str, str]] = []

            for n in _walk(tree.root_node):
                if n.type in (
                    "class_declaration",
                    "interface_declaration",
                    "record_declaration",
                ):
                    cn = _decl_name(n, src)
                    bl = _first(n, "base_list")
                    bases = (
                        [
                            _text(src, c).strip()
                            for c in bl.children
                            if c.type == "simple_base_type"
                        ]
                        if bl
                        else []
                    )
                    if cn:
                        key = f"{ns}::{rel}::{cn}"
                        local_bases[key] = bases
            for n in _walk(tree.root_node):
                if n.type not in ("method_declaration", "constructor_declaration"):
                    continue
                m = _method_name(n, src) or "<ctor>"
                t = _enclosing_type(n, src)
                if not t:
                    continue
                nid = f"{ns}::{rel}::{t}::{m}"
                # compute is_test once
                is_test = _is_test(n, src)
                graph.add_node(
                    nid,
                    type="test" if is_test else "function",
                    file=rel,
                    start_line=n.start_point[0] + 1,
                    end_line=n.end_point[0] + 1,
                    parameters=_param_count(n),
                    return_type=_return_type(n, src),
                    is_test=is_test,
                    is_async=_is_async(n, src),
                )
                local_names.append((m, nid))
            return local_bases, local_names
        except Exception as e:
            logger.warning(f"Pass1 failed for {path}: {e}")
            return {}, []

    with ThreadPoolExecutor() as exec1:
        futures = {exec1.submit(process_file_pass1, f): f for f in files}
        for fut in as_completed(futures):
            lb, ln = fut.result()
            base_map.update(lb)
            for m, nid in ln:
                name_index.setdefault(m, []).append(nid)

    # Pass 2: edges building with de-duplication
    seen_edges: Set[Tuple[str, str]] = set()

    def process_file_pass2(
        path: Path,
    ) -> Tuple[List[Tuple[str, str]], List[Tuple[str, str, int]]]:
        edges: List[Tuple[str, str]] = []
        externals: List[Tuple[str, str, int]] = []
        try:
            src = path.read_bytes()
            tree = PARSER.parse(src)
            ns = _namespace(tree.root_node, src)
            rel = path.relative_to(base).as_posix()

            for n in _walk(tree.root_node):
                if n.type == "invocation_expression":
                    fn = n.child_by_field_name("function") or n.child_by_field_name(
                        "expression"
                    )
                    callee = _last_ident(fn, src)
                    argn = _arg_count(n)
                elif n.type == "object_creation_expression":
                    callee = _last_ident(n.child_by_field_name("type"), src)
                    argn = _arg_count(n)  # simplified for constructors
                else:
                    continue
                if not callee:
                    continue
                simple = callee.split(".")[-1]
                # find caller context
                p = n
                while p and p.type not in (
                    "method_declaration",
                    "constructor_declaration",
                ):
                    p = p.parent
                if not p:
                    continue
                cm = _method_name(p, src) or "<ctor>"
                ct = _enclosing_type(p, src)
                caller = f"{ns}::{rel}::{ct}::{cm}"
                if caller not in graph:
                    continue
                matched = False
                # internal direct
                for tgt in name_index.get(simple, []):
                    if (
                        graph.nodes[tgt]["parameters"] == argn
                        and (caller, tgt) not in seen_edges
                    ):
                        edges.append((caller, tgt))
                        matched = True
                # inheritance fallback
                if not matched:
                    all_bases = _collect_all_bases(f"{ns}::{rel}::{ct}", base_map)
                    for tgt in name_index.get(simple, []):
                        parts = tgt.split("::")
                        if (
                            parts[2] in all_bases
                            and graph.nodes[tgt]["parameters"] == argn
                            and (caller, tgt) not in seen_edges
                        ):
                            edges.append((caller, tgt))
                            matched = True
                # external
                if not matched:
                    externals.append((caller, simple, argn))
            return edges, externals
        except Exception as e:
            logger.warning(f"Pass2 failed for {path}: {e}")
            return [], []

    with ThreadPoolExecutor() as exec2:
        futures2 = {exec2.submit(process_file_pass2, f): f for f in files}
        for fut in as_completed(futures2):
            eds, exs = fut.result()
            for u, v in eds:
                if not graph.has_edge(u, v):
                    graph.add_edge(u, v)
                    seen_edges.add((u, v))
            for caller, simple, argn in exs:
                if simple in proj_refs:
                    ext_key = f"project::{simple}"
                elif simple in pkg_refs:
                    ext_key = f"nuget::{simple}"
                else:
                    ext_key = f"external::{simple}/{argn}"
                if not graph.has_node(ext_key):
                    graph.add_node(ext_key, type="external")
                if not graph.has_edge(caller, ext_key):
                    graph.add_edge(caller, ext_key)

    return graph
