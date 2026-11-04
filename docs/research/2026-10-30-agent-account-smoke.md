# Agent account AA-4: smoke on pc-01

- Date: 2026-10-30 (GitHub sign-in finished the same evening; AA-5 on 2026-10-31)
- Environment: `pc-01` (DIEP-ANH), Windows 11 Pro, standard account `lfmap-agent` (not an administrator), `main` one commit behind `origin/main`
- Task: AA-4 and AA-5 in `docs/handoff/2026-10-30-agent-account.md` (ADR-023, issue #115)
- Result: **pass**. Every isolation check passed: the agent account cannot read the owner's profile or private folders and cannot write the runtime clone. Tests, Ollama, a signed commit and Word all work under the agent account. The two first-run failures (Claude Code not on `PATH`, GitHub CLI not signed in) were setup gaps, fixed the same day.

## Method

The owner signed in to Windows as `lfmap-agent` and ran a PowerShell 5.1 smoke script from a normal terminal. The script prints one `PASS`, `FAIL` or `INFO` line per check. It writes only under `D:\Tmp`: its log, a separate virtual environment (`UV_PROJECT_ENVIRONMENT`) so the shared `.venv` was untouched, and a throwaway git repository. "Must be denied" checks pass when Windows refuses the access. The scripts are kept outside the repository, with the other ADR-023 setup scripts.

## Results

| Area | Check | Result |
| --- | --- | --- |
| Identity | runs as `lfmap-agent`, process not elevated | PASS |
| Tools | `uv`, `git`, `gh` on `PATH` | PASS |
| Tools | `claude` on `PATH` | FAIL, fixed (see below) |
| Provenance | `DEV_ENVIRONMENT=pc-01` | PASS |
| Repository | `git status` in `D:\Development\lfmap` | PASS |
| Tests | `uv sync`; `uv run pytest packages/lfmap-core`: 976 passed, 1 warning, 23.8 s | PASS |
| Ollama | `GET http://localhost:11434/api/version` (0.40.13) | PASS |
| Allowed writes | `D:\Tmp`, `D:\Development` | PASS |
| Owner profile | `%LOCALAPPDATA%\lfmap`, `.ssh`, GitHub CLI config, `.claude` of the owner | PASS (denied) |
| Private folders | four top-level folders on `D:` with a deny entry for the agent | PASS (denied) |
| Runtime clone | write to `D:\lfmap-runtime` denied, read allowed | PASS |
| Credentials | Credential Manager shows only the agent's own entry | INFO |
| Signing | commit in a throwaway repository carries a signature (`git_signing_pc01_agent`) | PASS |
| GitHub | `gh auth status` | FAIL, fixed (see below) |
| Office | Word 16.0 starts through COM within 60 s | PASS |

## Fixes after the first run

- **Claude Code.** The native installer puts `claude.exe` in `%USERPROFILE%\.local\bin` but did not add it to the agent's user `PATH`. Adding that folder to the user `PATH` fixed it (`claude` 2.1.314).
- **GitHub CLI.** `gh auth login --with-token` rejected the fine-grained token `lfmap-agent-pc01` with HTTP 401 during its own validation, although the token was valid. The token is instead kept in the agent account's `GH_TOKEN` user variable, which only that account (and administrators) can read. With it, `gh api user` and `git ls-remote` over HTTPS both pass. The token is limited to Contents, Pull requests and Issues (read and write) on lfmap, MarkitdownTool and isomp, and expires after 90 days.

## AA-5: jobs and MCP on the runtime clone

On 2026-10-31 the owner ran a setup script from the owner account:

- `git -C D:\lfmap-runtime pull --ff-only`;
- `[runtime] root = 'D:\lfmap-runtime'` appended to `jobs.toml` (backup kept);
- `lfmap jobs register` from the runtime: the task `\LFMAP\echo-hello` now runs `D:\lfmap-runtime\scripts\Invoke-LfmapJob.ps1 -RepoPath "D:\lfmap-runtime"`;
- the user-scope `lfmap` MCP server in Claude Code repointed to `uv run --directory D:\lfmap-runtime lfmap serve mcp`. The script skips this step while any `claude` process runs, because Claude rewrites `~\.claude.json`; Claude Desktop counts as such a process.

`lfmap jobs doctor` exits 0. `runtime_root` and `runtime_acl` are `ok`. The two warnings are unrelated to ADR-023: `logon_mode` (the job runs only while the owner is signed in) and `ollama` (no enabled job uses the network).

A Task Scheduler task outside `\LFMAP\` (`\LFMAP-Runtime\update`, hourly and at logon) now keeps the runtime in step with `main`. It runs an updater kept in the owner's profile. The updater skips the run when the clone is not on `main` or has local changes, only fast-forwards, and runs `jobs doctor` after each update. It logs one line per run to `%LOCALAPPDATA%\lfmap\logs\runtime-update.log`.

## Notes

- `Start-Process -Credential` starts a process as `lfmap-agent` but keeps the caller's environment (`USERNAME`, `LOCALAPPDATA`). Do not use it for agent work: use `runas` or switch the Windows user.
- The owner's `pwsh` may be the Microsoft Store build, which the agent account cannot start. Use `C:\Program Files\PowerShell\7\pwsh.exe` for anything both accounts run.
- Open follow-up: `jobs doctor` does not yet check the owner of the runtime folder (#120).
