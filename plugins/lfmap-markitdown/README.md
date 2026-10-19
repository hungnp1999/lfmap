# lfmap-markitdown

LFMAP plugin that converts local documents (PDF, DOCX, PPTX, XLSX/XLS, CSV, HTML, EPUB, text) to Markdown, ported from MarkitdownTool. Roadmap Phase 1, item 1.1.

| Operation | What it does | Side effects |
| --- | --- | --- |
| `classify` | Can the file be converted, does it need OCR, text-layer quality of a PDF | none |
| `convert` | Return the Markdown of one file | none |
| `export` | Write `<name.ext>.md` files for a file or folder into an export folder | local write; overwriting asks first |
| `info` | Versions, formats, OCR availability and Tesseract languages | none |

- Reads only inside `${documents}` and writes only inside `${exports}` from the user config (`lfmap config add-folder`).
- Legacy Office formats (`.doc`, `.rtf`, `.odt`, `.ppt`, `.odp`, `.ods`) are only converted by the MarkitdownTool app (ADR-011).
- OCR for scanned PDFs and images needs the `ocr` extra (`uv sync --all-packages --extra ocr`) and Tesseract. Tesseract from winget ships only `eng` and `osd`; copy `vie.traineddata` into a folder and point the `tessdata_dir` plugin setting at it. Nothing is downloaded.
- Settings (`[plugins.markitdown.settings]`): `ocr_languages` (default `eng`), `tessdata_dir`, `max_file_bytes` (200 MB), `max_files` (2000), `max_scan_depth` (16).
