import hashlib
import io
from dataclasses import dataclass
from pathlib import Path

from lfmap_core import Tool, ToolError, operation
from lfmap_markitdown import formats
from lfmap_markitdown.backends import Backend, MarkItDownBackend
from lfmap_markitdown.formats import ReasonCode
from lfmap_markitdown.quality import analyze_pdf_text
from lfmap_markitdown.schemas import (
    ClassifyInput,
    ClassifyOutput,
    ConvertInput,
    ConvertOutput,
    ExportInput,
    ExportOutput,
    InfoInput,
    InfoOutput,
)

DEFAULT_MAX_FILE_BYTES = 200 * 1024 * 1024


@dataclass(frozen=True)
class _Classification:
    supported: bool
    needs_ocr: bool
    reason_code: ReasonCode
    text_quality: float | None = None
    low_quality_pages: tuple[int, ...] = ()


def _classify(extension: str, data: bytes | None) -> _Classification:
    """Same decision as MarkitdownTool's classify_file; a PDF's text layer is read from `data`."""
    if extension in formats.OFFICE_GUI_ONLY:
        return _Classification(False, False, "office_gui_only")
    if extension in formats.IMAGE_EXTENSIONS:
        return _Classification(True, True, "needs_ocr")
    if extension not in formats.DOCUMENT_EXTENSIONS:
        return _Classification(False, False, "unsupported_format")
    if extension != ".pdf" or data is None:
        return _Classification(True, False, "")
    report = analyze_pdf_text(data)
    if report.low_quality_pages:
        return _Classification(True, True, "garbled_text", report.text_quality, report.low_quality_pages)
    if not report.readable or report.empty_pages:
        return _Classification(True, True, "needs_ocr", report.text_quality)
    return _Classification(True, False, "", report.text_quality)


def ocr_available() -> bool:
    """The OCR backend arrives with TC-M5; until then OCR is never available."""
    return False


class MarkitdownTool(Tool):
    backend: Backend | None = None

    def _backend(self) -> Backend:
        if self.backend is None:
            self.backend = MarkItDownBackend()
        return self.backend

    def _require_file(self, value: str) -> Path:
        path = self.ctx.permissions.require_read(value)
        if not path.is_file():
            raise ToolError("not_found", "File not found", {"path": value})
        return path

    def _read(self, path: Path) -> bytes:
        """Read through one handle, so hashing, checks and conversion all see the same bytes."""
        limit = int(self.ctx.settings.get("max_file_bytes", DEFAULT_MAX_FILE_BYTES))
        with open(path, "rb") as stream:
            data = stream.read(limit + 1)
        if len(data) > limit:
            raise ToolError("invalid_input", "File is too large", {"reason_code": "too_large", "limit": limit})
        return data

    @operation("classify")
    def classify(self, inp: ClassifyInput) -> ClassifyOutput:
        """Check whether a local file can be converted to Markdown, and whether it needs OCR."""
        path = self._require_file(inp.path)
        extension = path.suffix.lower()
        found = _classify(extension, self._read(path) if extension == ".pdf" else None)
        return ClassifyOutput(
            path=str(path),
            extension=extension,
            supported=found.supported,
            needs_ocr=found.needs_ocr,
            markdown_eligible=found.supported and not found.needs_ocr,
            reason_code=found.reason_code,
            text_quality=found.text_quality,
            low_quality_pages=list(found.low_quality_pages),
            ocr_available=ocr_available(),
        )

    @operation("convert")
    def convert(self, inp: ConvertInput) -> ConvertOutput:
        """Convert one local file to Markdown and return the text; nothing is written to disk."""
        path = self._require_file(inp.path)
        data = self._read(path)
        extension = path.suffix.lower()
        found = _classify(extension, data)
        if not found.supported:
            raise ToolError("invalid_input", "Format cannot be converted", {"reason_code": found.reason_code})
        if found.needs_ocr or inp.force_ocr:
            if not inp.ocr:
                code = found.reason_code or "needs_ocr"
                raise ToolError("invalid_input", "File needs OCR; retry with ocr=true", {"reason_code": code})
            raise ToolError("backend_unavailable", "OCR is not installed", {"reason_code": "ocr_unavailable"})
        backend = self._backend()
        try:
            markdown = backend.to_markdown(io.BytesIO(data), extension, path.name)
        except Exception as error:
            raise ToolError("internal", f"Conversion failed: {type(error).__name__}", {"path": str(path)}) from error
        truncated = len(markdown) > inp.max_chars
        if truncated:
            markdown = markdown[: inp.max_chars]
        return ConvertOutput(
            path=str(path),
            markdown=markdown,
            chars=len(markdown),
            truncated=truncated,
            stage="markdown",
            text_quality=found.text_quality,
            sha256=hashlib.sha256(data).hexdigest(),
            backend=backend.name,
            backend_version=backend.version(),
        )

    @operation("export")
    def export(self, inp: ExportInput) -> ExportOutput:
        """Convert a file or folder and write <name>.md files into an export folder."""
        raise ToolError("internal", "not implemented")

    @operation("info")
    def info(self, inp: InfoInput) -> InfoOutput:
        """Report the plugin and MarkItDown versions, supported formats and OCR availability."""
        raise ToolError("internal", "not implemented")
