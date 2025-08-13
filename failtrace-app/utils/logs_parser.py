import os
import glob
import json
import re
import xml.etree.ElementTree as ET
from typing import List, Dict, Type, Optional, Iterable, Tuple


# ---------------------------
# Helpers
# ---------------------------

# پاکسازی کدهای ANSI: هم ESC واقعی، هم شکل هشداری '#x1B[...]'
_ANSI_RE = re.compile(r"\x1B\[[0-9;]*[A-Za-z]")  # \x1b[...m
_ANSI_HASH_RE = re.compile(r"#x1B\[[0-9;]*[A-Za-z]")  # #x1B[...m


def _strip_xml_namespaces(root: ET.Element) -> None:
    """In-place: remove any '{ns}tag' namespace prefixes so we can use simple XPath."""
    for el in root.iter():
        if isinstance(el.tag, str) and el.tag.startswith("{"):
            el.tag = re.sub(r"^\{.*?\}", "", el.tag)


def _safe_parse_xml(path: str) -> Optional[ET.Element]:
    try:
        tree = ET.parse(path)
        root = tree.getroot()
        _strip_xml_namespaces(root)
        return root
    except Exception:
        return None


def _clean_text(s: str) -> str:
    """Trim + strip ANSI (ESC and '#x1B' forms)."""
    s = (s or "").strip()
    s = _ANSI_RE.sub("", s)
    s = _ANSI_HASH_RE.sub("", s)
    return s


def _text_of(el: Optional[ET.Element]) -> str:
    """Safe inner text of an XML element (stripped & ANSI cleaned)."""
    if el is None:
        return ""
    return _clean_text(el.text or "")


def _attr(el: Optional[ET.Element], name: str) -> str:
    """Safe attribute get (stripped & ANSI cleaned)."""
    if el is None:
        return ""
    try:
        return _clean_text(el.get(name) or "")
    except Exception:
        return ""


def _normalize_record(name: str, status: str, message: str) -> Dict:
    return {
        "name": _clean_text(name),
        "status": _clean_text(status).lower(),
        "message": _clean_text(message),
    }


# ---------------------------
# Base Parser
# ---------------------------


class TestLogParser:
    """Base interface for test log parsers."""

    registry: List[Type["TestLogParser"]] = []
    PRIORITY = 100  # smaller = more specific

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        TestLogParser.registry.append(cls)

    def load(self, log_path: str) -> List[Dict]:
        raise NotImplementedError()

    @classmethod
    def can_parse(cls, lang: str, log_path: str) -> bool:
        raise NotImplementedError()

    @classmethod
    def _probe_count(cls, lang: str, log_path: str) -> Tuple[int, Optional[List[Dict]]]:
        """
        Try to parse and return (count, data?) for ranking. Never raise.
        """
        try:
            if not cls.can_parse(lang, log_path):
                return 0, None
            data = cls().load(log_path)
            cnt = sum(1 for it in (data or []) if (it.get("name") or "").strip())
            return cnt, data
        except Exception:
            return 0, None

    @classmethod
    def get_parser(cls, lang: str, log_path: str) -> "TestLogParser":
        """
        Choose the parser that yields the largest number of testcases.
        Ties are broken by lower PRIORITY (more specific parser).
        """
        candidates = [p for p in cls.registry if p.can_parse(lang, log_path)]
        if not candidates:
            raise ValueError(f"No parser for lang={lang!r}, file={log_path!r}")

        best_cls: Optional[Type["TestLogParser"]] = None
        best_count = -1
        best_prio = 10**9

        for pc in candidates:
            cnt, _ = pc._probe_count(lang, log_path)
            pr = getattr(pc, "PRIORITY", 100)
            if cnt > best_count or (cnt == best_count and pr < best_prio):
                best_cls = pc
                best_count = cnt
                best_prio = pr

        # Safety: if all failed to parse, fall back to the most universal option if present
        if best_cls is None or best_count <= 0:
            for pc in candidates:
                if pc.__name__ == "UniversalXMLParser":
                    best_cls = pc
                    break

        if best_cls is None:
            best_cls = candidates[0]

        return best_cls()


# ---------------------------
# JSON parsers (pytest & generic)
# ---------------------------


class PytestJSONParser(TestLogParser):
    """Parses pytest --json-report output."""

    PRIORITY = 10

    @classmethod
    def can_parse(cls, lang: str, log_path: str) -> bool:
        return log_path.lower().endswith(".json")

    def load(self, log_path: str) -> List[Dict]:
        with open(log_path, encoding="utf-8") as f:
            data = json.load(f)

        out: List[Dict] = []
        tests = []
        if isinstance(data, dict):
            tests = data.get("tests") or data.get("report", {}).get("tests", []) or []
        elif isinstance(data, list):
            tests = data

        for t in tests:
            if not isinstance(t, dict):
                continue
            name = (t.get("nodeid") or t.get("name") or "").strip()
            status = (t.get("outcome") or t.get("status") or "").strip().lower()
            message = (t.get("longrepr") or t.get("message") or "").strip()
            if name:
                out.append(_normalize_record(name, status, message))
        return out


class GenericJSONParser(TestLogParser):
    """Fallback JSON parser for list[{'name','status','message'}]."""

    PRIORITY = 90

    @classmethod
    def can_parse(cls, lang: str, log_path: str) -> bool:
        return log_path.lower().endswith(".json")

    def load(self, log_path: str) -> List[Dict]:
        with open(log_path, encoding="utf-8") as f:
            data = json.load(f)
        out: List[Dict] = []
        if isinstance(data, list):
            for t in data:
                if not isinstance(t, dict):
                    continue
                out.append(
                    _normalize_record(
                        t.get("name") or "",
                        t.get("status") or "",
                        t.get("message") or "",
                    )
                )
        return out


# ---------------------------
# XML parsers
# ---------------------------


class XUnitXMLParser(TestLogParser):
    """
    .NET xUnit logger:
      <assemblies><assembly><collection><test ... result="Pass|Fail|Skip">...</test>...</collection>...
    """

    PRIORITY = 5

    @classmethod
    def can_parse(cls, lang: str, log_path: str) -> bool:
        if not log_path.lower().endswith(".xml"):
            return False
        root = _safe_parse_xml(log_path)
        if root is None:
            return False
        if (root.tag or "").lower() == "assemblies":
            return True
        return (root.find(".//test") is not None) and (
            root.find(".//collection") is not None
        )

    def load(self, log_path: str) -> List[Dict]:
        root = _safe_parse_xml(log_path)
        if root is None:
            return []
        out: List[Dict] = []
        for test in root.findall(".//test"):
            name_attr = _attr(test, "name")
            typ = _attr(test, "type")
            method = _attr(test, "method")
            fullname = name_attr or (
                f"{typ}.{method}".strip(".") if (typ or method) else ""
            )
            if not fullname:
                continue

            result = _attr(test, "result").lower()
            status = "passed"
            if result.startswith("fail"):
                status = "failed"
            elif result.startswith("skip"):
                status = "skipped"

            msg = ""
            failure_el = test.find("failure") or test.find(".//failure")
            if failure_el is not None:
                msg_el = failure_el.find("message") or failure_el.find(".//message")
                msg = (
                    _attr(msg_el, "message") or _text_of(msg_el) or _text_of(failure_el)
                )

            out.append(_normalize_record(fullname, status, msg))
        return out


class NUnitV3XMLParser(TestLogParser):
    """
    NUnit v3:
      <test-run> ... <test-suite> ... <test-case fullname="..." name="..." result="Passed|Failed|Skipped"> ...
    """

    PRIORITY = 12

    @classmethod
    def can_parse(cls, lang: str, log_path: str) -> bool:
        if not log_path.lower().endswith(".xml"):
            return False
        root = _safe_parse_xml(log_path)
        if root is None:
            return False
        tag = (root.tag or "").lower()
        if tag in {"test-run", "test-suite", "testsuite"}:
            return root.find(".//test-case") is not None
        return False

    def load(self, log_path: str) -> List[Dict]:
        root = _safe_parse_xml(log_path)
        if root is None:
            return []
        out: List[Dict] = []
        for tc in root.findall(".//test-case"):
            fullname = _attr(tc, "fullname")
            if not fullname:
                clsname = _attr(tc, "classname")
                name = _attr(tc, "name")
                fullname = f"{clsname}.{name}".strip(".")

            result = _attr(tc, "result").lower()
            status = "passed"
            if result.startswith("fail"):
                status = "failed"
            elif result.startswith("skip") or result in {"skipped", "inconclusive"}:
                status = "skipped"

            msg = ""
            failure_el = tc.find("failure") or tc.find(".//failure")
            if failure_el is not None:
                msg_el = failure_el.find("message") or failure_el.find(".//message")
                msg = (
                    _attr(msg_el, "message") or _text_of(msg_el) or _text_of(failure_el)
                )

            out.append(_normalize_record(fullname, status, msg))
        return out


class TRXXMLParser(TestLogParser):
    """
    MSTest/xUnit/NUnit via VSTest (.trx):
      map UnitTestResult -> UnitTest to get FullyQualifiedName
    """

    PRIORITY = 15

    @classmethod
    def can_parse(cls, lang: str, log_path: str) -> bool:
        if not log_path.lower().endswith(".trx"):
            return False
        root = _safe_parse_xml(log_path)
        if root is None:
            return False
        return (root.find(".//UnitTestResult") is not None) or (
            root.find(".//UnitTest") is not None
        )

    def load(self, log_path: str) -> List[Dict]:
        root = _safe_parse_xml(log_path)
        if root is None:
            return []
        id_to_fqn: Dict[str, str] = {}
        for ut in root.findall(".//UnitTest"):
            tid = _attr(ut, "id") or _attr(ut, "Id")
            tm = ut.find("./TestMethod")
            cls = _attr(tm, "className")
            name = _attr(tm, "name")
            fqn = f"{cls}.{name}".strip(".") if (cls or name) else ""
            if tid and fqn:
                id_to_fqn[tid] = fqn

        out: List[Dict] = []
        for r in root.findall(".//UnitTestResult"):
            tid = _attr(r, "testId")
            name = id_to_fqn.get(tid) or _attr(r, "testName")
            outcome = _attr(r, "outcome").lower()

            if outcome == "failed":
                status = "failed"
                msg_el = r.find(".//Message") or r.find(".//ErrorInfo/Message")
                message = _text_of(msg_el)
            elif outcome in {"notexecuted", "skipped", "inconclusive"}:
                status, message = "skipped", ""
            else:
                status, message = "passed", ""

            if name:
                out.append(_normalize_record(name, status, message))
        return out


class JUnitXMLParser(TestLogParser):
    """Parses JUnit‐style XML (JUnit/Surefire, pytest --junitxml, NUnit JUnit‐logger, …)"""

    @classmethod
    def can_parse(cls, lang: str, log_path: str) -> bool:
        return log_path.lower().endswith(".xml")

    def load(self, log_path: str) -> List[Dict]:
        tree = ET.parse(log_path)
        root = tree.getroot()

        for el in root.iter():
            if isinstance(el.tag, str) and el.tag.startswith("{"):
                el.tag = re.sub(r"^\{.*?\}", "", el.tag)

        out: List[Dict] = []
        for tc in root.findall(".//testcase"):
            classname = tc.get("classname", "")
            testname = tc.get("name", "")
            fullname = f"{classname}::{testname}" if classname else testname

            status = "passed"
            message_parts: List[str] = []

            for child in list(tc):
                tag = child.tag.lower()
                if tag in ("failure", "error"):
                    status = "failed"
                    if child.get("message"):
                        message_parts.append(child.get("message", ""))
                    if child.text:
                        message_parts.append(child.text.strip())
                    msg_el = child.find("message") or child.find(".//message")
                    if msg_el is not None:
                        if msg_el.get("message"):
                            message_parts.append(msg_el.get("message", ""))
                        if msg_el.text:
                            message_parts.append(msg_el.text.strip())
                    break
                if tag == "skipped":
                    status = "skipped"
                    if child.get("message"):
                        message_parts.append(child.get("message", ""))
                    if child.text:
                        message_parts.append(child.text.strip())
                    break

            full_message = _clean_text("\n".join(m for m in message_parts if m).strip())
            out.append({"name": fullname, "status": status, "message": full_message})

        return out


class UniversalXMLParser(TestLogParser):
    """
    Very tolerant fallback for ANY XML-like test report.
    Heuristics:
      - If has <testcase> → parse like JUnit
      - elif has <test-case> → parse like NUnit
      - elif has UnitTestResult/UnitTest → parse like TRX
      - elif has <test> with result → parse like xUnit logger
      - else: generic scans
    """

    PRIORITY = 99

    @classmethod
    def can_parse(cls, lang: str, log_path: str) -> bool:
        return (
            log_path.lower().endswith((".xml", ".trx"))
            and _safe_parse_xml(log_path) is not None
        )

    def load(self, log_path: str) -> List[Dict]:
        root = _safe_parse_xml(log_path)
        if root is None:
            return []

        # Prefer specialized shapes first
        if root.find(".//testcase") is not None:
            return JUnitXMLParser().load(log_path)
        if root.find(".//test-case") is not None:
            return NUnitV3XMLParser().load(log_path)
        if (root.find(".//UnitTestResult") is not None) or (
            root.find(".//UnitTest") is not None
        ):
            return TRXXMLParser().load(log_path)
        if (root.find(".//test") is not None) and (
            root.find(".//collection") is not None
        ):
            return XUnitXMLParser().load(log_path)

        out: List[Dict] = []

        # 1) Any *testcase/test-case* elements
        for el in root.iter():
            tag = (el.tag or "").lower()
            if tag.endswith("testcase") or tag.endswith("test-case"):
                classname = _attr(el, "classname")
                name = _attr(el, "name")
                fullname = (
                    f"{classname}.{name}".strip(".") if (classname or name) else name
                )
                status = (
                    _attr(el, "result") or _attr(el, "status") or "passed"
                ).lower()
                if status in {"", "success"}:
                    status = "passed"
                message = ""
                for child_name in ("failure", "error", "skipped"):
                    ch = el.find(child_name) or el.find(f".//{child_name}")
                    if ch is not None:
                        if child_name == "skipped":
                            status = "skipped"
                        else:
                            status = "failed"
                        message = _attr(ch, "message") or _text_of(ch)
                        break
                if fullname:
                    out.append(_normalize_record(fullname, status, message))
        if out:
            return out

        # 2) xunit-like <test result="...">
        for el in root.iter():
            if (el.tag or "").lower().endswith("test"):
                result = _attr(el, "result").lower()
                if result:
                    typ = _attr(el, "type")
                    method = _attr(el, "method")
                    name_attr = _attr(el, "name")
                    fullname = name_attr or (
                        f"{typ}.{method}".strip(".") if (typ or method) else ""
                    )
                    if not fullname:
                        continue
                    status = "passed"
                    if result.startswith("fail"):
                        status = "failed"
                    elif result.startswith("skip"):
                        status = "skipped"
                    msg = ""
                    failure_el = el.find("failure") or el.find(".//failure")
                    if failure_el is not None:
                        msg = _attr(failure_el, "message") or _text_of(failure_el)
                    out.append(_normalize_record(fullname, status, msg))
        if out:
            return out

        # 3) Totally generic: any element with 'name'/'fullname'
        for el in root.iter():
            name = _attr(el, "fullname") or _attr(el, "name")
            if not name:
                continue
            status = _attr(el, "status") or _attr(el, "result")
            msg = ""
            for cand in ("message", "failure", "error"):
                ch = el.find(cand) or el.find(f".//{cand}")
                if ch is not None:
                    msg = _attr(ch, "message") or _text_of(ch)
                    if not status:
                        status = "failed" if cand in {"failure", "error"} else status
                    break
            out.append(_normalize_record(name, status or "passed", msg))
        return out


# ---------------------------
# Public convenience
# ---------------------------


def _iter_log_files(path: str) -> Iterable[str]:
    """Yield one or many log files. If 'path' is a dir, collect common XML/TRX/JSON files recursively."""
    if os.path.isdir(path):
        patterns = ["**/*.xml", "**/*.trx", "**/*.json"]
        yielded = set()
        for pat in patterns:
            for p in glob.iglob(os.path.join(path, pat), recursive=True):
                if os.path.isfile(p) and p not in yielded:
                    yielded.add(p)
                    yield p
    else:
        yield path


def load_test_logs(lang: str, log_path: str) -> List[Dict]:
    """
    Unified entrypoint:
      - Detect appropriate parser based on language + file content
      - Supports file OR directory; merges all results
      - Returns list of {'name','status','message'}
    """
    results: List[Dict] = []
    for file_path in _iter_log_files(log_path):
        try:
            parser = TestLogParser.get_parser(lang, file_path)
        except ValueError:
            # Skip unknown files silently; continue with others
            continue
        try:
            parsed = parser.load(file_path)
            if not parsed:
                print(
                    f"[!] No testcases parsed from {file_path} using {parser.__class__.__name__}"
                )
            results.extend(parsed)
        except Exception as e:
            print(
                f"[!] Failed to parse test logs ({file_path}) with {parser.__class__.__name__}: {e}"
            )
            continue
    return results
