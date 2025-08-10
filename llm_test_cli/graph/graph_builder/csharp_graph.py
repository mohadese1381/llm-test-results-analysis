from __future__ import annotations
import os
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
import networkx as nx
from tree_sitter import Language, Parser
import xml.etree.ElementTree as ET
import logging

# ─────────────────────────────────────────────────────────────────────────────
# Tree-sitter init
# ─────────────────────────────────────────────────────────────────────────────
try:
    from tree_sitter_c_sharp import language as _cs_capsule

    CSHARP_LANG = Language(_cs_capsule())
except ImportError:
    from tree_sitter_languages import get_language  # type: ignore

    CSHARP_LANG = get_language("c_sharp")
PARSER = Parser(CSHARP_LANG)

# ─────────────────────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────────────────────
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Filters
# ─────────────────────────────────────────────────────────────────────────────
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
    lname = name.lower()
    return lname.endswith(_EXCLUDED_FILE_SUFFIXES_CI)


# ─────────────────────────────────────────────────────────────────────────────
# Test detection
# ─────────────────────────────────────────────────────────────────────────────
TEST_ATTRS = {
    # xUnit
    "Fact",
    "Theory",
    # NUnit
    "Test",
    "TestCase",
    "TestCaseSource",
    "ParameterizedTest",
    "TestFixture",
    # MSTest
    "TestMethod",
    "DataTestMethod",
    "TestClass",
    # skip
    "Ignore",
}


# ─────────────────────────────────────────────────────────────────────────────
# AST helpers
# ─────────────────────────────────────────────────────────────────────────────
def _walk(node):
    cursor = node.walk()
    reached_end = False
    while not reached_end:
        yield cursor.node
        if cursor.goto_first_child():
            continue
        if cursor.goto_next_sibling():
            continue
        while True:
            if not cursor.goto_parent():
                reached_end = True
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
        if n.type == "namespace_declaration":
            nm = n.child_by_field_name("name")
            return _text(src, nm).strip() if nm else "<global>"
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
    # any child 'modifier' == async
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
    """
    آخرین شناسه قابل‌اتکا از یک عبارت را برمی‌گرداند:
    - member_access_expression: name
    - invocation_expression: از function/expression بیرون بکش
    - generic_name / qualified_name / identifier
    - object_creation_expression: type
    """
    if not node:
        return None
    t = node.type
    if t == "identifier":
        return _text(src, node).strip() or None
    if t in ("qualified_name", "generic_name"):
        # آخرین بخش
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
        # fallback: deepest identifier
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
    # walk children
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
    # for class/fixture-level attributes
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
    # method-level attributes win
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
        # در کلاس تست، متدهای public اغلب تست‌اند حتی بدون اتریبیوت
        # (xUnit: اجازه‌ی Fact لازم است، ولی برای پوشش حداکثری این را قبول می‌کنیم)
        return True
    # نام‌گذاری
    nm = _method_name(node, src) or ""
    return nm.lower().startswith(("test", "should_", "when_"))


# ─────────────────────────────────────────────────────────────────────────────
# Inheritance resolution
# ─────────────────────────────────────────────────────────────────────────────
def _collect_all_bases(type_key: str, base_map: Dict[str, List[str]]) -> Set[str]:
    """
    type_key = "{ns}::{rel}::{Type}"
    base_map  type_key -> [BaseTypeName, ...]
    خروجی: مجموعه‌ی نام تمام BaseType ها (به‌صورت «نام نوع»، نه کلید کامل)
    """
    out: Set[str] = set()
    stack: List[str] = [type_key]
    seen: Set[str] = set()
    while stack:
        tk = stack.pop()
        if tk in seen:
            continue
        seen.add(tk)
        for b in base_map.get(tk, []):
            if b not in out:
                out.add(b)
            # اگر کلیدی هست که با این base ختم می‌شود، ادامه بده
            for k in base_map:
                # k ... :: {Base}
                if k.endswith(f"::{b}"):
                    stack.append(k)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# .csproj references (projects & nuget)
# ─────────────────────────────────────────────────────────────────────────────
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


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
def extract_csharp_graph(project_path: str) -> nx.DiGraph:
    base = Path(project_path)
    graph = nx.DiGraph()

    # Indexes for matching
    name_index: Dict[str, List[str]] = {}  # method -> [node_ids]
    typemethod_index: Dict[Tuple[str, str], List[str]] = (
        {}
    )  # (Type, Method) -> [node_ids]
    ns_typemethod_index: Dict[Tuple[str, str, str], List[str]] = (
        {}
    )  # (NS, Type, Method) -> [node_ids]
    base_map: Dict[str, List[str]] = {}  # type_key -> [base names]

    proj_refs, pkg_refs = _parse_csproj_refs(base)
    logger.info(f"Project refs: {proj_refs}, Package refs: {pkg_refs}")

    # Collect files
    files: List[Path] = []
    for p in base.rglob("*.cs"):
        if _contains_excluded_dir(p):  # skip generated & build
            continue
        if _is_excluded_file(p.name):
            continue
        files.append(p)

    # ── Pass 1: collect nodes & bases
    def pass1(path: Path):
        try:
            src = path.read_bytes()
            tree = PARSER.parse(src)
            root = tree.root_node
            ns = _namespace(root, src)
            rel = path.relative_to(base).as_posix()

            local_bases: Dict[str, List[str]] = {}
            locals_idx: List[Tuple[str, str, str]] = []  # (Type, Method, node_id)
            class_is_test: Dict[str, bool] = {}  # key = (ns, rel, Type) -> is_test

            # classes / interfaces / records
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
                                nm = _text(src, ch).strip()
                                # پاک‌سازی generic args
                                nm = nm.split("<", 1)[0].strip()
                                if nm:
                                    bases.append(nm)
                    key = f"{ns}::{rel}::{cn}"
                    local_bases[key] = bases
                    class_is_test[key] = _has_test_attribute_on_type(n, src)

            # methods (+ ctors)
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

            return local_bases, locals_idx
        except Exception as e:
            logger.warning(f"Pass1 failed for {path}: {e}")
            return {}, []

    with ThreadPoolExecutor() as ex1:
        futs = {ex1.submit(pass1, f): f for f in files}
        for fut in as_completed(futs):
            lb, locals_idx = fut.result()
            base_map.update(lb)
            for tname, mname, nid in locals_idx:
                name_index.setdefault(mname, []).append(nid)
                typemethod_index.setdefault((tname, mname), []).append(nid)
                ns, rel, *_ = nid.split("::", 3)
                ns_typemethod_index.setdefault((ns, tname, mname), []).append(nid)

    # ── Pass 2: edges
    seen_edges: Set[Tuple[str, str]] = set()

    def _match_targets(ns: str, caller_type: str, simple: str, argc: int) -> List[str]:
        """
        چندمرحله‌ای:
        1) (NS+Type+Method) با پارامتر برابر
        2) (Type+Method) با پارامتر برابر
        3) فقط نام متد با پارامتر برابر
        4) بدون قیود پارامتر، اما نزدیک‌ترین‌ها (NS/Type) در اولویت
        """
        candidates: List[str] = []

        # 1
        for nid in ns_typemethod_index.get((ns, caller_type, simple), []):
            if graph.nodes[nid].get("parameters") == argc:
                candidates.append(nid)
        if candidates:
            return candidates

        # 2
        for nid in typemethod_index.get((caller_type, simple), []):
            if graph.nodes[nid].get("parameters") == argc:
                candidates.append(nid)
        if candidates:
            return candidates

        # 3
        for nid in name_index.get(simple, []):
            if graph.nodes[nid].get("parameters") == argc:
                candidates.append(nid)
        if candidates:
            return candidates

        # 4) relax param count
        # prefer same NS & Type
        pref = ns_typemethod_index.get((ns, caller_type, simple), [])
        if pref:
            return pref
        pref2 = typemethod_index.get((caller_type, simple), [])
        if pref2:
            return pref2
        return name_index.get(simple, []) or []

    def pass2(path: Path):
        edges: List[Tuple[str, str]] = []
        externals: List[Tuple[str, str, int, str]] = []  # (caller, simple, argc, kind)
        try:
            src = path.read_bytes()
            tree = PARSER.parse(src)
            root = tree.root_node
            ns = _namespace(root, src)
            rel = path.relative_to(base).as_posix()

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

                    externals.append((caller, simple, argc, "call"))

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
                    # سازنده‌ها با نام <ctor> ذخیره شدند؛ ولی معمولاً از نظر نام متدی ندارند.
                    # پس ابتدا <ctor> در همان Type هدف را جست‌وجو می‌کنیم
                    ctor_targets = typemethod_index.get((simple_ctor, "<ctor>"), [])
                    if ctor_targets:
                        for tgt in ctor_targets:
                            if (caller, tgt) not in seen_edges:
                                edges.append((caller, tgt))
                        continue

                    # شاید سازنده نام‌گذاری نشده و به Initialize/Build می‌خورد—fallback به نام نوع
                    targets = name_index.get(simple_ctor, [])
                    if targets:
                        for tgt in targets:
                            if (caller, tgt) not in seen_edges:
                                edges.append((caller, tgt))
                        continue

                    externals.append((caller, simple_ctor, argc, "new"))

                elif n.type == "await_expression":
                    # await foo.BarAsync() → در child یک invocation_expression است، قبلاً گرفته می‌شود
                    continue

            return edges, externals
        except Exception as e:
            logger.warning(f"Pass2 failed for {path}: {e}")
            return [], []

    with ThreadPoolExecutor() as ex2:
        futs2 = {ex2.submit(pass2, f): f for f in files}
        for fut in as_completed(futs2):
            eds, exs = fut.result()
            for u, v in eds:
                if not graph.has_edge(u, v):
                    graph.add_edge(u, v)
                    seen_edges.add((u, v))
            for caller, simple, argc, kind in exs:
                # Label external nodes; try to hint project/nuget when name matches
                if simple in proj_refs:
                    ext_key = f"project::{simple}"
                elif simple in pkg_refs:
                    ext_key = f"nuget::{simple}"
                else:
                    ext_key = f"external::{simple}/{argc}"
                if not graph.has_node(ext_key):
                    graph.add_node(ext_key, type="external")
                if not graph.has_edge(caller, ext_key):
                    graph.add_edge(caller, ext_key)

    return graph
