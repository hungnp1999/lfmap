# Changelog

## [Unreleased]

### Added

- Plugin skeleton: manifest, formats and reason codes, input/output schemas for `classify`, `convert`, `export`, `info` (TC-M1).
- `quality.py`: text-layer quality checks ported from MarkitdownTool `document_core.py` @ 923ff35 (TC-M2).
- `backends`: `Backend` protocol and `MarkItDownBackend` (`convert_stream` only, plugins disabled) (TC-M3).
- `classify` and `convert` (no OCR yet): permission check first, one read per file, `max_file_bytes` setting (default 200 MB), MarkitdownTool's PDF classification, `max_chars` truncation, SHA-256 of the converted bytes (TC-M4).
- OCR backend in the `ocr` extra: OCRmyPDF with the pypdfium rasterizer and plain PDF output, so Ghostscript is never used; Tesseract found on `PATH` or in `C:\Program Files\Tesseract-OCR`; optional `tessdata_dir` setting; one OCR run at a time (TC-M5).
- `convert` runs OCR for scans, images and garbled PDF text layers when `ocr=true`; `ocr_languages` falls back to the `ocr_languages` setting (default `eng`); `info` and `health` report versions, formats and OCR availability (TC-M6).
- `export`: file or folder to `<name.ext>.md` in an export folder, subfolders kept with `recursive`, atomic writes, existing files skipped unless `overwrite`, which asks for approval (T2) once before writing; linked folders are never entered; `max_files` (2000) and `max_scan_depth` (16) settings (TC-M7).
- Parity fixtures (synthetic, < 2 MB), `Get-Expected.ps1` to record MarkitdownTool's classification on Windows, and `test_parity.py`, skipped until `expected.json` is recorded (TC-M8, part 1).
- `expected.json` recorded from MarkitdownTool 2.4.0 (`integration_service.classify` at tag v2.4.0); the parity test now runs and matches on all fixtures. `Get-Expected.ps1` refuses MarkitdownTool older than 2.4.0 (no text-layer checks) and no longer turns a missing `low_quality_pages` into `[null]` (TC-M8).
- Verified on Windows over a real MCP stdio round trip: info, classify, convert, a read outside the roots refused, export creating files (T1, audited), and overwrite refused without approval (T2, audited) (TC-M9).
