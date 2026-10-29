import pytest

from lfmap_core import ToolError
from lfmap_core.naming import shorten_filename


def test_short_name_is_unchanged():
    assert shorten_filename("report.pdf") == "report.pdf"


def test_name_at_the_limit_is_unchanged():
    name = "a" * 251 + ".pdf"
    assert shorten_filename(name) == name


def test_short_name_keeps_trailing_dot():
    assert shorten_filename("a.", max_length=5) == "a."


def test_keeps_extension():
    result = shorten_filename("x" * 300 + ".pdf")
    assert len(result) == 255
    assert result == "x" * 251 + ".pdf"


def test_without_extension():
    assert shorten_filename("y" * 300) == "y" * 255


def test_long_suffix_is_not_an_extension():
    name = "z" * 250 + "." + "e" * 20
    assert shorten_filename(name) == name[:255]


def test_dot_file_is_not_an_extension():
    assert shorten_filename(".abcdefgh", max_length=4) == ".abc"


@pytest.mark.parametrize(
    ("name", "max_length", "expected"),
    [
        ("abcdef.txt", 8, "abcd.txt"),
        ("abcdef.txt", 5, "a.txt"),
        ("abcdef.txt", 4, "abcd"),
        ("abcdef.txt", 3, "abc"),
        ("a.tar.gz", 6, "a.t.gz"),
        ("Báo cáo tháng 10.docx", 12, "Báo cáo.docx"),
        ("ab. .cdef", 4, "ab"),
        ("abc...defgh", 6, "abc"),
        ("a" * 10, 1, "a"),
    ],
)
def test_max_length(name, max_length, expected):
    assert shorten_filename(name, max_length=max_length) == expected


@pytest.mark.parametrize(("name", "max_length"), [("...abc", 2), (". .x", 1)])
def test_rejects_empty_result(name, max_length):
    with pytest.raises(ToolError) as info:
        shorten_filename(name, max_length=max_length)
    assert info.value.code == "invalid_input"
    assert info.value.details == {"name": name}


@pytest.mark.parametrize("value", [None, 7, b"a.txt"])
def test_non_str_name(value):
    with pytest.raises(ToolError) as info:
        shorten_filename(value)
    assert info.value.code == "invalid_input"
    assert info.value.details == {"name": repr(value)}


@pytest.mark.parametrize("max_length", [0, -1, True, 2.5, "8", None])
def test_bad_max_length(max_length):
    with pytest.raises(ToolError) as info:
        shorten_filename("abc.txt", max_length=max_length)
    assert info.value.code == "invalid_input"
    assert info.value.details == {"max_length": repr(max_length)}
