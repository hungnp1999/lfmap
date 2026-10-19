import sys
from pathlib import Path

import pytest

from lfmap_markitdown.backends import MarkItDownBackend

sys.path.insert(0, str(Path(__file__).parent))
import builders  # noqa: E402


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("name", "build", "expected"),
    [
        ("a.docx", lambda p: builders.make_docx(p, "Calibration report ABC"), "Calibration report ABC"),
        ("a.html", lambda p: _write(p, "<html><body><h1>Hello ABC</h1></body></html>"), "# Hello ABC"),
        ("a.csv", lambda p: _write(p, "name,qty\nbolt,3\n"), "| bolt | 3 |"),
        ("a.pdf", lambda p: builders.make_text_pdf(p, "Inspection record ABC"), "Inspection record ABC"),
    ],
)
def test_converts_stream_to_markdown(tmp_path: Path, name: str, build, expected: str) -> None:
    path = build(tmp_path / name)
    with open(path, "rb") as stream:
        markdown = MarkItDownBackend().to_markdown(stream, path.suffix, path.name)
    assert expected in markdown


def test_version_is_reported() -> None:
    assert MarkItDownBackend().version() == "0.1.8"
