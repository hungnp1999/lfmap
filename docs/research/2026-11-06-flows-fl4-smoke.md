# Flows FL-4: Windows smoke on pc-01

- Date: 2026-11-06
- Environment: `pc-01` (DIEP-ANH), Windows 11 Pro 10.0.26300, `main` at `6477045` (FL-1..FL-3 merged)
- Task: FL-4 in `docs/handoff/2026-11-06-lfmap-flows.md` (issue #168, part of it)
- Result: **pass** for the event flow, pause, approval in a new process, `flows.run.completed` and idempotent redelivery. **Partial** for the scheduled flow: the `schtasks` command is well formed, but `Invoke-LfmapJob.ps1 -FlowId` could not be run because PowerShell 7 is not installed on this machine. Two procedure and environment findings are listed below; no code or test was changed.

## Setup

- `uv sync`, then `uv run pytest packages/lfmap-core`: **1390 passed, 1 skipped** in 38 s.
- Every process used a throwaway app folder (`LOCALAPPDATA=D:\Development\lfmap-fl4`, set only for the processes of this smoke; `D:\Development\lfmap-fl4b` for the schedule dry-run). The real `%LOCALAPPDATA%\lfmap`, the real Task Scheduler and the real `jobs.toml` were not touched.
- Echo got `[adapters] events = true` only for the run (worktree edit of `plugins/lfmap-echo/src/lfmap_echo/lfmap.toml`, as in EB-4), reverted with `git checkout`, never committed.
- `flows.toml` in the temp folder: `smoke-event` (trigger `event = "echo.say.completed"`, `max_tier = 0`; step `say` = `echo.say` with `text = "${trigger.payload.output.text}"`, `upper = true`; step `review` = `approve`) and `smoke-manual` (`manual = true`, one `echo.say` step). Echo's input fields are `text` and `upper`; the completed payload is `{"output": {"text", "length"}, "request_id"}`.

## Results

| Step | Result | Evidence |
| --- | --- | --- |
| 1. `flows list`, `flows check` | pass | both exit 0; `All flows ok` |
| 2. Event starts the flow and it pauses | pass | see below |
| 3. Approve in a new process | pass | see below |
| 4. Same event delivered twice | pass | still 1 run file, 1 proposal |
| 5a. `jobs register --dry-run` with a scheduled flow | pass | well-formed `schtasks` line (see notes) |
| 5b. `Invoke-LfmapJob.ps1 -FlowId` and its JSON log line | **not run** | no `pwsh` on this machine |

### Step 2

1. `lfmap events run --until-idle` once: `Handled 0 event(s)`; `events status` then lists `adapter-echo` and `flows`.
2. Published `echo.say.requested` `{"input": {"text": "xin chào FL-4"}}` with `open_bus().publish(..., source="core")`, then `lfmap events run --until-idle`: `Handled 2 event(s)`.
3. `events.db`: `echo.say.requested`, then `echo.say.completed` with `causation_id` = the request id and `output.text = "xin chào FL-4"`.
4. `lfmap flows runs`: `ev-<event id>-smoke-event  smoke-event  awaiting_approval`.
5. `lfmap approvals pending`: exactly one proposal, `20261106T080957Z-flows-9b6e31ce  flows  flows.resume  T2  smoke-event/review: Check the echo before it is shared`. Audit line: channel `flow`, decision `queue`.

### Step 3

Each command here ran in its own process, so the process that started the run had long exited. The owner opened a new PowerShell window and ran `lfmap approvals approve 20261106T080957Z-flows-9b6e31ce` at the console (TTY check not bypassed).

- First attempt: `Error [invalid_input]: flow changed; start a new run` (see "Findings" 1).
- After `flows.toml` was restored byte for byte (SHA-256 `c616c551…` equals the run's `flow_sha256`), the second attempt worked: `approvals pending` empty; `flows status` shows `say completed`, `review completed`, run `completed`.
- `events.db` gained `flows.run.completed` `{"flow": "smoke-event", "run_id": "ev-<event id>-smoke-event"}`.
- Audit lines: channel `cli`, `flows.resume`, decisions `approve` then `allow`.

### Step 4

`flows_triggers.handle(registry, event)` was called twice with the stored `echo.say.completed` event (a small script, `attempt=2`). Both calls returned without error; `flows/runs/` still held the single run file and `approvals pending` still listed one proposal.

### Step 5

- `lfmap flows check` with `smoke-daily` (`schedule = { daily = "06:30" }`) exits 0. The dry-run printed (in the second temp folder, after the first smoke run had finished):

  ```text
  schtasks /Create /TN \LFMAP\flow-smoke-daily /TR "\"…\powershell.exe\" -NoProfile -File \"D:\Development\lfmap\scripts\Invoke-LfmapJob.ps1\" -FlowId smoke-daily -RepoPath \"D:\Development\lfmap\" -UvPath \"C:\Users\Admin\AppData\Local\Microsoft\WinGet\Links\uv.EXE\"" /SC DAILY /ST 06:30 /F
  schtasks /Delete /TN \LFMAP\echo-hello /F
  ```

  Nothing was run. The `/Delete` line is the dry-run's plan for a task that exists in the real Task Scheduler but not in the temp `jobs.toml`; it reads the real scheduler, read-only, to build the plan.
- `lfmap flows start smoke-manual` (the command the script would run) works: run `completed`, exit 0, and it published `flows.run.completed` into the existing `events.db`.

## Findings

1. **Resume refuses a changed flow file (expected, positive result).** Step 5 first edited `flows.toml` in the folder that held the pending run (added `smoke-daily`). Approving then failed with `flow changed; start a new run`, which is the designed check (decision 8, spec section 5). Restoring the file made the same proposal approvable. Lesson for the procedure: do not edit `flows.toml` while a run waits; do schedule checks in a second app folder.
2. **`pwsh` 7 is not installed on this machine** (not on `PATH`, not under `C:\Program Files\PowerShell\7`, WindowsApps or WinGet packages). `jobs register --dry-run` without `--pwsh` stops with `Error [not_found]: pwsh was not found; pass --pwsh`. `Invoke-LfmapJob.ps1` uses `??` and does not parse on Windows PowerShell 5.1, so the `-FlowId` run and its JSON log line (`job = flow-smoke-manual`) are **not verified**. To close: install PowerShell 7, then run `pwsh -NoProfile -File scripts\Invoke-LfmapJob.ps1 -FlowId smoke-manual -RepoPath <root>` against a temp `LOCALAPPDATA`.
3. **Long worktree path breaks `jobs register`.** From a worktree under `D:\Development\lfmap\.claude\worktrees\…`, the dry-run failed with `Task action is longer than 261 characters`. A short runtime root (`--repo D:\Development\lfmap`) is fine. Not a defect for the intended use (ADR-023 runtime root), but it explains why the dry-run must not be run from a deep worktree.

No Windows-specific problem with paths or `os.replace` on open files was seen: run files were rewritten after each step and read by later processes without error.

## Cleanup

The echo manifest edit was reverted. The temp folders `D:\Development\lfmap-fl4` and `D:\Development\lfmap-fl4b` hold only smoke data and can be deleted by the owner.
