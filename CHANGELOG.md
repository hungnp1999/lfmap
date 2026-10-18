# Changelog

## [Unreleased]

### Added

- uv workspace (Python 3.12), ruff, pytest, pre-commit.
- `lfmap-core` 0.1.0: `Tool`, `@operation`, `invoke`, `ToolError`, `lfmap.toml` manifest schema and loader, entry-point discovery (`Registry`), Permission Manager (`fs_read`, `fs_write`, `network`; network paths refused).
- Generated CLI (`lfmap plugins list`, `lfmap <plugin> <operation>`, `--json`, confirmation for operations with side effects) and MCP adapter (`lfmap serve mcp`, tools named `<plugin>_<operation>`).
- Reference plugin `lfmap-echo` with operation `say`.
- CI on Windows with a runtime dependency license check, and CodeQL.
