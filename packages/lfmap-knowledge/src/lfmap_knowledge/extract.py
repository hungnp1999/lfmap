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
    markdown: str
    extractor_version: str
    text_quality: float | None
    from_cache: bool


@dataclass(frozen=True)
class SkipResult:
    reason_code: str


def extractor_version() -> str:
    """Return the version of the markitdown and lfmap-markitdown packages, or '0' if not found."""
    try:
        markitdown_version = importlib.metadata.version("markitdown")
    except importlib.metadata.PackageNotFoundError:
        markitdown_version = "0"
    try:
        lfmap_markitdown_version = importlib.metadata.version("lfmap-markitdown")
    except importlib.metadata.PackageNotFoundError:
        lfmap_markitdown_version = "0"
    return f"markitdown/{markitdown_version}/{lfmap_markitdown_version}"


def cache_path(cache_dir: Path, content_hash: str) -> Path:
    """Return the path to the cached Markdown file."""
    return cache_dir / content_hash[:2] / f"{content_hash}.md"


def extract(
    tool_ctx: ToolContext,
    path: Path,
    content_hash: str,
    cache_dir: Path,
    ocr: bool,
    config: dict | None = None,
) -> ExtractResult | SkipResult:
    """
    Extract Markdown from a file using the markitdown tool.

    :param tool_ctx: The tool context.
    :param path: The path to the file to extract.
    :param content_hash: The hash of the file content.
    :param cache_dir: The directory to use for caching.
    :param ocr: Whether to use OCR.
    :param config: Optional configuration for the markitdown tool.
    :return: An ExtractResult if extraction is successful, or a SkipResult if extraction should be skipped.
    """
    md_path = cache_path(cache_dir, content_hash)
    meta_path = md_path.with_suffix(".json")

    # Check if cache is valid
    if md_path.exists() and meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta["extractor_version"] == extractor_version():
            return ExtractResult(
                markdown=md_path.read_text(encoding="utf-8"),
                extractor_version=meta["extractor_version"],
                text_quality=meta.get("text_quality"),
                from_cache=True,
            )

    # Create cache directory if it doesn't exist
    md_path.parent.mkdir(parents=True, exist_ok=True)

    # Call markitdown tool
    try:
        tool = MarkitdownTool(context_for("markitdown", parent=tool_ctx, config=config))
        result = tool.convert(ConvertInput(path=str(path), ocr=ocr))
    except ToolError as e:
        if e.details and "reason_code" in e.details:
            return SkipResult(e.details["reason_code"])
        raise

    # Write to cache atomically
    fd, temp_md_path = tempfile.mkstemp(dir=md_path.parent, suffix=".md")
    with os.fdopen(fd, "w", encoding="utf-8") as temp_md_file:
        temp_md_file.write(result.markdown)
    os.replace(temp_md_path, str(md_path))

    temp_meta_path = md_path.with_suffix(".tmp.json")
    with open(temp_meta_path, "w", encoding="utf-8") as temp_meta_file:
        json.dump(
            {
                "extractor_version": extractor_version(),
                "text_quality": result.text_quality,
            },
            temp_meta_file,
        )
    os.replace(temp_meta_path, str(meta_path))

    return ExtractResult(
        markdown=result.markdown,
        extractor_version=extractor_version(),
        text_quality=result.text_quality,
        from_cache=False,
    )
