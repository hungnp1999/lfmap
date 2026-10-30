# EventBus EB-4: Windows smoke on pc-01

- Date: 2026-10-30
- Environment: `pc-01` (DIEP-ANH), Windows 11 Pro 10.0.26200, Python 3.12.10, `main` at `616f5ac` (EB-3 merged)
- Task: EB-4 in `docs/handoff/2026-10-29-eventbus.md` (issue #100)
- Result: **pass**. Two processes drained one durable subscription with no duplicate and no missing event. Echo requests were answered with `.completed`. The drain at the end of `jobs run` stayed within its bound. No SQLite lock error or wait was seen.
- Also found: a **pre-existing** weakness in the CLI's interactive-terminal check on Windows (see "Finding"). It is not caused by the EventBus work.

## Setup

- `uv sync`, then `uv run pytest packages/lfmap-core`: **935 passed** in 13.4 s.
- Every process used a throwaway app folder (`LOCALAPPDATA=D:\Development\lfmap-eb4\appdata`, set only for the processes started for this smoke). The real `%LOCALAPPDATA%\lfmap` was never touched. Processes were started from `.venv\Scripts\` directly, so `uv` kept its own cache under the real `LOCALAPPDATA`.
- Echo got `[adapters] events = true` only for the run. The change was made in the worktree's `plugins/lfmap-echo/src/lfmap_echo/lfmap.toml` (editable install), reverted afterwards, and never committed.
- The helper scripts were kept outside the repository:
  - publish: creates the subscription `smoke` (`smoke.>`) and publishes N `smoke.item` events with `source="core"`, or N `echo.say.requested` events after attaching the adapter.
  - worker: waits for a shared start time, subscribes `smoke` with a handler that sleeps 10 ms and logs `pid event-id`, then drains in batches of 100 until idle.
  - check: reads `SqliteBus.counts()` and the `events` table of `events.db`.

## Results

### A. Two Python workers on one durable subscription

200 events were published per run (0.42–0.43 s per batch), then two worker processes started at the same instant.

| Run | Worker 1 | Worker 2 | Log lines | Distinct ids | Duplicates | Wall time |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 105 | 95 | 200 | 200 | 0 | 1.58 s |
| 2 | 96 | 104 | 200 | 200 | 0 | 1.78 s |
| 3 | 88 | 112 | 200 | 200 | 0 | 1.72 s |

`counts()` after run 3: `smoke` ready 0, leased 0, done 600, dead 0. Both processes did real work in every run, and leases held: no event was handled twice.

### B. Two `lfmap events run --until-idle` processes on 200 echo requests

200 `echo.say.requested` events were published with `{"input": {"text": "xin chào <i>"}}`. Then two `lfmap events run --until-idle` processes were started in parallel.

- The two processes printed `Handled 182 event(s)` and `Handled 18 event(s)`. The second one started later because CLI start-up takes about 5 s.
- `adapter-echo` ended with done 200 and dead 0.
- `events.db` held 200 requests, 200 `echo.say.completed` events and 200 distinct `request_id` values: 0 duplicates, 0 missing.
- Sample payload: `{"output": {"length": 10, "text": "xin chào 0"}, "request_id": "8d07…"}`. Vietnamese text survived the round trip.

### C. One request, then `jobs run`

1. **One request.** It was published with `uv run python -c "…open_bus().publish('echo.say.requested', {'input': {'text': 'EB-4 smoke', 'upper': True}}, source='core')…"`. `lfmap events run --until-idle` then handled 1 event in 5.36 s wall time. Exactly one event followed with `causation_id` set to the request id: `echo.say.completed` `{"output": {"length": 10, "text": "EB-4 SMOKE"}, "request_id": <request id>}`.
2. **`jobs run` on an echo job.** The job was `echo-hello` in the throwaway `jobs.toml`, run with `lfmap jobs run echo-hello --json`.

   | Queue before | Handled | Wall time |
   | --- | --- | --- |
   | empty | 0 | 5.36 s |
   | 50 requests | 50 (`Handled 50 event(s)` on stderr) | 5.68 s |
   | 5 requests, `--max-events 2` | 2, leaving 3 ready (checked with `events status`) | n/a |

   The `--json` stdout stayed the job's output only.
3. **Baseline.** `lfmap plugins list` takes 5.35 s. Nearly all of the wall time above is CLI start-up (plugin discovery imports markitdown and knowledge), and draining 50 echo requests adds about 0.3 s.

### Locks

None of the runs reported `database is locked`, a timeout, or a retry. Two processes contended for leases on one WAL database without visible waits. The 30 s busy timeout was never approached.

## Finding: the interactive-terminal check passes with stdin from `NUL` (pre-existing)

`cli._interactive()` is `sys.stdin.isatty()`. On Windows, `NUL` is a character device, so `os.isatty()` returns True when stdin is redirected from it (`<NUL` in PowerShell or cmd, `</dev/null` in Git Bash). Some agent shells start commands with stdin on `NUL`. In this session's own Bash tool, a plain `python -c "import os; print(os.isatty(0))"` printed True. Commands that should need a person therefore run for an agent or script:

- `lfmap approvals grant echo.say --tier T3 --for 1h </dev/null` succeeded in the throwaway folder. It printed `Granted echo.say up to T3 until …`, and the grant was revoked right after.
- `lfmap events prune </dev/null` ran instead of failing with `permission_denied`.
- `config add-folder`, `approvals revoke` and `events retry` use the same check. `approvals approve` is safer because it also calls `typer.confirm`, which aborts at end of file.
- With a pipe (`echo y | lfmap events prune`), the check works and the command is refused.

This goes against the invariant that self-granting commands run only at a TTY (ADR-017). It is outside the scope of EB-4, so nothing is changed in this PR. Suggested fix, as a separate `security-review` task:

- On Windows, treat stdin as interactive only when `GetConsoleMode` succeeds on the stdin handle. Use `ctypes` with `kernel32.GetConsoleMode(msvcrt.get_osfhandle(0), …)`: it fails for `NUL`, files and pipes.
- Optionally also require stdout to be a console.
- Add a test that monkeypatches the console probe.

## Cleanup

The echo manifest was reverted (`git checkout`). The throwaway folder `D:\Development\lfmap-eb4`, created for this smoke, was moved to the Recycle Bin.
