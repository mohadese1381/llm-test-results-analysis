import networkx as nx
import pytest

import failtrace.analysis.critical_path_extractor as cp


def test__keep_step_filters_excluded_paths_and_handles_missing():
    assert cp._keep_step({"file": ""}) is True
    assert cp._keep_step({"file": None}) is True
    assert cp._keep_step({"file": "src/app/core.py"}) is True
    for bad in cp._EXCLUDED_SUBSTRS:
        assert cp._keep_step({"file": bad.strip("/") + "/x.py"}) is False
        assert cp._keep_step({"file": bad + "y.py"}) is False
    assert cp._keep_step("not-a-dict") is False


def test__unique_preserves_order_and_removes_dups():
    seq = ["a", "b", "a", "c", "b", "d"]
    assert cp._unique(seq) == ["a", "b", "c", "d"]


def test__attach_origin_for_external_step_prefers_predecessors_then_successors():
    g = nx.DiGraph()
    g.add_node("A", file="src/a.py")
    g.add_node("B", file="src/b.py")
    g.add_node("EXT", type="external")
    g.add_edge("A", "EXT")
    step = {"node": "EXT", "type": "external"}
    cp._attach_origin_for_external_step(g, step)
    assert step.get("origin") and step["origin"]["callers"] == ["src/a.py"]

    g2 = nx.DiGraph()
    g2.add_node("EXT", type="external")
    g2.add_node("C", file="src/c.py")
    g2.add_edge("EXT", "C")
    step2 = {"node": "EXT", "type": "external"}
    cp._attach_origin_for_external_step(g2, step2)
    assert step2.get("origin") and step2["origin"]["callers"] == ["src/c.py"]

    g3 = nx.DiGraph()
    g3.add_node("EXT", type="external")
    step3 = {"node": "EXT", "type": "external"}
    cp._attach_origin_for_external_step(g3, step3)
    assert step3.get("origin") and step3["origin"]["callers"] == []


def test__augment_externals_with_origin_only_when_absent(monkeypatch):
    g = nx.DiGraph()
    g.add_node("EXT", type="external")
    p = [{"node": "EXT", "type": "external"}]
    called = {"n": 0}

    def fake_attach(graph, step):
        called["n"] += 1
        step["origin"] = {"callers": ["src/x.py"]}

    monkeypatch.setattr(cp, "_attach_origin_for_external_step", fake_attach)
    cp._augment_externals_with_origin(g, p)
    assert called["n"] == 1
    cp._augment_externals_with_origin(g, p)
    assert called["n"] == 1


def test__path_signature_and_informativeness_score_and_postprocess():
    p1 = [{"node": "A", "is_test": False}, {"node": "T", "is_test": True}]
    p2 = [
        {"node": "A", "is_test": False},
        {"node": "B", "is_test": False},
        {"node": "T", "is_test": True},
    ]
    p3 = [{"node": "X", "is_test": False}, {"node": "T", "is_test": True}]

    assert cp._path_signature(p1) == ("A", "T")
    assert cp._informativeness_score(p1) == (1, 2)
    assert cp._informativeness_score(p2) == (2, 3)

    merged = cp._postprocess_paths(
        [p1, p2, p3, [], [{"no_node_key": 1}], [{"node": "T", "is_test": True}]],
        drop_short_downstream=True,
        max_paths=2,
    )
    assert merged[0] == p2
    assert merged[1] in (p1, p3)
    assert all(len(m) >= 2 for m in merged)


def _make_graph_for_find():
    g = nx.DiGraph()
    g.add_node("proj::validate", file="src/validate.py", type="function", is_test=False)
    g.add_node("proj::handler", file="src/handler.py", type="function", is_test=False)
    g.add_node("ext::http/get", type="external")
    g.add_node(
        "tests::test_api", file="tests/test_api.py", is_test=True, test_status="failed"
    )
    g.add_edge("proj::validate", "proj::handler")
    g.add_edge("proj::handler", "tests::test_api")
    g.add_edge("proj::handler", "ext::http/get")
    g.add_node("venv::helper", file=".venv/helper.py", type="function", is_test=False)
    g.add_edge("venv::helper", "proj::handler")
    return g


def test_find_critical_paths_basic_happy_path(monkeypatch):
    g = _make_graph_for_find()

    files = {
        "proj::validate": "src/validate.py",
        "proj::handler": "src/handler.py",
        "ext::http/get": "requests/api.py",
        "tests::test_api": "tests/test_api.py",
        "venv::helper": ".venv/helper.py",
    }
    types = {
        "proj::validate": "function",
        "proj::handler": "function",
        "ext::http/get": "external",
        "tests::test_api": "test",
        "venv::helper": "function",
    }

    def fake_enrich(graph, path):
        return [
            {
                "node": n,
                "file": files.get(n, ""),
                "type": types.get(n, "function"),
                "is_test": n.startswith("tests::"),
            }
            for n in path
        ]

    monkeypatch.setattr(cp, "enrich_path_with_metadata", fake_enrich)

    res = cp.find_critical_paths(g, cutoff=5, max_paths_per_direction=5)
    assert "tests::test_api" in res
    up = res["tests::test_api"]["upstream"]
    dn = res["tests::test_api"]["downstream"]

    assert any(step["node"] == "proj::validate" for path in up for step in path)
    assert all(all(cp._keep_step(s) for s in path) for path in up)
    assert all(all(cp._keep_step(s) for s in path) for path in dn)
    assert dn == []


def test_find_critical_paths_no_failed_tests_returns_empty(monkeypatch):
    g = nx.DiGraph()
    g.add_node("proj::a", file="a.py", is_test=False)
    g.add_node("tests::t", file="tests/t.py", is_test=True, test_status="passed")

    def fake_enrich(graph, path):
        return [
            {
                "node": n,
                "file": "a.py",
                "type": "function",
                "is_test": n.startswith("tests::"),
            }
            for n in path
        ]

    monkeypatch.setattr(cp, "enrich_path_with_metadata", fake_enrich)
    assert cp.find_critical_paths(g) == {}


def test_find_critical_paths_respects_cutoff_and_postprocess(monkeypatch):
    g = nx.DiGraph()
    g.add_node("A", file="a.py")
    g.add_node("B", file="b.py")
    g.add_node("C", file="c.py")
    g.add_node("T", file="tests/t.py", is_test=True, test_status="failed")
    g.add_edge("A", "B")
    g.add_edge("B", "C")
    g.add_edge("C", "T")

    def fake_enrich(graph, path):
        return [
            {
                "node": n,
                "file": f"{n.lower()}.py",
                "type": "function",
                "is_test": n == "T",
            }
            for n in path
        ]

    monkeypatch.setattr(cp, "enrich_path_with_metadata", fake_enrich)

    res_short = cp.find_critical_paths(g, cutoff=2, max_paths_per_direction=10)
    ups_short = res_short["T"]["upstream"]
    sigs_short = {tuple(s["node"] for s in p) for p in ups_short}
    assert ("B", "C", "T") in sigs_short
    assert ("C", "T") in sigs_short
    assert all(len(p) <= 3 for p in ups_short)

    res_long = cp.find_critical_paths(g, cutoff=3, max_paths_per_direction=1)
    assert len(res_long["T"]["upstream"]) == 1
    assert tuple(s["node"] for s in res_long["T"]["upstream"][0]) == (
        "A",
        "B",
        "C",
        "T",
    )


def test_find_critical_paths_filters_excluded_nodes_in_paths(monkeypatch):
    g = nx.DiGraph()
    g.add_node("X", file="site-packages/pkg.py")
    g.add_node("Y", file="src/y.py")
    g.add_node("T", file="tests/t.py", is_test=True, test_status="failed")
    g.add_edge("X", "Y")
    g.add_edge("Y", "T")

    def fake_enrich(graph, path):
        mapping = {"X": "site-packages/pkg.py", "Y": "src/y.py", "T": "tests/t.py"}
        return [
            {"node": n, "file": mapping[n], "type": "function", "is_test": n == "T"}
            for n in path
        ]

    monkeypatch.setattr(cp, "enrich_path_with_metadata", fake_enrich)
    res = cp.find_critical_paths(g, cutoff=3, max_paths_per_direction=5)
    up = res["T"]["upstream"]
    assert up and all(
        all("site-packages" not in (s.get("file") or "") for s in path) for path in up
    )
