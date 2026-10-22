# lfmap-powershell

LFMAP plugin that lets an agent (MCP), the CLI or a scheduled job run **PowerShell 7 scripts that you allow-listed**, with typed, checked parameters. It never runs arbitrary commands: you choose the scripts by editing `config.toml` by hand, each one pinned to its SHA-256. Roadmap Phase 1, item 1.6. Spec: [`docs/specs/powershell.md`](../../docs/specs/powershell.md).

| Operation | What it does | Side effects |
| --- | --- | --- |
| `list` | Allow-listed scripts, their parameters, and whether each can run now (`ready`, `problem`) | none (T0) |
| `run` | Run one allow-listed script; returns exit code, stdout, stderr and duration | external (T3) |

## Setup

1. Put your scripts in one folder and add it to your config (interactive terminal only, so an agent cannot widen it):

   ```powershell
   uv run lfmap config add-folder D:\Scripts --as scripts
   ```

2. Get the hash of each script:

   ```powershell
   (Get-FileHash -Algorithm SHA256 D:\Scripts\Get-DiskReport.ps1).Hash
   ```

3. Allow-list it in `%LOCALAPPDATA%\lfmap\config.toml`:

   ```toml
   [plugins.powershell.settings]
   pwsh = 'C:\Program Files\PowerShell\7\pwsh.exe'   # optional; default: pwsh on PATH

   [plugins.powershell.settings.scripts.disk-report]
   path = 'D:\Scripts\Get-DiskReport.ps1'
   sha256 = "3F2A..."            # from step 2; case ignored
   description = "Free space per drive"
   timeout_s = 60                # 1..3600, default 60
   max_output_chars = 20000      # 1000..200000, default 20000, per stream

   [plugins.powershell.settings.scripts.disk-report.params.Drive]
   type = "string"               # string | int | switch | choice (default string)
   required = true
   pattern = "[A-Z]"             # string only; the whole value must match
   # max_length = 256            # string only, 1..4096
   # min = 0, max = 100          # int only, min >= 0
   # choices = ["fast", "full"]  # choice only
   ```

   - Script id: lower case letters, digits and `-`, starting with a letter, at most 40 characters. Parameter names: letters and digits; two names that differ only in case are refused.
   - String values may not be empty, start with a dash, or contain `"` or control characters.
   - An invalid entry shows up in `list` with the reason; the other entries still work.
   - Every time you edit a script, update its `sha256`. Until you do, `run` refuses it.

4. Check: `uv run lfmap powershell list --json` shows `"ready": true`.

## Running a script

`run` is tier T3 ("runs external commands", ADR-017):

- **Interactive CLI**: asks you before it runs.

  ```powershell
  uv run lfmap powershell run --input-json '{"script": "disk-report", "params": {"Drive": "C"}}'
  ```

- **MCP** (Claude): runs only while a time-limited grant you made in an interactive terminal is valid. `--approve` cannot pre-approve it.

  ```powershell
  uv run lfmap approvals grant powershell.run --tier T3 --for 2h
  ```

- **Jobs**: a `powershell.run` job is queued in `lfmap approvals pending` until you approve it.

A non-zero exit code is a normal result (`exit_code`), not an error. At the timeout the whole process tree is killed and `timed_out` is true. Each run writes one audit line (script id and exit code, never the output).

How it runs: the plugin reads the script once, checks the hash, writes those exact bytes to a fresh copy in `%LOCALAPPDATA%\lfmap\powershell\tmp\` and runs `pwsh -NoProfile -NonInteractive -NoLogo -File <copy> -Name value ...` in the script's own folder, without a shell. The copy is deleted afterwards.

## Writing scripts for this plugin

- Declare parameters with `param(...)` matching the allow-list types: `[string]`, `[int]`, `[switch]`.
- `$PSScriptRoot` points at the temporary copy. Use the working directory (`Get-Location`) to find files next to the script.
- For non-ASCII output, start with `[Console]::OutputEncoding = [Text.Encoding]::UTF8`; the plugin decodes output as UTF-8.

## Limits and security

- The script runs with **your full user rights**. The plugin only controls which script runs and with which arguments. That is why `run` is T3 and why the allow-list is a hand edit of `config.toml`.
- A grant on `powershell.run` covers **every** allow-listed script while it lasts. Keep the allow-list short.
- Script output goes back to the caller, over MCP to Claude (marked `untrusted`). Do not allow-list scripts that print secrets.
- Not supported yet: path-typed parameters, per-script tiers, mapping exit codes to job failures, streaming output, running as another user, Windows PowerShell 5.1.
