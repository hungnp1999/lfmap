# lfmap-markitdown

LFMAP plugin that converts local documents (PDF, DOCX, PPTX, XLSX/XLS, CSV, HTML, EPUB, text) to Markdown, ported from MarkitdownTool. Work in progress (Roadmap Phase 1, item 1.1): the operations `classify`, `convert`, `export` and `info` are declared but not implemented yet.

- Legacy Office formats (`.doc`, `.rtf`, `.odt`, `.ppt`, `.odp`, `.ods`) are only converted by the MarkitdownTool app (ADR-011).
- OCR for scanned PDFs and images needs the `ocr` extra and Tesseract: `uv sync --extra ocr`.
