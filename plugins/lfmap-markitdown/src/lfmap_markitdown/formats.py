"""Supported formats and the reason codes shared with MarkitdownTool's integration service."""

from typing import Literal

DOCUMENT_EXTENSIONS = frozenset(
    {".pdf", ".docx", ".pptx", ".xlsx", ".xls", ".csv", ".html", ".htm", ".epub", ".txt", ".md", ".json", ".xml"}
)
# Images have no text layer, so they only convert through OCR.
IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"})
# Legacy Office formats need Office itself; only the MarkitdownTool app converts them (ADR-011).
OFFICE_GUI_ONLY = frozenset({".doc", ".rtf", ".odt", ".ppt", ".odp", ".ods"})

ReasonCode = Literal[
    "",
    "unsupported_format",
    "needs_ocr",
    "garbled_text",
    "office_gui_only",
    "ocr_unavailable",
    "docling_unavailable",
    "too_large",
    "exists",
]


def all_formats() -> list[str]:
    """Every extension the plugin can convert, with or without OCR."""
    return sorted(DOCUMENT_EXTENSIONS | IMAGE_EXTENSIONS)
