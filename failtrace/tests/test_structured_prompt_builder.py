import json
import math
from pathlib import Path
import networkx as nx
import pytest

import failtrace.llm.structured_prompt_builder as spb


def test_get_error_message_found_and_not_found():
    summary = {"failed_detail": [{"name": "tests/t::fail", "error": "E"}]}
    assert spb.get_error_message(summary, "tests/t::fail") == "E"
    assert spb.get_error_message(summary, "tests/t::other") == ""


@pytest.mark.parametrize(
    "n,expected", [(0, 3), (1, 3), (10, 6), (1200, 12), (5000, 12)]
)
def test__compute_base_k_bounds_and_growth(n, expected):
    assert spb._compute_base_k(n) == expected
    assert 3 <= spb._compute_base_k(n) <= 12


@pytest.mark.parametrize(
    "nodes,edges,expected",
    [
        (0, 0, 0.7),
        (10, 0, 0.55),
        (10, 80, 0.85),
        (4, 8, 0.625),
        (8, 15, 0.55 + 0.30 * min(1.0, (15 / 8.0) / 8.0)),
    ],
)
def test__compute_alpha_range(nodes, edges, expected):
    got = spb._compute_alpha(nodes, edges)
    eps = 1e-12
    assert 0.55 - eps <= got <= 0.85 + eps
    assert math.isclose(got, expected, rel_tol=1e-12, abs_tol=1e-12)


@pytest.mark.parametrize(
    "u,base,alpha,expected_range",
    [
        (0, 12, 0.85, (0, 0)),
        (1, 12, 0.85, (3, 3)),
        (10, 12, 0.5, (3, 12)),
        (50, 5, 0.9, (3, 5)),
    ],
)
def test__k_for_test_clamping(u, base, alpha, expected_range):
    k = spb._k_for_test(u, base, alpha)
    assert expected_range[0] <= k <= expected_range[1]


def test__last_internal_non_test_prefers_last_non_external():
    path = [
        {"node": "T", "is_test": True, "type": "test", "file": "tests/t.py"},
        {"node": "A", "is_test": False, "type": "function", "file": "src/a.py"},
        {"node": "EXT", "type": "external", "file": "lib/x"},
        {"node": "B", "is_test": False, "type": "function", "file": "src/b.py"},
    ]
    nid, f = spb._last_internal_non_test(path)
    assert (nid, f) == ("B", "src/b.py")
    assert spb._last_internal_non_test([{"node": "T", "is_test": True}]) == (None, None)


def test__freq_counts_and__top_k_and_hotspots_selection():
    downstream = [
        [
            {"node": "T", "is_test": True},
            {"node": "A", "is_test": False, "type": "function", "file": "src/a.py"},
        ],
        [
            {"node": "T", "is_test": True},
            {"node": "B", "is_test": False, "type": "function", "file": "src/b.py"},
            {"node": "EXT", "type": "external"},
            {"node": "A", "is_test": False, "type": "function", "file": "src/a.py"},
        ],
        [
            {"node": "T", "is_test": True},
            {"node": "B", "is_test": False, "type": "function", "file": "src/b.py"},
        ],
    ]
    func_freq, file_freq = spb._freq_counts(downstream)
    assert func_freq == {"A": 2, "B": 1}
    assert file_freq == {"src/a.py": 2, "src/b.py": 1}
    top = spb._top_k({"x": 2, "y": 2, "a": 2}, 2)
    assert top == ["a", "x"] or top == ["a", "y"]
    hs = spb._build_hotspots_for_test(downstream, base_k=5, alpha=0.85)
    assert set(hs["functions"]) == {"A", "B"}
    assert set(hs["files"]) == {"src/a.py", "src/b.py"}
    hs_empty = spb._build_hotspots_for_test([], base_k=5, alpha=0.85)
    assert hs_empty == {"functions": [], "files": []}


def test_build_structured_prompt_end_to_end_with_monkeypatch(tmp_path, monkeypatch):
    g = nx.DiGraph()
    g.add_node("tests/t::fail", is_test=True, test_status="failed")
    g.add_node("m::foo", is_test=False)
    g.add_edge("m::foo", "tests/t::fail")

    def fake_build_graph(project_path):
        return g

    def fake_load_test_logs(log_path, lang):
        return [{"name": "tests/t::fail", "status": "failed", "message": "err msg"}]

    def fake_tag_graph_with_logs(graph, logs, lang):
        graph.nodes["tests/t::fail"]["error_message"] = "err msg"
        return graph

    def fake_build_test_summary(graph):
        return {
            "total_tests": 1,
            "executed_tests": 1,
            "passed_tests": 0,
            "failed_tests": 1,
            "skipped_tests": 0,
            "untagged_tests": 0,
            "failed_detail": [{"name": "tests/t::fail", "error": "err msg"}],
        }

    def fake_find_critical_paths(graph):
        return {
            "tests/t::fail": {
                "upstream": [
                    [
                        {
                            "node": "m::foo",
                            "file": "src/m.py",
                            "type": "function",
                            "is_test": False,
                        },
                        {
                            "node": "tests/t::fail",
                            "file": "tests/t.py",
                            "type": "test",
                            "is_test": True,
                        },
                    ]
                ],
                "downstream": [
                    [
                        {
                            "node": "tests/t::fail",
                            "file": "tests/t.py",
                            "type": "test",
                            "is_test": True,
                        },
                        {
                            "node": "m::bar",
                            "file": "src/bar.py",
                            "type": "function",
                            "is_test": False,
                        },
                    ]
                ],
            }
        }

    monkeypatch.setattr(spb, "build_graph", fake_build_graph)
    monkeypatch.setattr(spb, "load_test_logs", fake_load_test_logs)
    monkeypatch.setattr(spb, "tag_graph_with_logs", fake_tag_graph_with_logs)
    monkeypatch.setattr(spb, "build_test_summary", fake_build_test_summary)
    monkeypatch.setattr(spb, "find_critical_paths", fake_find_critical_paths)

    out_path = tmp_path / "out" / "llm_prompt.json"
    data = spb.build_structured_prompt("P", "L", "python", str(out_path))

    assert out_path.is_file()
    saved = json.loads(out_path.read_text(encoding="utf-8"))
    assert saved["meta"]["project_path"] == "P"
    assert saved["meta"]["language"] == "python"
    assert saved["summary"]["failed_tests"] == 1
    assert saved["critical_paths"]["tests/t::fail"]["error"] == "err msg"
    hs = data["hotspots"]["tests/t::fail"]
    assert isinstance(hs["functions"], list) and isinstance(hs["files"], list)
    assert 3 <= spb._compute_base_k(data["meta"]["graph"]["nodes"]) <= 12
