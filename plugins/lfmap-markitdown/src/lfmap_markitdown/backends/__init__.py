"""Conversion backends: MarkItDown, OCR (`ocr` extra) and Docling for PDFs (`docling` extra)."""

from lfmap_markitdown.backends.base import Backend
from lfmap_markitdown.backends.markitdown import MarkItDownBackend

__all__ = ["Backend", "MarkItDownBackend"]
