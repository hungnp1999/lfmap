# Module Spec: plugin `powershell` (Roadmap 1.6)

Version 0.1 · 2026-10-22 · Status: agreed for implementation (handoff `docs/handoff/2026-10-22-powershell-plan.md`).

## 1. Purpose

Let an agent (MCP), the CLI or a scheduled job run **PowerShell 7 scripts that the user allow-listed**, with typed, checked parameters. The plugin never runs arbitrary commands (Blueprint §4: "allow-list, no arbitrary commands"). Roadmap 1.6 result: "run an approved script from MCP".

## 2. Decisions

| # | Decision | Rejected options |
|---|---|---|
| P1 | The allow-list lives in `config.toml` under `[plugins.powershell.settings.scripts.<id>]`. No operation or MCP tool writes `config.toml` (core rule), so an agent cannot add a script. | A separate `scripts.toml` (one more file and loader, same protection); an `add` operation (an agent could allow-list its own script). |
| P2 | `run` declares `side_effects = "external"` with `min_tier = "T1"`. Each allow-list entry has `tier = "T1" | "T2" | "T3"`, **default T3** (ADR-020, amending ADR-017). Core asks the plugin for the call's tier before running and clamps it to T1..T3. T3: over MCP only under a time-limited grant made in an interactive terminal (`lfmap approvals grant powershell.run --tier T3 --for 2h`); the interactive CLI asks; jobs queue it (ADR-018). T2: asks, or a grant / `serve mcp --approve`. T1: runs and is audited (jobs need `max_tier >= 1`). | All scripts T3 (read-only scripts would need a broad grant); a separate `run_safe` operation (the boundary would be the operation name the agent picks, not the user's config); T0 scripts (no audit trail for an external command). |
| P3 | Each entry pins the script's **SHA-256**. `run` reads the file once, checks the hash, writes those exact bytes to a fresh copy in the plugin's temp folder and runs the copy, so the file cannot change between check and start. The working directory is the script's own folder. | Run the original path (time-of-check/time-of-use gap); no hash (any later edit to the script runs silently). |
| P4 | Script paths must be inside `[paths] scripts` (manifest `fs_read = ["${scripts}"]`) and go through `require_read`, so UNC and device paths are refused before any I/O. | Trust the path in config (bypasses the shared security rule). |
| P5 | Parameters are typed in the allow-list (`string`, `int`, `switch`, `choice`) and passed as an argument list to `pwsh -NoProfile -NonInteractive -NoLogo -File <copy> -Name value ...`, never through a shell or `-Command`. Strings may not start with `-` and may not contain control characters or `"`. | `-Command` with a built string (injection); free-form argument arrays (an agent could pass any switch). |
| P6 | A non-zero exit code is a normal result (`exit_code`), not an error. A timeout kills the whole process tree and returns `timed_out = true`. | Mapping exit codes to `ToolError` (loses the output the agent needs to explain the failure). |
| P7 | No new dependency (standard library `subprocess`). `pwsh` comes from `settings.pwsh` (absolute local path) or `PATH`. | — |

## 3. Configuration

```toml
[paths]
scripts = ['D:\Scripts']                     # string or list, like other [paths] entries

[plugins.powershell.settings]
pwsh = 'C:\Program Files\PowerShell\7\pwsh.exe'   # optional; default: pwsh on PATH

[plugins.powershell.settings.scripts.disk-report]
path = 'D:\Scripts\Get-DiskReport.ps1'
sha256 = "3F2A..."            # (Get-FileHash -Algorithm SHA256 <path>).Hash; case ignored
description = "Free space per drive"
timeout_s = 60                # 1..3600, default 60
max_output_chars = 20000      # 1000..200000, default 20000, per stream
tier = "T1"                   # T1 | T2 | T3, default T3 (ADR-020); only lower it for read-only scripts

[plugins.powershell.settings.scripts.disk-report.params.Drive]
type = "string"               # string | int | switch | choice (default string)
required = true
pattern = "[A-Z]"             # string only; full match
# max_length = 256            # string only, 1..4096
# min = 0, max = 2147483647   # int only, min >= 0
# choices = ["fast", "full"]  # choice only, non-empty, each a safe string
```

Rules:

- Script id: `^[a-z][a-z0-9-]{0,39}$`. Parameter name: `^[A-Za-z][A-Za-z0-9]{0,39}$`; two names that differ only in case are invalid (PowerShell ignores case).
- An entry with unknown keys, a bad hash, a pattern that does not compile, `min > max`, a `choice` without choices, an unsafe choice, or a required `switch` is **invalid**: `list` shows it with the reason, `run` refuses it, other entries still work.
- `scripts` that is not a table: `invalid_input` for every operation.

## 4. Operations

### `list` (side_effects `none`, T0)

Input: none. Output `ListOutput.scripts: list[ScriptInfo]`, sorted by id:

| Field | Meaning |
|---|---|
| `id`, `description`, `path`, `timeout_s` | From the entry (empty/0 for an invalid entry). |
| `params: list[ParamInfo]` | `name`, `type`, `required`, `pattern`, `min`, `max`, `choices`, in allow-list order. |
| `ready` | `run` would start the script now: entry valid, path inside `${scripts}`, file readable, hash matches. |
| `problem` | Why not ready: `invalid id: ...`, `invalid entry: ...`, or the message of the `ToolError` from the path/read/hash check. |

`list` does not need `pwsh` and starts no process.

### `run` (side_effects `external`, tier from the entry: T1..T3, default T3)

Input `RunInput`: `script` (id, pattern as above), `params: dict[str, str | int | bool]` (default empty). The CLI takes it as `--input-json`.

Steps, in this order (nothing is started before step 6):

1. Load the allow-list. Invalid entry: `invalid_input` (details carry the reason). Unknown id: `not_found` (details list allowed ids).
2. Build arguments (`build_args`): unknown name, missing required, wrong type, out of range, not in choices, unsafe string or pattern mismatch: `invalid_input`. Arguments follow allow-list order; `switch` true adds `-Name`, false adds nothing; `int` is passed in decimal.
3. `require_read(entry.path)`: outside `${scripts}` or UNC: `permission_denied`.
4. Read bytes; unreadable or missing: `not_found`. SHA-256 differs: `permission_denied` with `expected` and `actual` in details.
5. Resolve `pwsh`: bad `settings.pwsh`: `invalid_input`; not found: `backend_unavailable`.
6. `ctx.dry_run`: return `dry_run = true` and `command`, start nothing, audit nothing.
7. Write the bytes to `<temp_dir>/<tmp folder>/<id>-<8 hex>.ps1`, run `[pwsh, -NoProfile, -NonInteractive, -NoLogo, -File, <copy>, *args]` in the script's folder with the entry's timeout and output limit, then delete the copy (also on error).
8. Append one audit line: `channel`, `plugin = powershell`, `operation = run`, `tier = <entry tier>`, `decision = allow`, `reason = "exit <code>"` or `"timeout"`, `target = <id>`. Never the output.

Output `RunOutput`: `script`, `dry_run`, `command` (with the **allow-listed** path, not the copy), `exit_code` (null on timeout), `stdout`, `stderr` (UTF-8, invalid bytes replaced, cut to `max_output_chars` each), `stdout_truncated`, `stderr_truncated`, `timed_out`, `duration_ms`, `untrusted = true`, `notice`.

## 5. Process runner (`runner.run_process(argv, cwd, timeout_s, max_chars) -> ProcessResult`)

- No shell; `stdin` is `DEVNULL`; stdout and stderr captured.
- Windows: `CREATE_NO_WINDOW`; on timeout `taskkill /T /F /PID <pid>` then `kill()`. POSIX: new session; on timeout `killpg(SIGKILL)` then `kill()`. Output already written is kept.
- Starting fails (`OSError`): `backend_unavailable`.
- The tool calls it as `runner.run_process` (module attribute) so tests can replace it.

## 6. Module layout

```text
plugins/lfmap-powershell/
├── pyproject.toml          # entry point powershell = "lfmap_powershell.tool:PowerShellTool"; deps: lfmap-core only
├── README.md               # product page: setup, hash command, grant command, limits
├── LICENSE                 # Apache-2.0
├── src/lfmap_powershell/
│   ├── __init__.py
│   ├── lfmap.toml          # list (none), run (external); fs_read ["${scripts}"], exec ["pwsh"], network false
│   ├── allowlist.py        # SCRIPT_ID, PARAM_NAME, ParamSpec, ScriptEntry, load_allowlist, build_args, unsafe_reason, sha256_hex
│   ├── runner.py           # ProcessResult, run_process
│   ├── schemas.py          # ListInput, ParamInfo, ScriptInfo, ListOutput, RunInput, RunOutput, NOTICE
│   └── tool.py             # pwsh_path, PowerShellTool (health, list, run)
└── tests/                  # test_allowlist.py, test_runner.py, test_tool.py
```

Workspace: add `lfmap-powershell` to the root `pyproject.toml` (dependencies and `[tool.uv.sources]`), to `WORKSPACE` in `scripts/check_licenses.py`, and `"scripts"` to `FOLDER_NAMES` in `lfmap_core/config.py` so `lfmap config add-folder scripts <dir>` works.

## 7. Security notes

- The script itself runs with the user's full rights; the plugin only controls **which** script and **which** arguments. That is why `run` defaults to T3, why a lower tier must be written per script, and why allow-listing stays a hand edit of `config.toml`.
- A grant on `powershell.run` covers every allow-listed script for its duration. Keep the allow-list short.
- Script output goes back to the caller (over MCP, to Claude). Do not allow-list scripts that print secrets.
- `$PSScriptRoot` points at the temporary copy; scripts should use the working directory (`Get-Location`) to find files next to them.
- Non-ASCII output: scripts should set `[Console]::OutputEncoding = [Text.Encoding]::UTF8` first; the runner decodes UTF-8.

## 8. Not in scope (Phase 1)

Path-typed parameters checked against roots, exit-code-to-job-failure mapping, streaming output, running as another user, Windows PowerShell 5.1.
