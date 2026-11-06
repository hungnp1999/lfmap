# Architecture

A short map of LFMAP for contributors and Claude sessions. The full Phase 1 architecture document (Vietnamese) is `docs/phase1/01_Architecture.md`; decisions live in the ADRs outside the repository. Update this file in the same PR when the module map, a main flow or an invariant changes.

## Shape

One Python workspace (`uv`), Windows-first, no background service. Business logic lives in a plugin's `Tool` class; `lfmap-core` generates the adapters from each plugin's `lfmap.toml` manifest.

```mermaid
flowchart LR
  U[Owner, PowerShell] -->|lfmap ...| CLI
  C[Claude Code / Desktop] -->|MCP stdio| MCP
  TS[Task Scheduler \LFMAP\] -->|Invoke-LfmapJob.ps1| JOB
  subgraph core [lfmap-core]
    CLI[CLI adapter] --> RT[runtime + approval Gate T0-T3]
    MCP[MCP adapter] --> RT
    JOB[lfmap jobs run] --> RT
  end
  RT --> MD[markitdown]
  RT --> KN[knowledge]
  RT --> PS[powershell]
  RT --> EC[echo]
  KN -->|SDK, context_for| MD
  KN -->|loopback HTTP| OL[Ollama bge-m3]
  KN --> DB[(catalog.db, LanceDB, Markdown cache)]
  RT --> AUD[(audit.jsonl, grants.json, approvals)]
  MD --> FS[(user folders in declared roots)]
```

## Module map

| Path | Role |
| --- | --- |
| `packages/lfmap-core` | `Tool`, `@operation`, `ToolContext`, `ToolError` (`tool.py`, `errors.py`); manifest schema (`manifest.py`); plugin discovery via the `lfmap.plugins` entry point (`registry.py`); building tools and contexts (`runtime.py`); user config `%LOCALAPPDATA%\lfmap\config.toml` (`config.py`); Permission Manager (`permissions.py`); risk tiers, policy and audit log (`approval.py`), time-limited grants (`grants.py`), job approval queue (`approvals.py`); scheduled jobs and doctor (`jobs.py`, `jobs_doctor.py`); declared flows: `flows.toml` model and static checks (`flows.py`), the `${...}` reference grammar (`flows_refs.py`), the flow runner with its durable pause and `flows.resume` approvals (`flows_run.py`, at most 230 code lines, spec section 9); flow triggers (the `flows` bus subscription, scheduled-flow tasks for `jobs register`, `flows.run.<status>` events: `flows_triggers.py`); EventBus: topics and patterns (`topics.py`), `Event` and the `EventBus` Protocol with an in-process bus (`events.py`), durable SQLite bus with leases and dead letters (`events_sqlite.py`), retry, payload and operation-topic helpers (`events_retry.py`, `events_payload.py`, `events_names.py`); `ctx.events`, the user's bus `events.db` and the event adapter (`events_adapter.py`); generated adapters (`cli.py`, `mcp_adapter.py`); telemetry off (`telemetry.py`) |
| `packages/lfmap-knowledge` | Plugin `knowledge`: scan roots (`scanner.py`), extract Markdown through markitdown with a hash cache (`extract.py`), chunk (`chunker.py`), FTS5 with Vietnamese folding (`fts.py`), Ollama embeddings (`embed.py`), LanceDB (`vectors.py`), SQLite catalog and migrations (`store.py`, `catalog.py`), file edges (`edges.py`), hybrid search and `get_context` (`search.py`), reindex and status (`indexer.py`) |
| `plugins/lfmap-markitdown` | Plugin `markitdown`: `classify`, `convert`, `export`, `info`; backends MarkItDown (default), OCR (`[ocr]` extra) and Docling (`[docling]` extra, PDF only, offline models); text-quality checks ported from MarkitdownTool |
| `plugins/lfmap-powershell` | Plugin `powershell`: runs only allow-listed scripts (hash-pinned, typed arguments) without a shell, with timeout and capped output; tier per script (ADR-020, default T3) |
| `plugins/lfmap-echo` | Reference plugin |
| `scripts/` | `check_licenses.py` (CI licence gate), `Invoke-LfmapJob.ps1` (runs one job, JSON log) |
| `docs/` | `specs/`, `handoff/`, `research/`, phase acceptance sets `phase0/`, `phase1/`, provenance |

## Main flows

1. **Operation call.** An adapter resolves the plugin and operation, `runtime.build_tool` creates the `ToolContext` (permissions, `data_dir`, settings, channel, approver), and the approval `Gate` maps `side_effects` to a tier: `none` T0, `local_write` T1, `external` T3. T2/T3 ask a human (CLI TTY prompt, MCP elicitation, `--approve`, grant) according to the channel; every decision above T0 is written to `audit.jsonl`.
2. **Scheduled job.** Task Scheduler runs `Invoke-LfmapJob.ps1` from `[runtime] root` in `jobs.toml` (default: this checkout), which runs `lfmap jobs run` from that same tree and exits. A job never asks: calls above its `max_tier` become proposals in `approvals\pending\`, approved later at a TTY.
3. **Knowledge reindex.** Under a single-writer lock: reconcile files, extract changed ones through markitdown (in-process SDK call with the caller's rights), chunk, index FTS5, embed in batches, write LanceDB, garbage-collect.
4. **Question over MCP.** `knowledge_search` / `knowledge_get_context`: keyword and vector search fused with RRF, weak hits pruned, packed to a token budget with citations. `secret` roots never leave on `mcp`/`rest`; every call that returns content writes `egress_log`.
5. **Event.** No daemon: handlers run only while `lfmap events run` or the end of `lfmap jobs run` drains `%LOCALAPPDATA%\lfmap\events.db` (bounded by `--max-seconds` / `--max-events`). A plugin with `[adapters] events = true` publishes its own topics through `ctx.events`. Core publishes `<plugin>.<operation>.requested` (a job with `via = "event"`, later Flows); the event adapter (`adapter-<plugin-id>`) runs the operation like a job (channel `event`, capped at `[events] max_tier`, otherwise a proposal) and publishes `.completed` or `.failed`. Delivery is at least once, so handlers must be idempotent; failed handlers retry with backoff and end as dead letters (`lfmap events dead`, `retry` at a TTY).
6. **Flow.** `lfmap flows start <id>` creates a run. Three triggers start one: `manual` (that command), `schedule` (`lfmap jobs register` creates task `\LFMAP\flow-<id>`, which runs `Invoke-LfmapJob.ps1 -FlowId <id>`, i.e. this command, from `[runtime] root`) and `event` (the durable bus subscription `flows`, attached by every draining process, starts each matching flow once with `run_id = ev-<event id>-<flow id>`, so a redelivery finds its run; only flows that pass `check_flow` are subscribed, and none can match `flows.*` or `*.requested`). The run: `flows_run.start` checks the flow (`check_flow`), then the step loop resolves each step's `when` and `input` from the trigger payload and earlier outputs, and runs the call through `run_operation` on channel `flow` with a `JobApprover` capped at the flow's `max_tier` (0 or 1). State is one JSON file per run in `%LOCALAPPDATA%\lfmap\flows\runs\`, saved after every step, holding references only. A step above the ceiling, or an `approve` step, pauses the run behind one `flows.resume` proposal (T2) and the process may exit. `lfmap approvals approve <id>` (TTY) calls `check_resume` (the proposal must be the one the run waits for, `flows.toml` must hash as it did at the start, and the resolved input must equal what the proposal shows), runs that step under `ApprovedGate`, then continues; a later step above the ceiling pauses again. `reject` and expiry set the run `rejected` or `expired`; a failing step sets it `failed`, with no retry. When a run ends (`completed`, `failed`, `rejected`, `expired`) core publishes `flows.run.<status>` `{run_id, flow}` into the user's bus if `events.db` exists (never creating it, never failing the run).

## Invariants

- Adapters stay generic: no plugin-specific code in `cli.py` or `mcp_adapter.py`. Plugins call each other through the SDK (`context_for`), never through CLI or MCP.
- Every caller-supplied path goes through `PermissionManager.require_read` / `require_write` before file-system access; the final check is `realpath` plus an inline `startswith` guard. UNC, `\\?\`, `\\.\` and `//` paths are refused before any I/O.
- Folders come only from the user's `config.toml`; no operation writes it. Self-granting commands (`config add-folder`, `approvals grant/revoke/approve/reject`) and the queue-changing `events retry/prune` run only at a TTY and have no MCP form. On Windows a TTY means a console stdin (`GetConsoleMode`) with a visible console window; `grant`, `revoke` and `add-folder` also need a random 6-character code typed back. This gate stops scripts, piped or `NUL` stdin and accidents, not an agent of the same Windows user that drives a real console (issue #108; separate-user ADR pending).
- Code that runs as the owner comes from a reviewed runtime clone that agents cannot write (ADR-023): Task Scheduler jobs and the owner's MCP server start from `[runtime] root` (on pc-01 `D:\lfmap-runtime`, a clone of `main` that an hourly task of the owner fast-forwards), never from a development tree such as `D:\Development\lfmap`. Agents run under their own Windows account; the owner's profile (`%LOCALAPPDATA%\lfmap`, credentials) is outside their reach. `lfmap jobs doctor` warns (`runtime_acl`) when any account other than the owner, SYSTEM or Administrators can write the root.
- T3 is never covered by `--yes`, `--approve` or elicitation.
- No network beyond loopback: markitdown converts opened streams only, the embedder accepts loopback URLs and ignores proxy variables.
- Runtime dependencies must carry a licence in the manifest's `allowed` list (`scripts/check_licenses.py`).
- Writing a plugin's own `data_dir` is not a side effect (ADR-016).
- Events: a plugin publishes only with `[adapters] events = true`, only `<plugin-id>.…` topics (two tokens or more), with `source` set to its id; `<plugin>.<operation>.requested|completed|failed` are published by core only. An event call runs on channel `event`, never asks anyone and is capped at `[events] max_tier` (default 0); above it the call becomes a proposal (`job` = the id the request carries from `lfmap jobs run`, else `"events"`). `events.db` has a fixed path in the app folder.
- Flows: a flow step runs on channel `flow`, which `decide` treats like `job` and `event`: nobody is asked, the flow's `max_tier` (0 or 1, never above) is a ceiling, and anything above it becomes a `flows.resume` proposal (job `flows`, T2) that a person approves at a TTY. A flow never pre-approves, widens a grant or raises its own ceiling; no flow starts another (a trigger cannot match `flows.*`, and the trigger handler ignores those topics); resume refuses when `flows.toml` changed or the proposal no longer matches the waiting step. `--input-json` is read through a `PermissionManager` with no roots, so only a person at a TTY can name a file.

## Review habits

- Redraw the diagram above (or a richer one as an Artifact page) at the end of each Roadmap phase and after a large refactor; note any drift from this file in the PR.
- Run `/security-review` before merging a code PR that touches caller-supplied paths, adapters, network calls, subprocesses or `.claude/`. CodeQL runs on every PR.
