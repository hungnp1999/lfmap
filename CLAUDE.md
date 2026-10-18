# CLAUDE.md

Guidance for Claude Code sessions working on LFMAP. Design sources of truth live outside the repo (ADRs, Plugin Contract, Roadmap); follow them and flag conflicts instead of silently picking one side.

## Conventions

- Talk to the maintainer in **Vietnamese**. Code, comments, docstrings, commit messages, PR text, README and CHANGELOG in **English**.
- Standard library first, small functions, few comments, type hints everywhere.
- Business logic lives in a plugin's `Tool` class; adapters (CLI, MCP, later REST) stay generic and are generated in `lfmap-core`. Never write plugin-specific code in an adapter.
- New dependency: check its license first. Runtime licenses must be in a manifest's `allowed` list (`scripts/check_licenses.py` enforces it); reviewed exceptions go in `EXCEPTIONS` there and in the License Register.

## Security rules

- Every caller-supplied path goes through `PermissionManager.require_read` / `require_write` before any file-system call.
- Keep the final check as `realpath` followed by an inline `startswith` guard on the same variable (CodeQL `py/path-injection` does not recognise checks hidden in helpers).
- UNC, `\\?\`, `\\.\` and `//` paths are refused before any I/O.

## Commands (Windows, repo root)

```powershell
uv sync
uv run pytest
uv run ruff check . ; uv run ruff format --check .
uv sync --no-dev ; uv run --no-sync python scripts/check_licenses.py ; uv sync
```

## Workflow

1. Branch from up-to-date `main`; update `CHANGELOG.md` (`[Unreleased]`).
2. Open a PR. It may be merged without waiting for the maintainer only when every CodeQL check and the test suite pass and the PR is not a draft.
