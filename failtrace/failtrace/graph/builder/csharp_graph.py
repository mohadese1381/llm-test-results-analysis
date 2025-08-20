from __future__ import annotations
import os
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
import networkx as nx
from tree_sitter import Language, Parser
import xml.etree.ElementTree as ET
import logging

try:
    from tree_sitter_c_sharp import language as _cs_capsule

    CSHARP_LANG = Language(_cs_capsule())
except ImportError:
    from tree_sitter_languages import get_language  # type: ignore

    CSHARP_LANG = get_language("c_sharp")
PARSER = Parser(CSHARP_LANG)


logger = logging.getLogger(__name__)


_EXCLUDED_DIRS: Set[str] = {
    "bin",
    "obj",
    ".vs",
    ".git",
    ".github",
    ".idea",
    ".vscode",
    "packages",
    ".nuget",
    "TestResults",
    "Coverage",
    ".sonarqube",
    ".azure-pipelines",
    ".artifacts",
    "out",
    "build",
    "target",
    "Generated",
}
_EXCLUDED_FILE_SUFFIXES_CI = (
    ".g.cs",
    ".g.i.cs",
    ".designer.cs",
    ".generated.cs",
    "assemblyinfo.cs",
)


def _contains_excluded_dir(path: Path) -> bool:
    return any(part.lower() in _EXCLUDED_DIRS for part in path.parts)


def _is_excluded_file(name: str) -> bool:
    return name.lower().endswith(_EXCLUDED_FILE_SUFFIXES_CI)


TEST_ATTRS = {
    "Fact",
    "Theory",
    "Test",
    "TestCase",
    "TestCaseSource",
    "ParameterizedTest",
    "TestFixture",
    "TestMethod",
    "DataTestMethod",
    "TestClass",
    "Ignore",
}


def _walk(node):
    cursor = node.walk()
    done = False
    while not done:
        yield cursor.node
        if cursor.goto_first_child():
            continue
        if cursor.goto_next_sibling():
            continue
        while True:
            if not cursor.goto_parent():
                done = True
                break
            if cursor.goto_next_sibling():
                break


def _text(src: bytes, node) -> str:
    return (
        src[node.start_byte : node.end_byte].decode("utf-8", "ignore") if node else ""
    )


def _first(node, typ: str):
    for i in range(getattr(node, "child_count", 0)):
        ch = node.child(i)
        if ch.type == typ:
            return ch
    return None


def _decl_name(node, src: bytes) -> Optional[str]:
    nm = node.child_by_field_name("name") or _first(node, "identifier")
    return _text(src, nm).strip() if nm else None


def _namespace(root, src: bytes) -> str:
    for n in _walk(root):
        if n.type in ("namespace_declaration", "file_scoped_namespace_declaration"):
            nm = n.child_by_field_name("name")
            txt = _text(src, nm).strip() if nm else ""
            return txt or "<global>"
    return "<global>"


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


def _is_async(node, src: bytes) -> bool:
    for i in range(node.child_count):
        ch = node.child(i)
        if ch.type == "modifier" and _text(src, ch).strip() == "async":
            return True
    return False


def _param_count(node) -> int:
    pl = node.child_by_field_name("parameter_list") or _first(node, "parameter_list")
    if not pl:
        return 0
    return sum(1 for ch in pl.children if ch.type == "parameter")


def _arg_count(inv_node) -> int:
    al = inv_node.child_by_field_name("argument_list") or _first(
        inv_node, "argument_list"
    )
    if not al:
        return 0
    return sum(1 for ch in al.children if ch.type == "argument")


def _identifier_deep(node, src: bytes) -> Optional[str]:
    if not node:
        return None
    t = node.type
    if t == "identifier":
        return _text(src, node).strip() or None
    if t in ("qualified_name", "generic_name"):
        last = None
        for i in range(node.child_count):
            v = _identifier_deep(node.child(i), src)
            if v:
                last = v
        return last
    if t in ("member_access_expression", "conditional_access_expression"):
        nm = node.child_by_field_name("name") or _first(node, "identifier")
        if nm:
            return _text(src, nm).strip() or None
        last = None
        for i in range(node.child_count):
            v = _identifier_deep(node.child(i), src)
            if v:
                last = v
        return last
    if t == "invocation_expression":
        fn = node.child_by_field_name("function") or node.child_by_field_name(
            "expression"
        )
        return _identifier_deep(fn, src)
    if t == "object_creation_expression":
        typ = node.child_by_field_name("type")
        return _identifier_deep(typ, src)
    last = None
    for i in range(node.child_count):
        v = _identifier_deep(node.child(i), src)
        if v:
            last = v
    return last


def _return_type(node, src: bytes) -> str:
    if node.type == "constructor_declaration":
        return "void"
    t = (
        node.child_by_field_name("type")
        or _first(node, "predefined_type")
        or _first(node, "identifier")
    )
    return _text(src, t).strip() if t else "void"


def _has_test_attribute_on_type(node, src: bytes) -> bool:
    for i in range(node.child_count):
        ch = node.child(i)
        if ch.type == "attribute_list":
            for j in range(ch.child_count):
                attr = ch.child(j)
                if attr.type == "attribute":
                    name = attr.child_by_field_name("name")
                    if name and _text(src, name).split(".")[-1] in TEST_ATTRS:
                        return True
    return False


def _is_test_method(node, src: bytes, class_is_test: bool) -> bool:
    for i in range(node.child_count):
        ch = node.child(i)
        if ch.type == "attribute_list":
            for j in range(ch.child_count):
                attr = ch.child(j)
                if attr.type == "attribute":
                    name = attr.child_by_field_name("name")
                    nm = _text(src, name).split(".")[-1] if name else ""
                    if nm in TEST_ATTRS:
                        return True
    if class_is_test:
        return True
    nm = _method_name(node, src) or ""
    return nm.lower().startswith(("test", "should_", "when_"))


def _collect_usings(root, src: bytes) -> List[str]:
    usings: List[str] = []
    for n in _walk(root):
        if n.type == "using_directive":
            name = n.child_by_field_name("name")
            if name:
                txt = _text(src, name).strip()
                if txt:
                    usings.append(txt)
    return usings


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
                if name:
                    proj_refs.add(name)
            for pref in root.findall(".//PackageReference"):
                name = pref.get("Include")
                if name:
                    pkg_refs.add(name)
        except ET.ParseError as e:
            logger.warning(f"Failed to parse {csproj}: {e}")
    return proj_refs, pkg_refs


def extract_csharp_graph(project_path: str) -> nx.DiGraph:
    base = Path(project_path)
    graph = nx.DiGraph()

    name_index: Dict[str, List[str]] = {}
    typemethod_index: Dict[Tuple[str, str], List[str]] = {}
    ns_typemethod_index: Dict[Tuple[str, str, str], List[str]] = {}
    base_map: Dict[str, List[str]] = {}

    proj_refs, pkg_refs = _parse_csproj_refs(base)

    files: List[Path] = []
    for p in base.rglob("*.cs"):
        if _contains_excluded_dir(p):
            continue
        if _is_excluded_file(p.name):
            continue
        files.append(p)

    def pass1(path: Path):
        try:
            src = path.read_bytes()
            tree = PARSER.parse(src)
            root = tree.root_node
            ns = _namespace(root, src)
            rel = path.relative_to(base).as_posix()

            local_bases: Dict[str, List[str]] = {}
            locals_idx: List[Tuple[str, str, str]] = []
            class_is_test: Dict[str, bool] = {}

            for n in _walk(root):
                if n.type in (
                    "class_declaration",
                    "interface_declaration",
                    "record_declaration",
                ):
                    cn = _decl_name(n, src)
                    if not cn:
                        continue
                    base_list = _first(n, "base_list")
                    bases = []
                    if base_list:
                        for ch in base_list.children:
                            if ch.type in ("simple_base_type", "base_type"):
                                nm = _text(src, ch).strip().split("<", 1)[0].strip()
                                if nm:
                                    bases.append(nm)
                    key = f"{ns}::{rel}::{cn}"
                    local_bases[key] = bases
                    class_is_test[key] = _has_test_attribute_on_type(n, src)

            for n in _walk(root):
                if n.type not in ("method_declaration", "constructor_declaration"):
                    continue
                tname = _enclosing_type(n, src)
                if not tname:
                    continue
                mname = _method_name(n, src) or "<ctor>"
                key_type = f"{ns}::{rel}::{tname}"
                is_test = _is_test_method(n, src, class_is_test.get(key_type, False))
                node_id = f"{ns}::{rel}::{tname}::{mname}"
                graph.add_node(
                    node_id,
                    type="test" if is_test else "function",
                    file=rel,
                    start_line=n.start_point[0] + 1,
                    end_line=n.end_point[0] + 1,
                    parameters=_param_count(n),
                    return_type=_return_type(n, src),
                    is_test=is_test,
                    is_async=_is_async(n, src),
                )
                locals_idx.append((tname, mname, node_id))
            return local_bases, locals_idx, ns, rel, _collect_usings(root, src)
        except Exception as e:
            logger.warning(f"Pass1 failed for {path}: {e}")
            return {}, [], "<global>", path.name, []

    file_usings: Dict[str, List[str]] = {}
    file_ns: Dict[str, str] = {}

    with ThreadPoolExecutor() as ex1:
        futs = {ex1.submit(pass1, f): f for f in files}
        for fut in as_completed(futs):
            lb, locals_idx, ns, rel, usings = fut.result()
            base_map.update(lb)
            file_usings[rel] = usings
            file_ns[rel] = ns
            for tname, mname, nid in locals_idx:
                name_index.setdefault(mname, []).append(nid)
                typemethod_index.setdefault((tname, mname), []).append(nid)
                ns2, rel2, *_ = nid.split("::", 3)
                ns_typemethod_index.setdefault((ns2, tname, mname), []).append(nid)

    seen_edges: Set[Tuple[str, str]] = set()

    def _match_targets(ns: str, caller_type: str, simple: str, argc: int) -> List[str]:
        cands: List[str] = []
        for nid in ns_typemethod_index.get((ns, caller_type, simple), []):
            if graph.nodes[nid].get("parameters") == argc:
                cands.append(nid)
        if cands:
            return cands
        for nid in typemethod_index.get((caller_type, simple), []):
            if graph.nodes[nid].get("parameters") == argc:
                cands.append(nid)
        if cands:
            return cands
        for nid in name_index.get(simple, []):
            if graph.nodes[nid].get("parameters") == argc:
                cands.append(nid)
        if cands:
            return cands
        pref = ns_typemethod_index.get((ns, caller_type, simple), [])
        if pref:
            return pref
        pref2 = typemethod_index.get((caller_type, simple), [])
        if pref2:
            return pref2
        return name_index.get(simple, []) or []

    def _update_external_node(ext_key: str, origin: Dict[str, object]) -> None:
        node = graph.nodes[ext_key]
        counts: Dict[str, int] = node.get("origin_counts", {})
        key = f"{origin.get('file')}|{origin.get('namespace')}|{origin.get('kind')}|{origin.get('symbol')}"
        counts[key] = counts.get(key, 0) + 1
        node["origin_counts"] = counts

        parts: List[Dict[str, object]] = []
        for k, c in sorted(counts.items(), key=lambda kv: kv[1], reverse=True):
            f, ns, kind, sym = k.split("|", 3)
            parts.append(
                {"file": f, "namespace": ns, "kind": kind, "symbol": sym, "count": c}
            )
        node["origins"] = parts

    def pass2(path: Path):
        edges: List[Tuple[str, str]] = []
        ex_edges: List[Tuple[str, str, Dict[str, object]]] = (
            []
        )  # (caller, ext_key, origin)
        try:
            src = path.read_bytes()
            tree = PARSER.parse(src)
            root = tree.root_node
            rel = path.relative_to(base).as_posix()
            ns = file_ns.get(rel) or _namespace(root, src)
            usings = file_usings.get(rel) or _collect_usings(root, src)

            def _caller_node(n):
                p = n
                while p and p.type not in (
                    "method_declaration",
                    "constructor_declaration",
                ):
                    p = p.parent
                if not p:
                    return None, None
                cm = _method_name(p, src) or "<ctor>"
                ct = _enclosing_type(p, src)
                return cm, ct

            for n in _walk(root):
                if n.type == "invocation_expression":
                    fn = n.child_by_field_name("function") or n.child_by_field_name(
                        "expression"
                    )
                    callee = _identifier_deep(fn, src)
                    argc = _arg_count(n)
                    cm, ct = _caller_node(n)
                    if not callee or not cm or not ct:
                        continue
                    caller = f"{ns}::{rel}::{ct}::{cm}"
                    if caller not in graph:
                        continue

                    simple = callee.split(".")[-1]
                    targets = _match_targets(ns, ct, simple, argc)
                    if targets:
                        for tgt in targets:
                            if (caller, tgt) not in seen_edges:
                                edges.append((caller, tgt))
                        continue

                    if simple in proj_refs:
                        ext_key = f"project::{simple}"
                    elif simple in pkg_refs:
                        ext_key = f"nuget::{simple}"
                    else:
                        ext_key = f"external::{simple}/{argc}"

                    origin = {
                        "language": "csharp",
                        "namespace": ns,
                        "usings": usings,
                        "symbol": simple,
                        "kind": "call",
                        "file": rel,
                    }
                    ex_edges.append((caller, ext_key, origin))

                elif n.type == "object_creation_expression":
                    typ = n.child_by_field_name("type")
                    callee_type = _identifier_deep(typ, src)
                    argc = _arg_count(n)
                    cm, ct = _caller_node(n)
                    if not callee_type or not cm or not ct:
                        continue
                    caller = f"{ns}::{rel}::{ct}::{cm}"
                    if caller not in graph:
                        continue

                    simple_ctor = callee_type.split(".")[-1]
                    ctor_targets = typemethod_index.get((simple_ctor, "<ctor>"), [])
                    if ctor_targets:
                        for tgt in ctor_targets:
                            if (caller, tgt) not in seen_edges:
                                edges.append((caller, tgt))
                        continue

                    targets = name_index.get(simple_ctor, [])
                    if targets:
                        for tgt in targets:
                            if (caller, tgt) not in seen_edges:
                                edges.append((caller, tgt))
                        continue

                    if simple_ctor in proj_refs:
                        ext_key = f"project::{simple_ctor}"
                    elif simple_ctor in pkg_refs:
                        ext_key = f"nuget::{simple_ctor}"
                    else:
                        ext_key = f"external::{simple_ctor}/{argc}"

                    origin = {
                        "language": "csharp",
                        "namespace": ns,
                        "usings": usings,
                        "symbol": simple_ctor,
                        "kind": "new",
                        "file": rel,
                    }
                    ex_edges.append((caller, ext_key, origin))

            return edges, ex_edges
        except Exception as e:
            logger.warning(f"Pass2 failed for {path}: {e}")
            return [], []

    with ThreadPoolExecutor() as ex2:
        futs = {ex2.submit(pass2, f): f for f in files}
        for fut in as_completed(futs):
            eds, exs = fut.result()
            for u, v in eds:
                if not graph.has_edge(u, v):
                    graph.add_edge(u, v)
                    seen_edges.add((u, v))
            for caller, ext_key, origin in exs:
                if not graph.has_node(ext_key):
                    graph.add_node(ext_key, type="external", origins=[])
                if not graph.has_edge(caller, ext_key):
                    graph.add_edge(caller, ext_key, origin=origin)
                else:
                    ed = graph.get_edge_data(caller, ext_key) or {}
                    if "origin" not in ed:
                        graph.add_edge(caller, ext_key, origin=origin)
                _update_external_node(ext_key, origin)

    return graph
