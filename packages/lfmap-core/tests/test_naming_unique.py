import unicodedata

import pytest

from lfmap_core import ToolError
from lfmap_core.naming import split_extension, unique_name


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("report.pdf", ("report", ".pdf")),
        ("a.tar.gz", ("a.tar", ".gz")),
        ("README", ("README", "")),
        (".env", (".env", "")),
        ("..env", (".", ".env")),
        ("a.", ("a", ".")),
        ("x.abcdefghij", ("x", ".abcdefghij")),
        ("x.abcdefghijk", ("x.abcdefghijk", "")),
        ("Báo cáo.docx", ("Báo cáo", ".docx")),
        ("", ("", "")),
    ],
)
def test_split_extension(name, expected):
    assert split_extension(name) == expected


@pytest.mark.parametrize("value", [None, 7, b"a.txt", ["a.txt"]])
def test_split_extension_non_str(value):
    with pytest.raises(ToolError) as info:
        split_extension(value)
    assert info.value.code == "invalid_input"
    assert info.value.details == {"name": repr(value)}


@pytest.mark.parametrize(
    ("name", "existing", "expected"),
    [
        ("a.txt", [], "a.txt"),
        ("a.txt", ["b.txt"], "a.txt"),
        ("a.txt", ["a.txt"], "a (2).txt"),
        ("a.txt", ["A.TXT"], "a (2).txt"),
        ("A.TXT", ["a.txt"], "A (2).TXT"),
        ("a.txt", ["a.txt", "a (2).txt"], "a (3).txt"),
        ("a.txt", ["a.txt", "a (3).txt"], "a (2).txt"),
        ("a.txt", ["a.txt", "A (2).TXT", "a (3).txt"], "a (4).txt"),
        ("a.tar.gz", ["a.tar.gz"], "a.tar (2).gz"),
        ("README", ["readme"], "README (2)"),
        (".env", [".env"], ".env (2)"),
        ("x.abcdefghijk", ["x.abcdefghijk"], "x.abcdefghijk (2)"),
        ("Straße.txt", ["STRASSE.TXT"], "Straße (2).txt"),
        ("a (2).txt", ["a (2).txt"], "a (2) (2).txt"),
    ],
)
def test_unique_name(name, existing, expected):
    assert unique_name(name, existing) == expected


def test_unique_name_reads_a_generator_once():
    taken = (n for n in ["x.md", "x (2).md"])
    assert unique_name("x.md", taken) == "x (3).md"


def test_unique_name_accepts_a_set():
    assert unique_name("x.md", {"x.md"}) == "x (2).md"


def test_unique_name_compares_nfc():
    existing = [unicodedata.normalize("NFD", "hồ sơ.pdf")]
    result = unique_name(unicodedata.normalize("NFC", "hồ sơ.pdf"), existing)
    assert result == unicodedata.normalize("NFC", "hồ sơ (2).pdf")


def test_unique_name_returns_nfc_when_free():
    decomposed = unicodedata.normalize("NFD", "Hồ sơ.pdf")
    assert unique_name(decomposed, []) == unicodedata.normalize("NFC", "Hồ sơ.pdf")


@pytest.mark.parametrize("value", [None, 3, b"a.txt"])
def test_unique_name_non_str(value):
    with pytest.raises(ToolError) as info:
        unique_name(value, [])
    assert info.value.code == "invalid_input"
    assert info.value.details == {"name": repr(value)}
