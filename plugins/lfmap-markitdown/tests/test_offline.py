import shutil
import socket
from pathlib import Path

import pytest

from lfmap_markitdown.backends import ocr
from lfmap_markitdown.schemas import ClassifyInput, ConvertInput, ExportInput, InfoInput
from lfmap_markitdown.tool import MarkitdownTool

PARITY = Path(__file__).parent / "fixtures" / "parity"


class _NoNetwork(socket.socket):
    def __init__(self, *args: object, **kwargs: object) -> None:
        raise AssertionError("network access attempted")


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "socket", _NoNetwork)
    monkeypatch.setattr(socket, "create_connection", _NoNetwork)
    monkeypatch.setattr(ocr, "find_tesseract", lambda: None)


def test_all_operations_run_offline(tool: MarkitdownTool, root: Path) -> None:
    source = root / "in"
    shutil.copytree(PARITY, source, ignore=shutil.ignore_patterns("*.py", "*.ps1", "*.json"))
    assert tool.info(InfoInput()).markitdown_version
    for path in sorted(source.iterdir()):
        tool.classify(ClassifyInput(path=str(path)))
    for name in ("good.pdf", "report.docx", "list.xlsx", "page.html"):
        assert tool.convert(ConvertInput(path=str(source / name))).markdown
    result = tool.export(ExportInput(path=str(source), output_dir=str(root / "out")))
    assert result.succeeded == 4 and result.failed == 0
