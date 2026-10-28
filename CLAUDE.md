# CLAUDE.md

Guidance for Claude Code sessions working on LFMAP. Module map, main flows and invariants: `ARCHITECTURE.md`.

## Working from handoffs

- Work starts from a handoff file `docs/handoff/YYYY-MM-DD-*.md` and the spec it links (`docs/specs/`). Together they carry the decisions already made (ADRs, Plugin Contract, Roadmap live outside the repo).
- Do one task at a time and meet its completion criteria. If the handoff conflicts with the code, an ADR or this file, stop and ask; do not pick a side silently.
- "Cập nhật tài liệu dự án" items: list them in the PR body; do not create ROADMAP/DECISIONS files here.
- Handoff files are in Vietnamese; keep them so.

## Conventions

- Talk to the maintainer in **Vietnamese**. Code, comments, docstrings, commit messages, PR text, README, CHANGELOG and specs in **English**.
- Standard library first, small functions, few comments, type hints everywhere.
- Business logic lives in a plugin's `Tool` class; adapters (CLI, MCP, later REST) stay generic and are generated in `lfmap-core`. Never write plugin-specific code in an adapter.
- New dependency: check its license first. Runtime licenses must be in a manifest's `allowed` list (`scripts/check_licenses.py` enforces it); reviewed exceptions go in `EXCEPTIONS` there and in the License Register.

## Security rules

- Every caller-supplied path goes through `PermissionManager.require_read` / `require_write` before any file-system call.
- Keep the final check as `realpath` followed by an inline `startswith` guard on the same variable (CodeQL `py/path-injection` does not recognise checks hidden in helpers).
- UNC, `\\?\`, `\\.\` and `//` paths are refused before any I/O.

## Provenance

- Git and PR operations only in an environment listed in `docs/DEVELOPMENT_PROVENANCE.md` (`cloud`, `pc-01`); never on an employer-owned device.
- Every commit ends with `Dev-Environment: <label>`; `.githooks/prepare-commit-msg` adds it once the SessionStart hook has run. Cloud commits also keep `Claude-Session:`. The `Provenance` workflow fails a PR otherwise.
- Merging through the API: put `Dev-Environment:` and `Claude-Session:` in the merge or squash commit message.

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
3. A PR that changes the module map, a main flow or an invariant updates `ARCHITECTURE.md` in the same PR.
4. Before merging a code PR that touches caller-supplied paths, adapters, network calls, subprocesses or `.claude/`, run `/security-review` and fix or answer its findings. Docs-only PRs skip it.
5. At the end of each Roadmap phase and after a large refactor, redraw the architecture diagram (Artifact page) and note any drift from `ARCHITECTURE.md`.
