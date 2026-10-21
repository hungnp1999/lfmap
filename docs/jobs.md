# Scheduled jobs

A job runs one plugin operation on a schedule, with nobody at the keyboard (ADR-018). Windows Task Scheduler
does the scheduling: every job is a task in the `\LFMAP\` folder that runs `scripts\Invoke-LfmapJob.ps1`,
which calls `lfmap jobs run <id>`. LFMAP has no scheduler loop of its own.

## Declaring jobs

Jobs live in `%LOCALAPPDATA%\lfmap\jobs.toml` (the `LFMAP_JOBS` environment variable overrides the path).

```toml
[[jobs]]
id = "echo-hello"                 # lower case letters, digits and "-", starting with a letter; unique
plugin = "echo"
operation = "say"
input = { text = "xin chào" }
schedule = { daily = "07:30" }    # or { weekly = "MON 07:30" } or { every_minutes = 60 } (1-1439)
max_tier = 0                      # 0 = only T0 runs; 1 = T1 runs and is audited
enabled = true
```

A job never runs with `--yes`, never asks anyone and ignores grants, `serve mcp --approve` and preapproved
destinations. What a call does depends on its tier (ADR-017) and the job's `max_tier`:

| Tier | `max_tier = 0` | `max_tier = 1` |
|---|---|---|
| T0 (no side effects) | runs | runs |
| T1 (new files) | queued for approval | runs, audited |
| T2 (overwrite, rename, delete) | queued for approval | queued for approval |
| T3 (external) | queued for approval | queued for approval |

`[approval]` in `config.toml` can only tighten this: `deny` refuses the call without queueing it, and T1 set
to `ask` is queued. Every decision above T0 is written to `audit.jsonl` with channel `job`.

## Approving queued calls

A queued call is not run. The job exits 1 with `Error [permission_denied]: Queued for approval` and writes a
proposal to `%LOCALAPPDATA%\lfmap\approvals\pending\<id>.json` (job, plugin, operation, input, tier, reason).
A job that keeps hitting the same call reuses its pending proposal instead of writing a new one.

```powershell
uv run lfmap approvals pending          # proposals waiting; expired ones move to approvals\expired
uv run lfmap approvals approve <id>     # shows the proposal, asks, then runs it once
uv run lfmap approvals reject <id>
```

- `approve` and `reject` only work in an interactive terminal, and neither is available over MCP, so an agent
  cannot approve its own work.
- `approve` moves the proposal to `approvals\done` before running it, so it never runs twice. It runs with the
  job's own rights, plus whatever its recorded tier covers. If the run needs a higher tier, you are asked again.
- `reject` moves it to `approvals\rejected`.
- Both are audited.
- Proposals expire after 7 days (`[jobs] approval_ttl_days` in `config.toml`, 1 to 30).
- Proposal files are never deleted, only moved between `pending`, `done`, `rejected` and `expired`. Clean them
  up by hand if you want to.

`approvals list` still lists time-limited grants.

## Commands

```powershell
uv run lfmap jobs list              # id, plugin.operation, schedule, enabled
uv run lfmap jobs run echo-hello    # run one job now; exit 0 success, 1 ToolError, 2 other error
uv run lfmap jobs register --dry-run
uv run lfmap jobs register
```

`register` creates or updates (`/F`) a task for every enabled job and deletes the tasks of jobs that are disabled
or no longer in `jobs.toml`. It only ever touches tasks directly in `\LFMAP\`. `--dry-run` prints the
`schtasks` commands without running them. `--repo` (default: this checkout) and `--uv` (default: `uv` on
`PATH`, then `%LOCALAPPDATA%\Microsoft\WinGet\Links\uv.exe`) are written into each task.

## The runner script

`scripts\Invoke-LfmapJob.ps1 -JobId <id> [-RepoPath <repo>] [-UvPath <uv.exe>]` runs
`uv run --directory <repo> lfmap jobs run <id> --json`, appends one JSON line to
`%LOCALAPPDATA%\lfmap\logs\jobs-YYYY-MM-DD.jsonl` (`started`, `finished`, `job`, `exit_code`, and `stdout`
and `stderr` cut to 4000 characters) and exits with the code of `lfmap`. It exits 2 when uv cannot be found.

Run it by hand to check a job before registering it:

```powershell
pwsh -NoProfile -File .\scripts\Invoke-LfmapJob.ps1 -JobId echo-hello; $LASTEXITCODE   # 0
pwsh -NoProfile -File .\scripts\Invoke-LfmapJob.ps1 -JobId khong-co;   $LASTEXITCODE   # 1
Get-Content "$env:LOCALAPPDATA\lfmap\logs\jobs-$(Get-Date -Format yyyy-MM-dd).jsonl" -Tail 2
```

## Running while signed out

Tasks created by `register` run as you and only while you are signed in (logon type "Interactive only").
The CLI never asks for or stores your Windows password. To run jobs at the lock screen or after sign-out,
set it once per task by hand:

1. Open Task Scheduler and select the `LFMAP` folder.
2. Open the task's Properties, General tab: choose "Run whether user is logged on or not", then OK and enter
   your Windows password when asked.
3. Optional, Conditions tab: tick "Wake the computer to run this task" so a sleeping machine does not miss it.

Running `register` again replaces the task (`/F`) and resets these settings, so repeat them afterwards.
