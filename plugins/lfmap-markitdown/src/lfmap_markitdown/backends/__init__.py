"""Conversion backends: MarkItDown now, Docling later (Roadmap 1.2)."""

from lfmap_markitdown.backends.base import Backend
from lfmap_markitdown.backends.markitdown import MarkItDownBackend

__all__ = ["Backend", "MarkItDownBackend"]
