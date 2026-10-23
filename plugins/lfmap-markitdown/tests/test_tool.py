import hashlib
import sys
from pathlib import Path

import pytest

from lfmap_core import ToolError
from lfmap_markitdown.backends import ocr
from lfmap_markitdown.schemas import ClassifyInput, ConvertInput, InfoInput
from lfmap_markitdown.tool import MarkitdownTool

sys.path.insert(0, str(Path(__file__).parent))
import builders  # noqa: E402


def _error(call) -> ToolError:
    with pytest.raises(ToolError) as caught:
        call()
    return caught.value


def _blank_pdf(path: Path) -> Path:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument.new()
    pdf.new_page(595, 842).close()
    pdf.save(path)
    pdf.close()
    return path


def test_path_outside_root_is_refused(tool: MarkitdownTool, tmp_path: Path) -> None:
    outside = tmp_path / "secret.txt"
    outside.write_text("x", encoding="utf-8")
    assert _error(lambda: tool.classify(ClassifyInput(path=str(outside)))).code == "permission_denied"
    assert _error(lambda: tool.convert(ConvertInput(path=str(outside)))).code == "permission_denied"


def test_missing_file(tool: MarkitdownTool, root: Path) -> None:
    assert _error(lambda: tool.classify(ClassifyInput(path=str(root / "none.pdf")))).code == "not_found"


@pytest.mark.parametrize(("name", "reason"), [("a.doc", "office_gui_only"), ("a.xyz", "unsupported_format")])
def test_unsupported_formats(tool: MarkitdownTool, root: Path, name: str, reason: str) -> None:
    (root / name).write_bytes(b"data")
    result = tool.classify(ClassifyInput(path=str(root / name)))
    assert (result.supported, result.markdown_eligible, result.reason_code) == (False, False, reason)
    error = _error(lambda: tool.convert(ConvertInput(path=str(root / name))))
    assert (error.code, error.details["reason_code"]) == ("invalid_input", reason)


@pytest.fixture
def no_ocr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ocr, "find_tesseract", lambda: None)


def test_scanned_pdf_needs_ocr(tool: MarkitdownTool, root: Path, no_ocr: None) -> None:
    path = _blank_pdf(root / "scan.pdf")
    result = tool.classify(ClassifyInput(path=str(path)))
    assert (result.needs_ocr, result.markdown_eligible, result.reason_code) == (True, False, "needs_ocr")
    error = _error(lambda: tool.convert(ConvertInput(path=str(path))))
    assert error.details["reason_code"] == "needs_ocr"
    error = _error(lambda: tool.convert(ConvertInput(path=str(path), ocr=True)))
    assert (error.code, error.details["reason_code"]) == ("backend_unavailable", "ocr_unavailable")


def test_image_needs_ocr(tool: MarkitdownTool, root: Path, no_ocr: None) -> None:
    (root / "a.png").write_bytes(b"png")
    result = tool.classify(ClassifyInput(path=str(root / "a.png")))
    assert (result.supported, result.needs_ocr, result.ocr_available) == (True, True, False)


def test_text_pdf_is_eligible(tool: MarkitdownTool, root: Path) -> None:
    path = builders.make_text_pdf(root / "a.pdf", "Inspection record for the pressure gauge")
    result = tool.classify(ClassifyInput(path=str(path)))
    assert (result.markdown_eligible, result.reason_code, result.text_quality) == (True, "", 1.0)


def test_convert_docx(tool: MarkitdownTool, root: Path) -> None:
    path = builders.make_docx(root / "report.docx", "Calibration report ABC")
    result = tool.convert(ConvertInput(path=str(path)))
    assert "Calibration report ABC" in result.markdown
    assert result.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert (result.stage, result.truncated, result.backend, result.chars) == (
        "markdown",
        False,
        "markitdown",
        len(result.markdown),
    )


def test_convert_truncates(tool: MarkitdownTool, root: Path) -> None:
    path = builders.make_docx(root / "report.docx", "Calibration report ABC")
    result = tool.convert(ConvertInput(path=str(path), max_chars=10))
    assert (result.truncated, result.chars, len(result.markdown)) == (True, 10, 10)


def test_too_large(tool: MarkitdownTool, root: Path) -> None:
    (root / "a.txt").write_text("x" * 20, encoding="utf-8")
    tool.ctx.settings["max_file_bytes"] = 10
    error = _error(lambda: tool.convert(ConvertInput(path=str(root / "a.txt"))))
    assert (error.code, error.details["reason_code"]) == ("invalid_input", "too_large")


def test_force_ocr_without_ocr_flag(tool: MarkitdownTool, root: Path) -> None:
    path = builders.make_text_pdf(root / "a.pdf", "Inspection record for the pressure gauge")
    error = _error(lambda: tool.convert(ConvertInput(path=str(path), force_ocr=True)))
    assert error.details["reason_code"] == "needs_ocr"


def test_force_ocr_is_ignored_for_docx(tool: MarkitdownTool, root: Path) -> None:
    path = builders.make_docx(root / "report.docx", "Calibration report ABC")
    assert tool.convert(ConvertInput(path=str(path), force_ocr=True)).stage == "markdown"


def test_ocr_languages_come_from_settings(tool: MarkitdownTool) -> None:
    assert tool._languages("") == ["eng"]
    tool.ctx.settings["ocr_languages"] = "vie+eng"
    assert tool._languages("") == ["vie", "eng"]
    assert tool._languages("deu") == ["deu"]


def test_info_and_health(tool: MarkitdownTool, no_ocr: None) -> None:
    info = tool.info(InfoInput())
    assert ".pdf" in info.formats and ".doc" not in info.formats
    assert (info.markitdown_version, info.plugin_version) == ("0.1.8", "0.1.0")
    assert (info.ocr_available, info.tesseract_path, info.ocr_languages) == (False, None, [])
    assert tool.health() == {"ok": True, "markitdown": "0.1.8", "ocr": False, "tesseract": None, "docling": False}


@pytest.mark.skipif(not ocr.ocr_available(), reason="needs the ocr extra and Tesseract")
def test_convert_scanned_image_with_ocr(tool: MarkitdownTool, root: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (1400, 300), "white")
    ImageDraw.Draw(image).text((60, 100), "INSPECTION PASSED", fill="black", font=ImageFont.load_default(size=96))
    image.save(root / "scan.png", dpi=(300, 300))
    result = tool.convert(ConvertInput(path=str(root / "scan.png"), ocr=True))
    assert result.stage == "ocr_markdown" and "INSPECTION" in result.markdown.upper()
    assert list((root / "tmp").iterdir()) == []
