import pytest

from failtrace.utils.normalize import (
    _ensure_python_filepath,
    _split_name,
    normalize_test_name,
)


@pytest.mark.parametrize(
    "inp, expected",
    [
        ("", "unknown.py"),
        (None, "unknown.py"),
        ("   ", "unknown.py"),
    ],
)
def test_ensure_python_filepath_empty_and_nonstring(inp, expected):
    assert _ensure_python_filepath(inp) == expected


@pytest.mark.parametrize(
    "inp, expected",
    [
        ("tests.test_math", "tests/test_math.py"),
        ("module", "module.py"),
        ("tests/test_math.py", "tests/test_math.py"),
        (r"tests\test_math.py", "tests/test_math.py"),
        ("//foo///bar////baz.py", "foo/bar/baz.py"),
        ("   /a/b/c.py   ", "a/b/c.py"),
        ("a.b/c", "a.b/c.py"),
        ("a.b", "a/b.py"),
    ],
)
def test_ensure_python_filepath_various(inp, expected):
    assert _ensure_python_filepath(inp) == expected


@pytest.mark.parametrize(
    "raw, path_part, extra",
    [
        ("pkg.Class.test", "pkg.Class", ["test"]),
        ("pkg.sub.Class.testX", "pkg.sub.Class", ["testX"]),
        ("path::func", "path", ["func"]),
        ("path::Class::method", "path", ["Class", "method"]),
        ("Class#method", "Class", ["method"]),
        ("Class#   ", "Class", []),
        (r"a\b\c#foo", "a/b/c", ["foo"]),
        ("weird", "weird", []),
        ("a.b.c", "a.b", ["c"]),
        (" a.b.c  ", "a.b", ["c"]),
    ],
)
def test_split_name_cases(raw, path_part, extra):
    p, e = _split_name(raw)
    assert p == path_part
    assert e == extra


@pytest.mark.parametrize(
    "raw, expected_start",
    [
        ("tests.test_math.test_ok", "tests/test_math.py::test_ok"),
        (r"tests\test_math.py::test_ok", "tests/test_math.py::test_ok"),
        (" tests/test_api.py :: test_call ", "tests/test_api.py::test_call"),
        ("module#func", "module.py::func"),
        ("module", "module.py"),
    ],
)
def test_normalize_python_names(raw, expected_start):
    out = normalize_test_name(raw, "python")
    assert out.startswith(expected_start)
    assert "::" in out or out.endswith(".py")


@pytest.mark.parametrize("raw", ["", None])
def test_normalize_python_empty_like_returns_as_is(raw):
    assert normalize_test_name(raw, "python") is raw


def test_normalize_nonstring_returns_as_is():
    assert normalize_test_name(123, "python") == 123


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("com.acme.util.RangeTest#clamp", "RangeTest.java::RangeTest::clamp"),
        ("com.acme.util.RangeTest.clamp", "RangeTest.java::RangeTest::clamp"),
        ("src/main/java/com/acme/AppTest.testMain", "AppTest.java::AppTest::testMain"),
        (
            "src/test/java/com/acme/util/CalcTest.java#sum",
            "CalcTest.java::CalcTest::sum",
        ),
        (
            "tests/java/com/acme/ThingTest.testA",
            "ThingTest.java::ThingTest::testA",
        ),  # ignores tests/java
    ],
)
def test_normalize_java_names(raw, expected):
    out = normalize_test_name(raw, "java")
    assert out == expected


@pytest.mark.parametrize(
    "raw, expected_file",
    [
        ("a/b/c/Demo.java#run", "Demo.java"),
        ("a.b.c.Demo.testRun", "Demo.java"),
        ("target/classes/com/acme/Qux.test", "Qux.java"),
    ],
)
def test_normalize_java_filename_component(raw, expected_file):
    out = normalize_test_name(raw, "java")
    assert out.split("::", 1)[0] == expected_file
    assert "::" in out


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("MyProj.Tests.CalcTests.TestSum", "CalcTests.cs::CalcTests::TestSum"),
        ("tests/CalcTests.cs#TestSum", "CalcTests.cs::CalcTests::TestSum"),
        (
            r"src\test\csharp\NS\Tests\FooBarTests.TestA",
            "FooBarTests.cs::FooBarTests::TestA",
        ),
        ("build/bin/Any/AdderTests.testAdd", "AdderTests.cs::AdderTests::testAdd"),
    ],
)
def test_normalize_csharp_names(raw, expected):
    out = normalize_test_name(raw, "csharp")
    assert out == expected


@pytest.mark.parametrize(
    "raw, expected_prefix",
    [
        ("pkg.MyClass.testX", "MyClass"),
        ("src/main/java/com/acme/Alpha.run", "Alpha"),
        ("tests/Bravo.run", "Bravo"),
    ],
)
def test_normalize_unknown_language(raw, expected_prefix):
    out = normalize_test_name(raw, "go")
    assert out.startswith(expected_prefix)
    parts = out.split("::")
    assert len(parts) >= 1
    if len(parts) > 1:
        assert parts[1] == expected_prefix


@pytest.mark.parametrize(
    "raw, lang",
    [
        ("src/test/java/com/acme/util//RangeTest.clamp", "java"),
        ("tests///math//MathTest.testA", "java"),
        ("tests....strange...Name.test", "java"),
        ("tests\\java\\com\\acme\\Thingy#go", "java"),
        ("\\\\server\\share\\Pkg.Class.Method", "csharp"),
    ],
)
def test_normalize_handles_odd_separators(raw, lang):
    out = normalize_test_name(raw, lang)
    assert isinstance(out, str) and "::" in out
    assert "//" not in out
    assert "  " not in out


def test_normalize_python_multiple_colons_and_spaces():
    raw = "  tests/test_service.py  ::   TestAPI  ::  test_call   "
    out = normalize_test_name(raw, "python")
    assert out.startswith("tests/test_service.py::")
    parts = out.split("::")
    assert parts[1] == "TestAPI"
    assert parts[2] == "test_call"
