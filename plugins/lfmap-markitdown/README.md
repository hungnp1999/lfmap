# lfmap-markitdown

LFMAP plugin that converts local documents (PDF, DOCX, PPTX, XLSX/XLS, CSV, HTML, EPUB, text) to Markdown, ported from MarkitdownTool. Roadmap Phase 1, item 1.1.

| Operation | What it does | Side effects |
| --- | --- | --- |
| `classify` | Can the file be converted, does it need OCR, text-layer quality of a PDF | none |
| `convert` | Return the Markdown of one file | none |
| `export` | Write `<name.ext>.md` files for a file or folder into an export folder | local write; overwriting asks first |
| `info` | Versions, formats, OCR and Docling availability, Tesseract languages | none |

- Reads only inside `${documents}` and writes only inside `${exports}` from the user config (`lfmap config add-folder`).
- Legacy Office formats (`.doc`, `.rtf`, `.odt`, `.ppt`, `.odp`, `.ods`) are only converted by the MarkitdownTool app (ADR-011).
- OCR for scanned PDFs and images needs the `ocr` extra (`uv sync --all-packages --extra ocr`) and Tesseract. Tesseract from winget ships only `eng` and `osd`; copy `vie.traineddata` into a folder and point the `tessdata_dir` plugin setting at it. Nothing is downloaded.
- Settings (`[plugins.markitdown.settings]`): `ocr_languages` (default `eng`), `tessdata_dir`, `max_file_bytes` (200 MB), `max_files` (2000), `max_scan_depth` (16), and for Docling `docling_artifacts_path`, `docling_device` (`auto`, `cpu` or `cuda`), `docling_threads` (4).

## Docling backend for PDFs

MarkItDown turns no PDF heading into a Markdown heading and can merge table columns. `convert` and `export` take `backend = "docling"` (`--backend docling` on the CLI) to read PDFs with [Docling](https://github.com/docling-project/docling) instead: nested headings and table columns, at about 3 s per page on CPU against 0.02 s for MarkItDown, plus about 5 s once per process to load the models. MarkItDown stays the default.

- PDF only. Other files in the same call or export folder still go through MarkItDown and report `backend = "markitdown"`.
- Install the extra: `uv sync --all-packages --extra docling` (add `--extra ocr` to keep OCRmyPDF for the MarkItDown backend). It pins `docling-slim` 2.142.0 and brings PyTorch on CPU.
- Download the models once into a folder of your choice. The extra does not include the `docling-tools` command, so run it from a separate tool environment, for example `uvx --from "docling-slim[cli,models-local]==2.142.0" docling-tools models download layout tableformer -o D:\Models\docling`. The folder must contain `docling-project--docling-layout-heron` and `docling-project--docling-models`; keep the license files that come with them.
- Point the `docling_artifacts_path` setting at that folder. Without the setting, the extra or either model folder, the call fails with `backend_unavailable` and `reason_code = "docling_unavailable"` (the missing folders are listed); `export` checks this once before writing anything.
- Fully offline: the plugin sets `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` before loading Docling, never downloads a model and passes Docling the bytes it already read, never a path.
- OCR: with `ocr=true` Docling runs Tesseract itself (same `ocr_languages` and `tessdata_dir`; OCRmyPDF is not used). Scanned, garbled or `force_ocr` PDFs are read with full-page OCR (`stage = "ocr_markdown"`); readable PDFs only OCR their bitmaps. Without `ocr=true` such files are refused with `needs_ocr`, as with MarkItDown.
- Heading levels come from section numbers: Docling writes every heading as `##`, so `## 1.1 X` becomes `### 1.1 X` and `## 2.3.4 X` becomes `####` (at most `######`). Unnumbered headings and other numbering styles (`II.`, `Article 3.`) stay `##`.

```powershell
uv run lfmap markitdown convert D:\Docs\manual.pdf --backend docling --json
uv run lfmap markitdown convert D:\Docs\scan.pdf --backend docling --ocr --json
```

`info` reports `docling_available` (extra, setting and models) and `docling_version`; `health` gains `docling`.
