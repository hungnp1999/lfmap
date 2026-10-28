import unicodedata

import pytest

from lfmap_core import ToolError
from lfmap_core.naming import safe_filename, unique_name


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("report.pdf", "report.pdf"),
        ("Báo cáo tháng 10.docx", "Báo cáo tháng 10.docx"),
        ("a<b>c.txt", "a_b_c.txt"),
        ('x:y"z.txt', "x_y_z.txt"),
        ("a/b\\c|d?e*f.txt", "a_b_c_d_e_f.txt"),
        ("tab\there.txt", "tab_here.txt"),
        ("bell\x07.txt", "bell_.txt"),
        ("name. . .", "name"),
        ("name   ", "name"),
        ("   name.txt", "name.txt"),
        ("CON", "_CON"),
        ("con.txt", "_con.txt"),
        ("Lpt9.tar.gz", "_Lpt9.tar.gz"),
        ("NUL .txt", "_NUL .txt"),
        ("COM10.txt", "COM10.txt"),
        ("console.txt", "console.txt"),
        (".env", ".env"),
    ],
)
def test_safe_filename(name, expected):
    assert safe_filename(name) == expected


def test_safe_filename_normalises_to_nfc():
    decomposed = unicodedata.normalize("NFD", "Hồ sơ.pdf")
    assert safe_filename(decomposed) == unicodedata.normalize("NFC", "Hồ sơ.pdf")


def test_safe_filename_custom_replacement():
    assert safe_filename("a:b", replacement="-") == "a-b"
    assert safe_filename("a:b", replacement="") == "ab"


def test_safe_filename_truncates_and_keeps_extension():
    result = safe_filename("x" * 300 + ".pdf")
    assert len(result) == 255
    assert result == "x" * 251 + ".pdf"


def test_safe_filename_truncates_without_extension():
    assert safe_filename("y" * 300) == "y" * 255


def test_safe_filename_long_suffix_is_not_an_extension():
    name = "z" * 250 + "." + "e" * 20
    assert safe_filename(name) == name[:255]


def test_safe_filename_max_length():
    assert safe_filename("abcdef.txt", max_length=8) == "abcd.txt"


def test_safe_filename_strips_after_truncation():
    assert safe_filename("ab. .cdef", max_length=4) == "ab"


@pytest.mark.parametrize("name", ["", "   ", "...", " . ", "\x00"])
def test_safe_filename_rejects_empty_result(name):
    with pytest.raises(ToolError) as info:
        safe_filename(name, replacement="")
    assert info.value.code == "invalid_input"
    assert info.value.details == {"name": name}


@pytest.mark.parametrize("value", [None, 7, b"a.txt"])
def test_safe_filename_non_str(value):
    with pytest.raises(ToolError) as info:
        safe_filename(value)
    assert info.value.code == "invalid_input"
    assert info.value.details == {"name": repr(value)}


@pytest.mark.parametrize("replacement", ["/", "?", "ab", "\n", " "])
def test_safe_filename_rejects_bad_replacement(replacement):
    with pytest.raises(ToolError) as info:
        safe_filename("a:b", replacement=replacement)
    assert info.value.code == "invalid_input"
    assert info.value.details == {"replacement": replacement}


@pytest.mark.parametrize(
    ("name", "existing", "expected"),
    [
        ("a.txt", [], "a.txt"),
        ("a.txt", ["b.txt"], "a.txt"),
        ("a.txt", ["a.txt"], "a (2).txt"),
        ("a.txt", ["A.TXT"], "a (2).txt"),
        ("a.txt", ["a.txt", "a (2).txt"], "a (3).txt"),
        ("a.txt", ["a.txt", "a (3).txt"], "a (2).txt"),
        ("a.tar.gz", ["a.tar.gz"], "a.tar (2).gz"),
        ("README", ["readme"], "README (2)"),
        (".env", [".env"], ".env (2)"),
        ("Straße.txt", ["STRASSE.TXT"], "Straße (2).txt"),
    ],
)
def test_unique_name(name, existing, expected):
    assert unique_name(name, existing) == expected


def test_unique_name_accepts_any_iterable():
    taken = (n for n in ["x.md", "x (2).md"])
    assert unique_name("x.md", taken) == "x (3).md"


def test_unique_name_compares_nfc():
    existing = [unicodedata.normalize("NFD", "hồ sơ.pdf")]
    assert unique_name(unicodedata.normalize("NFC", "hồ sơ.pdf"), existing) == unicodedata.normalize(
        "NFC", "hồ sơ (2).pdf"
    )
