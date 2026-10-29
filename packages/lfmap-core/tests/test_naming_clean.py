import unicodedata

import pytest

from lfmap_core import ToolError
from lfmap_core.naming import clean_filename


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
        ("del\x7f.txt", "del\x7f.txt"),
        ("name. . .", "name"),
        ("name   ", "name"),
        ("   name.txt", "name.txt"),
        ("a :b", "a _b"),
        ("CON", "_CON"),
        ("con.txt", "_con.txt"),
        ("Lpt9.tar.gz", "_Lpt9.tar.gz"),
        ("NUL .txt", "_NUL .txt"),
        ("  aux", "_aux"),
        ("com1.", "_com1"),
        ("COM10.txt", "COM10.txt"),
        ("COM0.txt", "COM0.txt"),
        ("console.txt", "console.txt"),
        ("my con.txt", "my con.txt"),
        (".env", ".env"),
    ],
)
def test_clean_filename(name, expected):
    assert clean_filename(name) == expected


def test_clean_filename_normalises_to_nfc():
    decomposed = unicodedata.normalize("NFD", "Hồ sơ.pdf")
    assert clean_filename(decomposed) == unicodedata.normalize("NFC", "Hồ sơ.pdf")


def test_clean_filename_custom_replacement():
    assert clean_filename("a:b", replacement="-") == "a-b"
    assert clean_filename("a:b", replacement="") == "ab"
    assert clean_filename("a::b", replacement="~") == "a~~b"


@pytest.mark.parametrize("name", ["", "   ", "...", " . ", "\x00", "::"])
def test_clean_filename_rejects_empty_result(name):
    with pytest.raises(ToolError) as info:
        clean_filename(name, replacement="")
    assert info.value.code == "invalid_input"
    assert info.value.details == {"name": name}


@pytest.mark.parametrize("value", [None, 7, b"a.txt"])
def test_clean_filename_non_str(value):
    with pytest.raises(ToolError) as info:
        clean_filename(value)
    assert info.value.code == "invalid_input"
    assert info.value.details == {"name": repr(value)}


@pytest.mark.parametrize("replacement", ["/", "?", "ab", "\n", " ", "\x00"])
def test_clean_filename_rejects_bad_replacement(replacement):
    with pytest.raises(ToolError) as info:
        clean_filename("a:b", replacement=replacement)
    assert info.value.code == "invalid_input"
    assert info.value.details == {"replacement": replacement}


def test_clean_filename_rejects_non_str_replacement():
    with pytest.raises(ToolError) as info:
        clean_filename("a:b", replacement=None)
    assert info.value.details == {"replacement": "None"}
