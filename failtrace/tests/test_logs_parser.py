import json
import os
from pathlib import Path
from textwrap import dedent
import types
import importlib
import pytest

from failtrace.utils.logs_parser import (
    _ANSI_RE,
    _ANSI_HASH_RE,
    _strip_xml_namespaces,
    _safe_parse_xml,
    _clean_text,
    _text_of,
    _attr,
    _normalize_record,
    TestLogParser,
    PytestJSONParser,
    GenericJSONParser,
    JUnitXMLParser,
    NUnitV3XMLParser,
    TRXXMLParser,
    XUnitXMLParser,
    UniversalXMLParser,
    _iter_log_files,
    load_test_logs,
)


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


@pytest.mark.parametrize(
    "s, expected",
    [
        ("", ""),
        (None, ""),
        ("  hi  ", "hi"),
        ("\x1b[31mRED\x1b[0m", "RED"),
        ("#x1B[31mRED#x1B[0m", "RED"),
    ],
)
def test_clean_text_variants(s, expected):
    assert _clean_text(s) == expected


def test_text_of_and_attr_behaviour():
    from xml.etree.ElementTree import Element

    assert _text_of(None) == ""
    e = Element("msg")
    e.text = "  hello \x1b[31mX\x1b[0m "
    assert _text_of(e) == "hello X"
    assert _attr(None, "name") == ""
    e2 = Element("t")
    e2.set("name", "  Val#x1B[32m ")
    assert _attr(e2, "name") == "Val"


def test_strip_xml_namespaces_and_safe_parse(tmp_path):
    xml = """<ns:root xmlns:ns="http://x"><ns:child>ok</ns:child></ns:root>"""
    p = _write(tmp_path, "ns.xml", xml)
    root = _safe_parse_xml(str(p))
    assert root is not None
    assert root.tag == "root"
    assert [c.tag for c in root] == ["child"]

    bad = _write(tmp_path, "bad.xml", "<root><broken></root>")
    assert _safe_parse_xml(str(bad)) is None


def test_normalize_record_lowercases_status_and_cleans():
    rec = _normalize_record("  N  ", "  FAILED  ", " \x1b[31mE\x1b[0m ")
    assert rec == {"name": "N", "status": "failed", "message": "E"}


def test_pytest_json_parser_dict_and_list(tmp_path):
    data1 = {
        "tests": [
            {"nodeid": "tests/test_a.py::test_ok", "outcome": "passed"},
            {
                "nodeid": "tests/test_a.py::test_fail",
                "outcome": "failed",
                "longrepr": "ZeroDivisionError",
            },
        ]
    }
    p1 = _write(tmp_path, "rep1.json", json.dumps(data1))
    out1 = PytestJSONParser().load(str(p1))
    assert len(out1) == 2 and any(t["status"] == "failed" for t in out1)

    data2 = {"report": {"tests": [{"name": "A::B", "status": "passed"}]}}
    p2 = _write(tmp_path, "rep2.json", json.dumps(data2))
    out2 = PytestJSONParser().load(str(p2))
    assert out2 == [{"name": "A::B", "status": "passed", "message": ""}]

    data3 = [{"name": "X::Y", "status": "skipped", "message": "why"}]
    p3 = _write(tmp_path, "rep3.json", json.dumps(data3))
    out3 = PytestJSONParser().load(str(p3))
    assert out3 == [{"name": "X::Y", "status": "skipped", "message": "why"}]


def test_generic_json_parser_list_only(tmp_path):
    data = [
        {"name": "a", "status": "FAILED", "message": "m"},
        {"name": "b", "status": "passed", "message": ""},
        {"foo": "bar"},
    ]
    p = _write(tmp_path, "gen.json", json.dumps(data))
    out = GenericJSONParser().load(str(p))
    assert out[0]["status"] == "failed"
    assert out[1]["name"] == "b"
    assert len(out) == 3
    assert out[2] == {"name": "", "status": "", "message": ""}


def test_junit_xml_parser_pass_fail_skip(tmp_path):
    xml = dedent(
        """\
    <testsuite name="ts">
      <testcase classname="pkg.T" name="ok"/>
      <testcase classname="pkg.T" name="fail">
        <failure message="AssertionError">expected 2 got 3</failure>
      </testcase>
      <testcase classname="pkg.T" name="sk">
        <skipped message="why"/>
      </testcase>
    </testsuite>
    """
    )
    p = _write(tmp_path, "junit.xml", xml)
    out = JUnitXMLParser().load(str(p))
    kinds = {t["name"]: t["status"] for t in out}
    assert kinds["pkg.T::ok"] == "passed"
    assert kinds["pkg.T::fail"] == "failed"
    assert kinds["pkg.T::sk"] == "skipped"
    assert any("AssertionError" in t["message"] for t in out)


def test_nunit_v3_xml_parser(tmp_path):
    xml = dedent(
        """\
    <test-run>
      <test-case fullname="NS.Tests.Foo.Bar" result="Failed">
        <failure><message>boom</message></failure>
      </test-case>
      <test-case classname="NS.Tests.Foo" name="SkipMe" result="Skipped">
        <reason><message>n/a</message></reason>
      </test-case>
    </test-run>
    """
    )
    p = _write(tmp_path, "nunit.xml", xml)
    out = NUnitV3XMLParser().load(str(p))
    got = {t["name"]: t["status"] for t in out}
    assert got["NS.Tests.Foo.Bar"] == "failed"
    assert got["NS.Tests.Foo.SkipMe"] == "skipped"


def test_trx_xml_parser(tmp_path):
    xml = dedent(
        """\
    <TestRun>
      <TestDefinitions>
        <UnitTest id="1">
          <TestMethod className="NS.Tests.CalcTests" name="Should_Add"/>
        </UnitTest>
      </TestDefinitions>
      <Results>
        <UnitTestResult testId="1" testName="ignored" outcome="Failed">
          <Output><ErrorInfo><Message>NullReferenceException</Message></ErrorInfo></Output>
        </UnitTestResult>
      </Results>
    </TestRun>
    """
    )
    p = _write(tmp_path, "rep.trx", xml)
    out = TRXXMLParser().load(str(p))
    assert out and out[0]["status"] == "failed"
    assert "NullReferenceException" in out[0]["message"]
    assert out[0]["name"] == "NS.Tests.CalcTests.Should_Add"


def test_xunit_xml_parser(tmp_path):
    xml = dedent(
        """\
    <assemblies>
      <collection>
        <test name="NS.Tests.Foo.Bar" type="NS.Tests.Foo" method="Bar" result="Fail">
          <failure><message>oops</message></failure>
        </test>
        <test name="NS.Tests.Foo.Baz" type="NS.Tests.Foo" method="Baz" result="Skip"/>
      </collection>
    </assemblies>
    """
    )
    p = _write(tmp_path, "xu.xml", xml)
    out = XUnitXMLParser().load(str(p))
    m = {t["name"]: t for t in out}
    assert m["NS.Tests.Foo.Bar"]["status"] == "failed"
    assert m["NS.Tests.Foo.Baz"]["status"] == "skipped"
    assert "oops" in m["NS.Tests.Foo.Bar"]["message"]


def test_universal_parser_delegates_to_junit(tmp_path):
    xml = """<testsuite><testcase classname="A" name="t"/></testsuite>"""
    p = _write(tmp_path, "u1.xml", xml)
    out = UniversalXMLParser().load(str(p))
    assert out and out[0]["name"] == "A::t"


def test_universal_parser_delegates_to_xunit(tmp_path):
    xml = """<assemblies><collection><test name="X" result="Pass"/></collection></assemblies>"""
    p = _write(tmp_path, "u2.xml", xml)
    out = UniversalXMLParser().load(str(p))
    assert out and out[0]["name"] == "X"


def test_universal_parser_generic_scans(tmp_path):
    xml = """<root><item name="Alpha" status="failed"><message>bad</message></item></root>"""
    p = _write(tmp_path, "u3.xml", xml)
    out = UniversalXMLParser().load(str(p))
    assert out and out[0]["name"] == "Alpha" and out[0]["status"] == "failed"


def test_get_parser_prefers_best_probe_and_fallback_universal(tmp_path, monkeypatch):
    xml = "<root/>"
    p = _write(tmp_path, "choose.xml", xml)

    class BadProbeParser(TestLogParser):
        PRIORITY = 1

        @classmethod
        def can_parse(cls, lang, path):
            return path.endswith("choose.xml")

        def load(self, log_path):
            raise RuntimeError("boom")

    try:
        parser = TestLogParser.get_parser("java", str(p))
        assert isinstance(parser, UniversalXMLParser)
    finally:
        TestLogParser.registry = [
            c for c in TestLogParser.registry if c is not BadProbeParser
        ]


def test_iter_log_files_on_file_and_directory(tmp_path):
    f = _write(tmp_path, "only.json", "{}")
    got = list(_iter_log_files(str(f)))
    assert got == [str(f)]

    _write(tmp_path, "a.xml", "<root/>")
    _write(tmp_path, "b.trx", "<TestRun/>")
    _write(tmp_path, "c.json", "[]")
    names = set(Path(x).name for x in _iter_log_files(str(tmp_path)))
    assert {"a.xml", "b.trx", "c.json", "only.json"}.issubset(names)


def test_load_test_logs_mixed_sources_and_errors(tmp_path, capsys, monkeypatch):
    pjson = _write(
        tmp_path,
        "rep.json",
        json.dumps({"tests": [{"nodeid": "t::a", "outcome": "passed"}]}),
    )

    pxml = _write(
        tmp_path, "j.xml", "<testsuite><testcase classname='C' name='m'/></testsuite>"
    )

    class ExplodingParser(TestLogParser):
        PRIORITY = 2

        @classmethod
        def can_parse(cls, lang, path):
            return path.endswith("boom.xml")

        def load(self, log_path):
            raise RuntimeError("explode")

    pboom = _write(tmp_path, "boom.xml", "<root/>")

    try:
        out = load_test_logs("python", str(tmp_path))
        names = [o["name"] for o in out]
        assert "t::a" in names
        assert "C::m" in names
        printed = capsys.readouterr().out
        assert ("Failed to parse test logs" in printed) or (
            "No testcases parsed from" in printed
        )
    finally:
        TestLogParser.registry = [
            c for c in TestLogParser.registry if c is not ExplodingParser
        ]
