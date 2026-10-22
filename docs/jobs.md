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
uv run lfmap jobs doctor           # read-only machine check; exit 1 when a check is FAIL
```

`register` creates or updates (`/F`) a task for every enabled job and deletes the tasks of jobs that are disabled
or no longer in `jobs.toml`. It only ever touches tasks directly in `\LFMAP\`. `--dry-run` prints the
`schtasks` commands without running them. `--repo` (default: this checkout) and `--uv` (default: `uv` on
`PATH`, then `%LOCALAPPDATA%\Microsoft\WinGet\Links\uv.exe`) are written into each task. So is the full path of
PowerShell 7 (`--pwsh`; default `%ProgramFiles%\PowerShell\7\pwsh.exe`, then the Microsoft Store alias
`%LOCALAPPDATA%\Microsoft\WindowsApps\pwsh.exe`, then `PATH`): Task Scheduler cannot start the Store `pwsh` by
name, and the task then fails with `0x80070002`.

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

## Checking the machine

`uv run lfmap jobs doctor [--json]` checks, without changing anything, that this machine can run the jobs. It
only runs `schtasks /Query` and `powercfg /query`, and asks Ollama for its version. Each line shows the check,
`ok`, `warn` or `FAIL`, what was found and, after `->`, how to fix it. It exits 1 when any check is `FAIL`;
`warn` never fails. `--json` prints a list of `{name, ok, detail, fix}` with `ok` `true`, `null` (warn) or `false`.

| Check | `ok` | `warn` | `FAIL` |
| --- | --- | --- | --- |
| `uv` | uv found (same rule as the runner script) | | uv not found |
| `pwsh` | PowerShell 7 found, and every task starts it by full path | | not found, or a task starts plain `pwsh`; run `register` |
| `jobs_file` | `jobs.toml` valid, every plugin and operation exists | no `jobs.toml` | invalid file, or a job names an unknown plugin or operation |
| `tasks` | a task in `\LFMAP\` for each enabled job, and no other | no `schtasks`, or no job and no task | a task is missing, or a disabled or removed job still has one; run `register` |
| `logon_mode` | every task runs whether you are logged on or not | a task runs only while you are logged on (`InteractiveToken`), or no task | |
| `wake` | the machine never sleeps on AC power, or every task has "Wake the computer" | no task, no `schtasks`, or sleep unknown | the machine sleeps and a task does not wake it |
| `sleep` | never sleeps on AC power | sleeps after N minutes, or `powercfg` unreadable | |
| `ollama` | `http://localhost:11434/api/version` answers | no enabled job uses a plugin with `permissions.network = true` | needed but not answering; start Ollama |

Only tasks of enabled jobs are inspected. On Linux or CI, where `schtasks` and `powercfg` do not exist, those
checks are `warn`. A task that runs only while you are logged on still runs at the lock screen; see below to
change it. Running `register` again resets the logon and wake settings, so `logon_mode` and `wake` go back to
`warn` or `FAIL` until you set them again.

## Running while signed out

Tasks created by `register` run as you and only while you are signed in (logon type "Interactive only").
The CLI never asks for or stores your Windows password. To run jobs at the lock screen or after sign-out,
set it once per task by hand:

1. Open Task Scheduler and select the `LFMAP` folder.
2. Open the task's Properties, General tab: choose "Run whether user is logged on or not", then OK and enter
   your Windows password when asked.
3. Optional, Conditions tab: tick "Wake the computer to run this task" so a sleeping machine does not miss it.

Running `register` again replaces the task (`/F`) and resets these settings, so repeat them afterwards.
