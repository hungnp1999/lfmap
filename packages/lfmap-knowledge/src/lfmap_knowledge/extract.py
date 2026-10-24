"""Extract Markdown through the markitdown plugin and cache it by content hash."""

import importlib.metadata
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from lfmap_core import ToolContext, ToolError
from lfmap_core.runtime import context_for
from lfmap_markitdown.schemas import ConvertInput
from lfmap_markitdown.tool import MarkitdownTool


@dataclass(frozen=True)
class ExtractResult:
    """Markdown of one content hash; from_cache tells whether markitdown was skipped."""

    markdown: str
    extractor_version: str
    text_quality: float | None
    from_cache: bool


@dataclass(frozen=True)
class SkipResult:
    """markitdown refused the file for a known reason (e.g. office_gui_only); nothing was cached."""

    reason_code: str


def _version(package: str) -> str:
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return "0"


PDF_BACKENDS = ("markitdown", "docling")


def pdf_backend(settings: dict) -> str:
    """The pdf_backend setting: markitdown (default) or docling."""
    backend = settings.get("pdf_backend", "markitdown")
    if backend not in PDF_BACKENDS:
        raise ToolError("invalid_input", "pdf_backend must be 'markitdown' or 'docling'", {"pdf_backend": backend})
    return backend


def backend_for(ext: str, pdf: str) -> str:
    """Docling only converts PDFs; every other format stays on markitdown."""
    return pdf if ext.lower() == ".pdf" else "markitdown"


def extractor_version(backend: str = "markitdown") -> str:
    """Version tag stored with each cache entry; a markitdown or docling upgrade invalidates the cache."""
    if backend == "docling":
        return f"docling/{_version('docling-slim')}/{_version('lfmap-markitdown')}"
    return f"markitdown/{_version('markitdown')}/{_version('lfmap-markitdown')}"


def cache_path(cache_dir: Path, content_hash: str, backend: str = "markitdown") -> Path:
    """Markdown cache file of one content hash: cache_dir/ab/<hash>.md, or <hash>.docling.md for docling."""
    suffix = ".md" if backend == "markitdown" else f".{backend}.md"
    return cache_dir / content_hash[:2] / f"{content_hash}{suffix}"


def require_backend(tool_ctx: ToolContext, backend: str, config: dict | None = None) -> None:
    """Raise backend_unavailable when the docling backend of markitdown cannot run."""
    if backend != "docling":
        return
    tool = MarkitdownTool(context_for("markitdown", parent=tool_ctx, config=config))
    if not tool.health()["docling"]:
        raise ToolError(
            "backend_unavailable",
            "pdf_backend is 'docling' but the markitdown Docling backend is unavailable; see `lfmap markitdown info`",
            {"reason_code": "docling_unavailable"},
        )


def _read_cache(md_path: Path, version: str) -> ExtractResult | None:
    try:
        meta = json.loads(md_path.with_suffix(".json").read_text(encoding="utf-8"))
        if meta["extractor_version"] != version:
            return None
        with open(md_path, encoding="utf-8", newline="") as f:
            markdown = f.read()
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return ExtractResult(markdown, version, meta.get("text_quality"), from_cache=True)


def _write_atomic(path: Path, text: str) -> None:
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        os.replace(temp, path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise


def extract(
    tool_ctx: ToolContext,
    path: Path,
    content_hash: str,
    cache_dir: Path,
    ocr: bool,
    config: dict | None = None,
    backend: str = "markitdown",
) -> ExtractResult | SkipResult:
    """Return the cached Markdown of content_hash, or convert path with markitdown and cache it.

    The .json sidecar is written last, so it only exists for a complete extraction.
    A ToolError with a reason_code becomes a SkipResult, except docling_unavailable (a configuration
    problem, not a property of the file); any other error is raised.
    """
    version = extractor_version(backend)
    md_path = cache_path(cache_dir, content_hash, backend)
    cached = _read_cache(md_path, version)
    if cached is not None:
        return cached

    try:
        tool = MarkitdownTool(context_for("markitdown", parent=tool_ctx, config=config))
        out = tool.convert(ConvertInput(path=str(path), ocr=ocr, backend=backend))
    except ToolError as e:
        if "reason_code" in e.details and e.details["reason_code"] != "docling_unavailable":
            return SkipResult(e.details["reason_code"])
        raise

    md_path.parent.mkdir(parents=True, exist_ok=True)
    _write_atomic(md_path, out.markdown)
    meta = {"extractor_version": version, "text_quality": out.text_quality}
    _write_atomic(md_path.with_suffix(".json"), json.dumps(meta))
    return ExtractResult(out.markdown, version, out.text_quality, from_cache=False)
