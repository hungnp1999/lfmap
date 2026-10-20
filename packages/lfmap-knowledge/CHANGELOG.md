# Changelog

All notable changes to lfmap-knowledge are documented here (Keep a Changelog).

## [Unreleased]

### Added
- Package skeleton, schemas and manifest (TC-K1).
- `store`: SQLite catalog schema v1, migrations and the single-writer `indexer.lock` (TC-K2).
- `scanner`: reconcile the catalog with a root folder, BLAKE2b-256 hashing only for new or changed files (TC-K3).
