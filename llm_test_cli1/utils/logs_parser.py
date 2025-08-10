# --- file: utils/log_parsers.py ---
import json
import re
import xml.etree.ElementTree as ET
from typing import List, Dict, Type


class TestLogParser:
    """Base interface for test log parsers."""
    registry: List[Type["TestLogParser"]] = []

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        TestLogParser.registry.append(cls)

    def load(self, log_path: str) -> List[Dict]:
        raise NotImplementedError()

    @classmethod
    def can_parse(cls, lang: str, log_path: str) -> bool:
        raise NotImplementedError()

    @classmethod
    def get_parser(cls, lang: str, log_path: str) -> "TestLogParser":
        for parser_cls in cls.registry:
            if parser_cls.can_parse(lang, log_path):
                return parser_cls()
        raise ValueError(f"No parser for lang={lang!r}, file={log_path!r}")


class PytestJSONParser(TestLogParser):
    """Parses pytest --json-report output."""
    @classmethod
    def can_parse(cls, lang: str, log_path: str) -> bool:
        return lang.lower() == "python" and log_path.lower().endswith(".json")

    def load(self, log_path: str) -> List[Dict]:
        with open(log_path, encoding="utf-8") as f:
            data = json.load(f)
        out: List[Dict] = []
        for t in data.get("tests", []):
            out.append({
                "name":    t.get("nodeid", ""),
                "status":  t.get("outcome", "").lower(),
                "message": t.get("longrepr", "") or ""
            })
        return out


class GenericJSONParser(TestLogParser):
    """Fallback JSON parser for list[{'name','status','message'}]."""
    @classmethod
    def can_parse(cls, lang: str, log_path: str) -> bool:
        return log_path.lower().endswith(".json")

    def load(self, log_path: str) -> List[Dict]:
        with open(log_path, encoding="utf-8") as f:
            data = json.load(f)
        out: List[Dict] = []
        if isinstance(data, list):
            for t in data:
                out.append({
                    "name":    t.get("name", ""),
                    "status":  t.get("status", "").lower(),
                    "message": t.get("message", "")
                })
        return out


class JUnitXMLParser(TestLogParser):
    """Parses JUnit‐style XML (JUnit/Surefire, pytest --junitxml, NUnit JUnit‐logger, …)."""
    @classmethod
    def can_parse(cls, lang: str, log_path: str) -> bool:
        return log_path.lower().endswith(".xml")

    def load(self, log_path: str) -> List[Dict]:
        tree = ET.parse(log_path)
        root = tree.getroot()

        # — strip all namespace prefixes if any —
        for el in root.iter():
            if isinstance(el.tag, str) and el.tag.startswith("{"):
                el.tag = re.sub(r"^\{.*?\}", "", el.tag)

        out: List[Dict] = []
        for tc in root.findall(".//testcase"):
            classname = tc.get("classname", "")
            testname  = tc.get("name", "")
            fullname  = f"{classname}::{testname}" if classname else testname

            # scan direct children for failure/error/skipped
            status = "passed"
            message = ""
            for child in list(tc):
                tag = child.tag.lower()
                if tag in ("failure", "error"):
                    status = "failed"
                    message = (child.text or "").strip()
                    break
                if tag == "skipped":
                    status = "skipped"
                    message = (child.text or "").strip()
                    break

            out.append({"name": fullname, "status": status, "message": message})

        return out


class TRXXMLParser(TestLogParser):
    """Parses .trx files from MSTest / xUnit / dotnet test."""
    @classmethod
    def can_parse(cls, lang: str, log_path: str) -> bool:
        return log_path.lower().endswith(".trx")

    def load(self, log_path: str) -> List[Dict]:
        tree = ET.parse(log_path)
        root = tree.getroot()
        out: List[Dict] = []
        for tc in root.findall(".//UnitTestResult"):
            name    = tc.get("testName", "")
            outcome = (tc.get("outcome", "") or "").lower()
            if outcome == "failed":
                status = "failed"
                msg_el = tc.find(".//ErrorInfo/Message") or tc.find(".//Message")
                message = (msg_el.text or "").strip() if msg_el is not None else ""
            elif outcome in ("notexecuted", "skipped"):
                status, message = "skipped", ""
            else:
                status, message = "passed", ""
            out.append({"name": name, "status": status, "message": message})
        return out
