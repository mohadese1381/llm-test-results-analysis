import networkx as nx
import pytest

import failtrace.analysis.summarizer as sm


def test_empty_graph_returns_all_zeros():
    g = nx.DiGraph()
    summary = sm.build_test_summary(g)
    assert summary["total_tests"] == 0
    assert summary["executed_tests"] == 0
    assert summary["failed_detail"] == []


def test_mixed_test_statuses_and_untagged():
    g = nx.DiGraph()
    g.add_node("t_pass", is_test=True, test_status="passed", file="f1.py", line=1)
    g.add_node(
        "t_fail",
        is_test=True,
        test_status="failed",
        file="f2.py",
        line=2,
        error_message="boom",
        docstring="doc",
    )
    g.add_node("t_skip", is_test=True, test_status="skipped", file="f3.py", line=3)
    g.add_node("t_untagged", is_test=True, file="f4.py", line=4)
    g.add_node("helper", is_test=False)

    summary = sm.build_test_summary(g)
    assert summary["total_tests"] == 4
    assert summary["executed_tests"] == 3
    assert summary["passed_tests"] == 1
    assert summary["failed_tests"] == 1
    assert summary["skipped_tests"] == 1
    assert summary["untagged_tests"] == 1
    assert len(summary["failed_detail"]) == 1
    detail = summary["failed_detail"][0]
    assert detail["name"] == "t_fail"
    assert detail["file"] == "f2.py"
    assert detail["line"] == 2
    assert detail["error"] == "boom"
    assert detail["doc"] == "doc"


@pytest.mark.parametrize("status_key", ["PASSED", "Failed", "sKiPpEd"])
def test_status_case_insensitivity(status_key):
    g = nx.DiGraph()
    g.add_node("t", is_test=True, test_status=status_key, file="f.py")
    summary = sm.build_test_summary(g)
    assert summary["total_tests"] == 1
    assert summary["executed_tests"] == 1
    if status_key.lower() == "passed":
        assert summary["passed_tests"] == 1
    elif status_key.lower() == "failed":
        assert summary["failed_tests"] == 1
    elif status_key.lower() == "skipped":
        assert summary["skipped_tests"] == 1
