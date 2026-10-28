import pytest

from lfmap_core import ToolError
from lfmap_core.versions import parse_version, require_core_version


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("0.1.0", (0, 1, 0)),
        ("0.2.0", (0, 2, 0)),
        ("1.10.3", (1, 10, 3)),
        ("12.0.99", (12, 0, 99)),
        ("01.2.3", (1, 2, 3)),
    ],
)
def test_parse_version(text, expected):
    assert parse_version(text) == expected


def test_parse_version_returns_plain_ints():
    parts = parse_version("2.3.4")
    assert type(parts) is tuple
    assert all(type(part) is int for part in parts)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "1",
        "1.2",
        "1.2.3.4",
        "v1.2.3",
        "1.2.3-rc1",
        "1.2.3+build",
        " 1.2.3",
        "1.2.3 ",
        "1.2.3\n",
        "1..3",
        "1.2.x",
        "-1.2.3",
        "+1.2.3",
        "1.2.３",
        "١.2.3",
    ],
)
def test_parse_version_rejects(text):
    with pytest.raises(ToolError) as caught:
        parse_version(text)
    assert caught.value.code == "invalid_input"
    assert caught.value.details == {"version": text}


@pytest.mark.parametrize("value", [None, 1, 1.2, b"1.2.3", ["1", "2", "3"]])
def test_parse_version_rejects_non_strings(value):
    with pytest.raises(ToolError) as caught:
        parse_version(value)
    assert caught.value.code == "invalid_input"
    assert caught.value.details == {"version": repr(value)}


@pytest.mark.parametrize(
    ("required", "current"),
    [
        ("0.1.0", "0.2.0"),
        ("0.2.0", "0.2.0"),
        ("0.2.0", "0.10.0"),
        ("0.9.9", "1.0.0"),
        ("1.2.3", "1.2.10"),
    ],
)
def test_require_core_version_accepts(required, current):
    assert require_core_version("knowledge", required, current) is None


@pytest.mark.parametrize(
    ("required", "current"),
    [
        ("0.3.0", "0.2.0"),
        ("0.10.0", "0.9.0"),
        ("1.0.0", "0.99.99"),
        ("0.2.1", "0.2.0"),
    ],
)
def test_require_core_version_refuses_old_core(required, current):
    with pytest.raises(ToolError) as caught:
        require_core_version("knowledge", required, current)
    error = caught.value
    assert error.code == "invalid_input"
    assert error.message == f"Plugin 'knowledge' needs lfmap-core {required} or newer, found {current}"
    assert error.details == {"plugin": "knowledge", "min_core_version": required, "core_version": current}


def test_require_core_version_bad_required_names_the_value():
    with pytest.raises(ToolError) as caught:
        require_core_version("echo", "0.2", "0.2.0")
    assert caught.value.code == "invalid_input"
    assert caught.value.details == {"version": "0.2"}


def test_require_core_version_bad_current_names_the_value():
    with pytest.raises(ToolError) as caught:
        require_core_version("echo", "0.1.0", "0.2.0.dev1")
    assert caught.value.code == "invalid_input"
    assert caught.value.details == {"version": "0.2.0.dev1"}
