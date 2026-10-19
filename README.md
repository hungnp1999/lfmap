# LFMAP — Local-First Modular Automation Platform

> Everything is a Tool, every Tool is a Plugin, every Plugin is a Product.

LFMAP is a plugin-based automation platform that runs on your own machine. A plugin writes its business logic once, as a `Tool` class with Pydantic input and output models, and gets a Python SDK, a CLI and an MCP server for free.

Status: **Phase 0 (foundation)**. Only the reference plugin `echo` exists.

## Layout

| Path | What |
| --- | --- |
| `packages/lfmap-core` | `Tool`, `@operation`, `ToolError`, `lfmap.toml` manifest, plugin discovery, Permission Manager, generated CLI and MCP adapters |
| `plugins/lfmap-echo` | Reference plugin with one operation, `say` |
| `docs/phase0/` | Phase 0 acceptance documents (Vietnamese): architecture, functional spec, test cases, user guide, runbook |
| `scripts/check_licenses.py` | CI check: runtime dependencies must use a license the plugin manifests allow |

## Quick start (Windows, PowerShell 7)

```powershell
uv sync
uv run pytest
uv run lfmap plugins list
uv run lfmap echo say --text "xin chào" --upper
uv run lfmap serve mcp --plugins echo        # MCP server over stdio
```

Add the MCP server to Claude Code:

```powershell
claude mcp add lfmap -- uv run --directory D:\Development\lfmap lfmap serve mcp --plugins echo
```

Each operation becomes an MCP tool named `<plugin>_<operation>` (for example `echo_say`), because Claude only accepts tool names made of letters, digits, `_` and `-`.

## Writing a plugin

1. Create `plugins/lfmap-<name>/` with `pyproject.toml`, `src/lfmap_<name>/lfmap.toml`, `schemas.py` and `tool.py` (copy `lfmap-echo`).
2. Register the entry point under `[project.entry-points."lfmap.plugins"]`; the name must equal the plugin id.
3. Every method marked `@operation("name")` takes one Pydantic model and returns one, and must be declared in `[[operations]]` of `lfmap.toml`.
4. Raise `ToolError(code, message, details)` for business errors. Codes: `invalid_input`, `permission_denied`, `not_found`, `backend_unavailable`, `timeout`, `internal`.
5. Check file access with `self.ctx.permissions.require_read(path)` / `require_write(path)`; only what `[permissions]` declares is granted.

## Folders and approvals

Folders a plugin may touch come from your own config file, `%LOCALAPPDATA%\lfmap\config.toml` (or the file named by `LFMAP_CONFIG`). No operation writes it, so a caller such as an AI agent cannot widen them.

```toml
[paths]
documents = ['D:\Docs', 'E:\Scans']   # used as ${documents} in a manifest's [permissions]
exports = 'D:\Docs\_markdown'
```

- Each value must be an absolute local path; network paths (`\\server\share`, `//host`) are refused. A list gives one folder per entry.
- `${data_dir}` and `${temp_dir}` are built in: `%LOCALAPPDATA%\lfmap\<plugin>` and its `tmp` subfolder.
- A variable you have not defined grants nothing, so every path under it is refused.

Operations with side effects (`side_effects` other than `none`) ask before running in the CLI (`--yes` skips the prompt). Over MCP an agent cannot confirm for you, so they are refused unless you approve them when starting the server:

```powershell
uv run lfmap serve mcp --plugins markitdown --approve markitdown.export
```

Operations with `external` side effects cannot be pre-approved.

## License

Apache-2.0.
