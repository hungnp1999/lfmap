import hashlib
import io
import os
import tempfile
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from lfmap_core import Tool, ToolError, operation
from lfmap_markitdown import formats
from lfmap_markitdown.backends import Backend, MarkItDownBackend, ocr
from lfmap_markitdown.formats import ReasonCode
from lfmap_markitdown.quality import analyze_pdf_text
from lfmap_markitdown.scan import ScanLimitExceeded, scan_folder
from lfmap_markitdown.schemas import (
    ClassifyInput,
    ClassifyOutput,
    ConvertInput,
    ConvertOutput,
    ExportedFile,
    ExportInput,
    ExportOutput,
    InfoInput,
    InfoOutput,
)

DEFAULT_MAX_FILE_BYTES = 200 * 1024 * 1024
DEFAULT_MAX_FILES = 2000
DEFAULT_MAX_SCAN_DEPTH = 16
# Reason codes that mean "this file is not for this run", not "something broke".
_SKIP_REASONS = {"unsupported_format", "needs_ocr", "garbled_text", "office_gui_only", "ocr_unavailable", "too_large"}


@dataclass(frozen=True)
class _Classification:
    supported: bool
    needs_ocr: bool
    reason_code: ReasonCode
    text_quality: float | None = None
    low_quality_pages: tuple[int, ...] = ()
    ocr_pages: tuple[int, ...] = ()


@dataclass(frozen=True)
class _Converted:
    markdown: str
    stage: str
    text_quality: float | None
    backend: Backend


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
        pages = tuple(sorted(report.empty_pages + report.low_quality_pages))
        return _Classification(True, True, "garbled_text", report.text_quality, report.low_quality_pages, pages)
    if not report.readable or report.empty_pages:
        return _Classification(True, True, "needs_ocr", report.text_quality)
    return _Classification(True, False, "", report.text_quality)


def _version(package: str) -> str:
    try:
        return version(package)
    except PackageNotFoundError:
        return ""


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

    def _languages(self, requested: str) -> list[str]:
        text = requested or str(self.ctx.settings.get("ocr_languages", "eng"))
        return [code for code in text.split("+") if code]

    def _ocr_markdown(self, data: bytes, extension: str, languages: str, force_pages: tuple[int, ...] | None) -> str:
        if not ocr.ocr_available():
            raise ToolError("backend_unavailable", "OCR is not installed", {"reason_code": "ocr_unavailable"})
        base = self.ctx.temp_dir
        if base is not None:
            base.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base, prefix="ocr-", ignore_cleanup_errors=True) as work:
            pdf = ocr.ocr_to_pdf(
                io.BytesIO(data),
                extension,
                Path(work),
                self._languages(languages),
                force_pages,
                self.ctx.settings.get("tessdata_dir"),
            )
            with open(pdf, "rb") as stream:
                return self._backend().to_markdown(stream, ".pdf", "ocr.pdf")

    def _convert(self, path: Path, data: bytes, use_ocr: bool, languages: str, force_ocr: bool) -> _Converted:
        extension = path.suffix.lower()
        found = _classify(extension, data)
        if not found.supported:
            raise ToolError("invalid_input", "Format cannot be converted", {"reason_code": found.reason_code})
        forced = force_ocr and extension == ".pdf"
        backend = self._backend()
        try:
            if found.needs_ocr or forced:
                if not use_ocr:
                    code = found.reason_code or "needs_ocr"
                    raise ToolError("invalid_input", "File needs OCR; retry with ocr=true", {"reason_code": code})
                force_pages = () if forced else found.ocr_pages if found.reason_code == "garbled_text" else None
                markdown = self._ocr_markdown(data, extension, languages, force_pages)
                return _Converted(markdown, "ocr_markdown", found.text_quality, backend)
            markdown = backend.to_markdown(io.BytesIO(data), extension, path.name)
        except ToolError:
            raise
        except Exception as error:
            raise ToolError("internal", f"Conversion failed: {type(error).__name__}", {"path": str(path)}) from error
        return _Converted(markdown, "markdown", found.text_quality, backend)

    def health(self) -> dict:
        markitdown_version = _version("markitdown")
        return {
            "ok": bool(markitdown_version),
            "markitdown": markitdown_version,
            "ocr": ocr.ocr_available(),
            "tesseract": ocr.find_tesseract(),
        }

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
            ocr_available=ocr.ocr_available(),
        )

    @operation("convert")
    def convert(self, inp: ConvertInput) -> ConvertOutput:
        """Convert one local file to Markdown and return the text; nothing is written to disk."""
        path = self._require_file(inp.path)
        data = self._read(path)
        result = self._convert(path, data, inp.ocr, inp.ocr_languages, inp.force_ocr)
        markdown = result.markdown
        truncated = len(markdown) > inp.max_chars
        if truncated:
            markdown = markdown[: inp.max_chars]
        return ConvertOutput(
            path=str(path),
            markdown=markdown,
            chars=len(markdown),
            truncated=truncated,
            stage=result.stage,
            text_quality=result.text_quality,
            sha256=hashlib.sha256(data).hexdigest(),
            backend=result.backend.name,
            backend_version=result.backend.version(),
        )

    def _sources(self, source: Path, recursive: bool) -> tuple[Path, list[Path]]:
        """The folder relative names are taken from, and the files to export."""
        if source.is_file():
            return source.parent, [source]
        if not source.is_dir():
            raise ToolError("not_found", "File or folder not found", {"path": str(source)})
        settings = self.ctx.settings
        try:
            files = scan_folder(
                source,
                recursive,
                int(settings.get("max_scan_depth", DEFAULT_MAX_SCAN_DEPTH)),
                int(settings.get("max_files", DEFAULT_MAX_FILES)),
            )
        except ScanLimitExceeded as error:
            raise ToolError("invalid_input", str(error), {"limit": error.limit, "value": error.value}) from error
        return source, files

    def _export_one(self, inp: ExportInput, path: Path, target: Path) -> ExportedFile:
        try:
            real = self._require_file(str(path))
            converted = self._convert(real, self._read(real), inp.ocr, inp.ocr_languages, inp.force_ocr)
        except ToolError as error:
            reason = error.details.get("reason_code", "")
            status = "skipped" if reason in _SKIP_REASONS else "failed"
            return ExportedFile(source=str(path), status=status, reason_code=reason, message=error.message)
        try:
            target = self.ctx.permissions.require_write(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            handle, temporary = tempfile.mkstemp(dir=target.parent, prefix=".tmp-", suffix=".md")
        except (ToolError, OSError) as error:
            return ExportedFile(source=str(path), status="failed", reason_code="", message=str(error))
        try:
            with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(converted.markdown)
            os.replace(temporary, target)
        except OSError as error:
            Path(temporary).unlink(missing_ok=True)
            return ExportedFile(source=str(path), status="failed", reason_code="", message=str(error))
        return ExportedFile(source=str(path), status="success", reason_code="", outputs=[str(target)])

    @operation("export")
    def export(self, inp: ExportInput) -> ExportOutput:
        """Convert a file or folder and write <name>.md files into an export folder."""
        if not os.path.isabs(inp.output_dir):
            raise ToolError("invalid_input", "output_dir must be an absolute path", {"output_dir": inp.output_dir})
        source = self.ctx.permissions.require_read(inp.path)
        output_dir = self.ctx.permissions.require_write(inp.output_dir)
        base, files = self._sources(source, inp.recursive)
        known = set(formats.all_formats())
        plan = [(path, output_dir / (str(path.relative_to(base)) + ".md")) for path in files]
        existing = {target for path, target in plan if path.suffix.lower() in known and target.exists()}
        if inp.overwrite and existing:
            self.ctx.require_approval("overwrite", detail=str(output_dir))
        results = []
        for path, target in plan:
            if target in existing and not inp.overwrite:
                results.append(
                    ExportedFile(source=str(path), status="skipped", reason_code="exists", outputs=[str(target)])
                )
            else:
                results.append(self._export_one(inp, path, target))
        return ExportOutput(
            output_dir=str(output_dir),
            total=len(results),
            succeeded=sum(r.status == "success" for r in results),
            skipped=sum(r.status == "skipped" for r in results),
            failed=sum(r.status == "failed" for r in results),
            files=results,
        )

    @operation("info")
    def info(self, inp: InfoInput) -> InfoOutput:
        """Report the plugin and MarkItDown versions, supported formats and OCR availability."""
        return InfoOutput(
            plugin_version=_version("lfmap-markitdown"),
            markitdown_version=_version("markitdown"),
            formats=formats.all_formats(),
            ocr_available=ocr.ocr_available(),
            tesseract_path=ocr.find_tesseract(),
            ocr_languages=ocr.available_languages(self.ctx.settings.get("tessdata_dir")),
        )
