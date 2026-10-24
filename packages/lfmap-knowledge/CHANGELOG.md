# Changelog

All notable changes to lfmap-knowledge are documented here (Keep a Changelog).

## [Unreleased]

### Added
- Setting `pdf_backend = "docling"`: PDFs are extracted by the markitdown Docling backend and get a `heading_path` (L21); see the root CHANGELOG.
- Package skeleton, schemas and manifest (TC-K1).
- `store`: SQLite catalog schema v1, migrations and the single-writer `indexer.lock` (TC-K2).
- `scanner`: reconcile the catalog with a root folder, BLAKE2b-256 hashing only for new or changed files (TC-K3).
- `search`: hybrid chunk search and `get_context`; all seven operations wired into `tool.py` (TC-K10, TC-K11). See the root CHANGELOG.
