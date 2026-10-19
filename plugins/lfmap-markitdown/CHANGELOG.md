# Changelog

## [Unreleased]

### Added

- Plugin skeleton: manifest, formats and reason codes, input/output schemas for `classify`, `convert`, `export`, `info` (TC-M1).
- `quality.py`: text-layer quality checks ported from MarkitdownTool `document_core.py` @ 923ff35 (TC-M2).
- `backends`: `Backend` protocol and `MarkItDownBackend` (`convert_stream` only, plugins disabled) (TC-M3).
- `classify` and `convert` (no OCR yet): permission check first, one read per file, `max_file_bytes` setting (default 200 MB), MarkitdownTool's PDF classification, `max_chars` truncation, SHA-256 of the converted bytes (TC-M4).
