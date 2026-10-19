# Changelog

## [Unreleased]

### Added

- uv workspace (Python 3.12), ruff, pytest, pre-commit.
- `lfmap-core` 0.1.0: `Tool`, `@operation`, `invoke`, `ToolError`, `lfmap.toml` manifest schema and loader, entry-point discovery (`Registry`), Permission Manager (`fs_read`, `fs_write`, `network`; network paths refused).
- Generated CLI (`lfmap plugins list`, `lfmap <plugin> <operation>`, `--json`, confirmation for operations with side effects) and MCP adapter (`lfmap serve mcp`, tools named `<plugin>_<operation>`).
- Reference plugin `lfmap-echo` with operation `say`.
- CI on Windows with a runtime dependency license check, and CodeQL.
- User config `%LOCALAPPDATA%\lfmap\config.toml` (`LFMAP_CONFIG` overrides): `[paths]` defines the folders behind `${name}` variables in `[permissions]`; built-in `${data_dir}` and `${temp_dir}` per plugin.
- `lfmap serve mcp --approve <plugin>.<operation>`; MCP tools carry read-only and open-world hints.
- `ToolContext` gains `data_dir`, `temp_dir`, `settings` (from `[plugins.<id>.settings]`), `channel` and `approver`; `build_tool` and `run_operation` take `channel` and `approver`; new `runtime.context_for` builds a context for calling another plugin in-process with the caller's permissions.

### Changed

- CLI and MCP now expand permission variables from the user config instead of none. A list variable gives one root per entry; an undefined variable grants nothing (with a warning) instead of failing the whole plugin. Relative roots are refused, and so is a root that resolves to a network path.

### Security

- MCP refuses operations with side effects unless the user approved them with `--approve` when starting the server (ADR-009). Operations with `external` side effects cannot be pre-approved.
