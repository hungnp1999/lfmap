import ctypes
import importlib.util
import os
import socket
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from lfmap_core import ToolContext, ToolError
from lfmap_core.permissions import PermissionManager
from lfmap_markitdown.backends import docling as docling_backend
from lfmap_markitdown.backends import ocr
from lfmap_markitdown.schemas import ConvertInput, ExportInput, InfoInput
from lfmap_markitdown.tool import MarkitdownTool

sys.path.insert(0, str(Path(__file__).parent))
import builders  # noqa: E402

FAKE_MARKDOWN = "## 1. Scope\n\n### 1.1 Responsibilities\n"
ARTIFACTS = os.environ.get("LFMAP_DOCLING_ARTIFACTS", "")
real_docling = pytest.mark.skipif(
    not ARTIFACTS or importlib.util.find_spec("docling") is None,
    reason="needs the docling extra and LFMAP_DOCLING_ARTIFACTS pointing to downloaded models",
)


class FakeDocling:
    name = "docling"

    def __init__(self, options: docling_backend.DoclingOptions) -> None:
        self.options = options
        self.calls: list[tuple[bytes, str, str]] = []

    def version(self) -> str:
        return "2.142.0"

    def to_markdown(self, stream, extension: str, filename: str) -> str:
        self.calls.append((stream.read(), extension, filename))
        return FAKE_MARKDOWN


@pytest.fixture
def made(monkeypatch: pytest.MonkeyPatch) -> list[FakeDocling]:
    """Pretend the extra and the models are installed; record every backend the tool asks for."""
    created: list[FakeDocling] = []

    def fake_get_backend(options: docling_backend.DoclingOptions) -> FakeDocling:
        created.append(FakeDocling(options))
        return created[-1]

    monkeypatch.setattr(docling_backend, "docling_installed", lambda: True)
    monkeypatch.setattr(docling_backend, "missing_models", lambda path: [])
    monkeypatch.setattr(docling_backend, "get_backend", fake_get_backend)
    monkeypatch.setattr(ocr, "find_tesseract", lambda: "/opt/tesseract/tesseract")
    return created


def _tool(root: Path, **settings: object) -> MarkitdownTool:
    permissions = PermissionManager([str(root)], [str(root)])
    context = ToolContext(plugin_id="markitdown", permissions=permissions, temp_dir=root / "tmp", settings=settings)
    return MarkitdownTool(context)


@pytest.fixture
def models(tmp_path: Path) -> Path:
    folder = tmp_path / "models"
    folder.mkdir()
    return folder


@pytest.fixture
def tool(root: Path, models: Path) -> MarkitdownTool:
    return _tool(root, docling_artifacts_path=str(models), ocr_languages="vie+eng")


def _blank_pdf(path: Path) -> Path:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument.new()
    pdf.new_page(595, 842).close()
    pdf.save(path)
    pdf.close()
    return path


def _error(call) -> ToolError:
    with pytest.raises(ToolError) as caught:
        call()
    return caught.value


def test_backend_defaults_to_markitdown() -> None:
    assert ConvertInput(path="x.pdf").backend == "markitdown"
    assert ExportInput(path="x", output_dir="y").backend == "markitdown"
    with pytest.raises(ValidationError):
        ConvertInput(path="x.pdf", backend="pandoc")


def test_pdf_goes_through_docling(tool: MarkitdownTool, root: Path, made: list[FakeDocling]) -> None:
    path = builders.make_text_pdf(root / "manual.pdf", "Quality manual ABC")
    result = tool.convert(ConvertInput(path=str(path), backend="docling"))
    assert (result.markdown, result.backend, result.backend_version, result.stage) == (
        FAKE_MARKDOWN,
        "docling",
        "2.142.0",
        "markdown",
    )
    [backend] = made
    assert backend.calls == [(path.read_bytes(), ".pdf", "manual.pdf")]
    assert (backend.options.ocr, backend.options.full_page_ocr) == (False, False)
    assert backend.options.artifacts_path == tool.ctx.settings["docling_artifacts_path"]


def test_default_backend_never_touches_docling(tool: MarkitdownTool, root: Path, made: list[FakeDocling]) -> None:
    path = builders.make_text_pdf(root / "manual.pdf", "Quality manual ABC")
    result = tool.convert(ConvertInput(path=str(path)))
    assert result.backend == "markitdown" and "Quality manual ABC" in result.markdown
    assert made == []


def test_other_formats_stay_on_markitdown(tool: MarkitdownTool, root: Path, made: list[FakeDocling]) -> None:
    path = builders.make_docx(root / "report.docx", "Calibration report ABC")
    result = tool.convert(ConvertInput(path=str(path), backend="docling"))
    assert result.backend == "markitdown" and "Calibration report ABC" in result.markdown
    assert made == []


def test_scanned_pdf_still_needs_ocr_flag(tool: MarkitdownTool, root: Path, made: list[FakeDocling]) -> None:
    path = _blank_pdf(root / "scan.pdf")
    error = _error(lambda: tool.convert(ConvertInput(path=str(path), backend="docling")))
    assert (error.code, error.details["reason_code"]) == ("invalid_input", "needs_ocr")
    assert made == []


def test_scanned_pdf_uses_docling_tesseract_ocr(tool: MarkitdownTool, root: Path, made: list[FakeDocling]) -> None:
    path = _blank_pdf(root / "scan.pdf")
    result = tool.convert(ConvertInput(path=str(path), backend="docling", ocr=True))
    assert (result.backend, result.stage) == ("docling", "ocr_markdown")
    options = made[-1].options
    assert (options.ocr, options.full_page_ocr) == (True, True)
    assert options.languages == ("vie", "eng")
    assert options.tesseract_cmd == "/opt/tesseract/tesseract"


def test_ocr_languages_from_input_win(tool: MarkitdownTool, root: Path, made: list[FakeDocling]) -> None:
    path = _blank_pdf(root / "scan.pdf")
    tool.convert(ConvertInput(path=str(path), backend="docling", ocr=True, ocr_languages="eng"))
    assert made[-1].options.languages == ("eng",)


def test_ocr_on_readable_pdf_only_reads_bitmaps(tool: MarkitdownTool, root: Path, made: list[FakeDocling]) -> None:
    path = builders.make_text_pdf(root / "manual.pdf", "Quality manual ABC")
    result = tool.convert(ConvertInput(path=str(path), backend="docling", ocr=True))
    assert result.stage == "markdown"
    assert (made[-1].options.ocr, made[-1].options.full_page_ocr) == (True, False)


def test_force_ocr_reads_whole_pages(tool: MarkitdownTool, root: Path, made: list[FakeDocling]) -> None:
    path = builders.make_text_pdf(root / "manual.pdf", "Quality manual ABC")
    result = tool.convert(ConvertInput(path=str(path), backend="docling", ocr=True, force_ocr=True))
    assert result.stage == "ocr_markdown"
    assert (made[-1].options.ocr, made[-1].options.full_page_ocr) == (True, True)


def test_ocr_without_tesseract(
    tool: MarkitdownTool, root: Path, made: list[FakeDocling], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ocr, "find_tesseract", lambda: None)
    path = _blank_pdf(root / "scan.pdf")
    error = _error(lambda: tool.convert(ConvertInput(path=str(path), backend="docling", ocr=True)))
    assert (error.code, error.details["reason_code"]) == ("backend_unavailable", "ocr_unavailable")


def test_extra_not_installed(tool: MarkitdownTool, root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(docling_backend, "docling_installed", lambda: False)
    path = builders.make_text_pdf(root / "manual.pdf", "Quality manual ABC")
    error = _error(lambda: tool.convert(ConvertInput(path=str(path), backend="docling")))
    assert (error.code, error.details["reason_code"]) == ("backend_unavailable", "docling_unavailable")


def test_artifacts_path_is_required(root: Path, made: list[FakeDocling]) -> None:
    tool = _tool(root)
    path = builders.make_text_pdf(root / "manual.pdf", "Quality manual ABC")
    error = _error(lambda: tool.convert(ConvertInput(path=str(path), backend="docling")))
    assert (error.code, error.details["reason_code"]) == ("backend_unavailable", "docling_unavailable")
    assert "docling_artifacts_path" in error.message
    assert made == []


def test_missing_models_are_named(tool: MarkitdownTool, root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(docling_backend, "docling_installed", lambda: True)
    path = builders.make_text_pdf(root / "manual.pdf", "Quality manual ABC")
    error = _error(lambda: tool.convert(ConvertInput(path=str(path), backend="docling")))
    assert (error.code, error.details["reason_code"]) == ("backend_unavailable", "docling_unavailable")
    assert error.details["missing"] == [docling_backend.LAYOUT_MODEL, docling_backend.TABLE_MODEL]


def test_conversion_error_is_internal(tool: MarkitdownTool, root: Path, made: list[FakeDocling], monkeypatch) -> None:
    def broken(self, stream, extension, filename):
        raise RuntimeError("model crashed with a long message")

    monkeypatch.setattr(FakeDocling, "to_markdown", broken)
    path = builders.make_text_pdf(root / "manual.pdf", "Quality manual ABC")
    error = _error(lambda: tool.convert(ConvertInput(path=str(path), backend="docling")))
    assert error.code == "internal" and "RuntimeError" in error.message


def test_export_mixes_backends(tool: MarkitdownTool, root: Path, made: list[FakeDocling]) -> None:
    source = root / "in"
    source.mkdir()
    builders.make_text_pdf(source / "manual.pdf", "Quality manual ABC")
    builders.make_docx(source / "report.docx", "Calibration report ABC")
    result = tool.export(ExportInput(path=str(source), output_dir=str(root / "out"), backend="docling"))
    assert (result.succeeded, result.failed) == (2, 0)
    assert (root / "out" / "manual.pdf.md").read_text(encoding="utf-8") == FAKE_MARKDOWN
    assert "Calibration report ABC" in (root / "out" / "report.docx.md").read_text(encoding="utf-8")
    assert sum(len(backend.calls) for backend in made) == 1


def test_export_refuses_before_writing_when_unavailable(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(docling_backend, "docling_installed", lambda: False)
    tool = _tool(root, docling_artifacts_path=str(root))
    source = root / "in"
    source.mkdir()
    builders.make_docx(source / "report.docx", "Calibration report ABC")
    error = _error(lambda: tool.export(ExportInput(path=str(source), output_dir=str(root / "out"), backend="docling")))
    assert (error.code, error.details["reason_code"]) == ("backend_unavailable", "docling_unavailable")
    assert not (root / "out").exists() or list((root / "out").iterdir()) == []


def test_info_reports_docling(tool: MarkitdownTool, root: Path, made: list[FakeDocling], monkeypatch) -> None:
    monkeypatch.setattr(docling_backend, "docling_version", lambda: "2.142.0")
    info = tool.info(InfoInput())
    assert (info.docling_available, info.docling_version) == (True, "2.142.0")
    assert tool.health()["docling"] is True
    assert _tool(root).info(InfoInput()).docling_available is False


def test_info_without_extra(tool: MarkitdownTool, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(docling_backend, "docling_installed", lambda: False)
    monkeypatch.setattr(docling_backend, "docling_version", lambda: "")
    info = tool.info(InfoInput())
    assert (info.docling_available, info.docling_version) == (False, "")
    assert tool.health()["docling"] is False
    assert tool.health()["ok"] is True


def test_missing_models_checks_both_folders(models: Path) -> None:
    both = [docling_backend.LAYOUT_MODEL, docling_backend.TABLE_MODEL]
    assert docling_backend.missing_models(str(models / "absent")) == both
    assert docling_backend.missing_models(str(models)) == both
    (models / docling_backend.LAYOUT_MODEL).mkdir()
    assert docling_backend.missing_models(str(models)) == [docling_backend.TABLE_MODEL]
    (models / docling_backend.TABLE_MODEL).mkdir()
    assert docling_backend.missing_models(str(models)) == []


def test_force_offline_sets_hub_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"):
        monkeypatch.setenv(name, "0")
    docling_backend.force_offline()
    assert os.environ["HF_HUB_OFFLINE"] == "1"
    assert os.environ["TRANSFORMERS_OFFLINE"] == "1"


def test_backend_is_cached_per_options(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(docling_backend, "DoclingBackend", FakeDocling)
    docling_backend.get_backend.cache_clear()
    try:
        first = docling_backend.DoclingOptions(artifacts_path="m")
        again = docling_backend.get_backend(first)
        assert docling_backend.get_backend(docling_backend.DoclingOptions(artifacts_path="m")) is again
        assert docling_backend.get_backend(docling_backend.DoclingOptions(artifacts_path="m", ocr=True)) is not again
    finally:
        docling_backend.get_backend.cache_clear()


def test_importing_the_plugin_does_not_import_docling() -> None:
    import subprocess

    code = "import sys, lfmap_markitdown.tool; print('docling' in sys.modules, 'torch' in sys.modules)"
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "False False"


def _heading_pdf(path: Path) -> Path:
    """A4 page with a bold title, numbered bold headings in two sizes and body text in Helvetica."""
    import pypdfium2 as pdfium
    import pypdfium2.raw as raw

    lines = [
        ("Helvetica-Bold", 20, "Quality Manual"),
        ("Helvetica-Bold", 15, "1. Scope"),
        ("Helvetica", 10, "ABC Company keeps controlled documents in a local folder for every site."),
        ("Helvetica", 10, "Each document has an owner, a revision and a retention period."),
        ("Helvetica-Bold", 12, "1.1 Responsibilities"),
        ("Helvetica", 10, "The quality team reviews every document once a year and keeps the records."),
        ("Helvetica-Bold", 15, "2. Records"),
        ("Helvetica", 10, "Records are kept for five years unless a contract asks for longer."),
    ]
    pdf = pdfium.PdfDocument.new()
    page = pdf.new_page(595, 842)
    y = 780
    for font_name, size, text in lines:
        font = raw.FPDFText_LoadStandardFont(pdf.raw, font_name.encode())
        obj = raw.FPDFPageObj_CreateTextObj(pdf.raw, font, size)
        buffer = ctypes.create_string_buffer((text + "\0").encode("utf-16-le"))
        raw.FPDFText_SetText(obj, ctypes.cast(buffer, ctypes.POINTER(raw.FPDF_WCHAR)))
        raw.FPDFPageObj_Transform(obj, 1, 0, 0, 1, 60, y)
        raw.FPDFPage_InsertObject(page.raw, obj)
        y -= size * 2.2
    page.gen_content()
    page.close()
    pdf.save(path)
    pdf.close()
    return path


class _NoNetwork(socket.socket):
    def __init__(self, *args: object, **kwargs: object) -> None:
        raise AssertionError("network access attempted")


@real_docling
def test_real_models_give_nested_headings_offline(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "socket", _NoNetwork)
    monkeypatch.setattr(socket, "create_connection", _NoNetwork)
    tool = _tool(root, docling_artifacts_path=ARTIFACTS)
    path = _heading_pdf(root / "headings.pdf")
    result = tool.convert(ConvertInput(path=str(path), backend="docling"))
    lines = result.markdown.splitlines()
    assert result.backend == "docling"
    assert "## 1. Scope" in lines and "## 2. Records" in lines
    assert "### 1.1 Responsibilities" in lines
    assert "ABC Company keeps controlled documents" in result.markdown


@real_docling
def test_real_models_report_version_and_availability(root: Path) -> None:
    tool = _tool(root, docling_artifacts_path=ARTIFACTS)
    info = tool.info(InfoInput())
    assert info.docling_available and info.docling_version == "2.142.0"
