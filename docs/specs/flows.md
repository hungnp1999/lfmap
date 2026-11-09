# Module Spec: LFMAP Flows (in-house, on jobs + EventBus)

- Package: `lfmap-core` (flat modules next to `jobs.py` and `events*.py`)
- Roadmap: Phase 2 item "LFMAP Flows"; research plan RT-04 (this spec) and RT-09 (first working flow) in [`docs/research/2026-10-23-commercial-replacements.md`](../research/2026-10-23-commercial-replacements.md)
- Decisions: ADR-021 (build in-house, clean room for n8n), ADR-024 (no agent framework; pause = file state + `resume` in a new process; the pause maps to an ADR-018 proposal `flows.resume`, T2), ADR-017/018 (tiers, non-interactive calls go to the approvals queue), ADR-006 as amended (no background service in Phase 2)
- Folding jobs into flows (architecture review C3/K1, issue #190, ADR-018 note 2026-11-08): section 13 of this spec. **Status: proposed, code waits for the owner to read section 13.**
- Handoff and task list: [`docs/handoff/2026-11-06-lfmap-flows.md`](../handoff/2026-11-06-lfmap-flows.md)

## 1. Purpose

Chain plugin operations into a declared flow that starts on its own (schedule or event), runs unattended up to a tier ceiling, and stops at a durable approval step that a person approves later in a new process. This is the backbone of the Phase 2 exit flow (email with attachment → convert → ingest → summarise → wait for approval).

Non-goals for this handoff: loops, parallel branches, sub-flows, expressions beyond the reference grammar below, a file-watch trigger (needs a daemon), a UI, the Agent Router (AI steps call a plugin operation like any other step), flows across machines.

Sources: behaviour only. Node-RED (Apache-2.0) and Activepieces (MIT, community edition) may be read for ideas; n8n (Sustainable Use License) documentation only, never its code (ADR-021 (2)). No code is copied; `docs/PROVENANCE.md` gets an "in-house" row.

## 2. Modules

| Module | Content | Task |
| --- | --- | --- |
| `flows_refs.py` | `find_refs`, `resolve(value, scope)`: the `${...}` grammar of section 4, pure functions | TC-F1 (qwen) or FL-1 |
| `flows.py` | `Flow`, `Step`, `Trigger`, `FlowsFile` (pydantic, `extra="forbid"`), `flows_path()`, `load_flows()`, `check_flow(registry, flow)` | FL-1 |
| `flows_run.py` | `FlowRun` state, `start(...)`, `resume(...)`, the step loop, the approval pause (cap 230 lines, section 9) | FL-2 |
| `cli.py` | `lfmap flows list|check|start|status|runs`; `approvals approve` resumes a paused run | FL-2 |
| `flows_triggers.py`, `events_adapter.py` / `jobs.py` | event trigger subscription; schedule trigger through `jobs register` | FL-3 |
| `jobs_flow.py` (new, section 13) | `job_to_flow(job)`, `load_all_flows()`: translates `jobs.toml` entries into one-step flows | #190 |

Standard library and pydantic only. No new dependency.

## 3. File format (`flows.toml`, next to `jobs.toml` in the user config folder)

```toml
[[flows]]
id = "convert-inbox"            # same pattern as job ids
max_tier = 1                    # 0 or 1, default 0; the ceiling for unattended steps
enabled = true

[flows.trigger]                 # exactly one of: manual, schedule, event
event = "markitdown.classify.completed"  # a topic pattern (topics.py grammar)
# schedule = { daily = "06:30" } # the jobs Schedule model, unchanged
# manual = true

[[flows.steps]]
id = "export"
call = "markitdown.export"      # <plugin>.<operation>, must exist in the registry (local_write: T1)
input = { path = "${trigger.payload.output.path}", output_dir = 'D:\Exports' }

[[flows.steps]]
id = "index"
call = "knowledge.reindex"
when = "${steps.export.output.succeeded}"   # run only when the value is present and truthy

[[flows.steps]]
id = "review"
approve = "Check the converted file before it is shared"   # a pause step: no call
```

Rules checked by `check_flow` (and by `lfmap flows check`, which exits 1 on any finding):

- Step ids unique, `[a-z][a-z0-9-]*`; at most 20 steps; a step has either `call` or `approve`, never both.
- `call` names a registered plugin and a declared operation; a literal `input` (no reference) passes the operation's input model; inputs with references are checked again at run time after resolving.
- A reference may only name the trigger or an **earlier** step; unknown roots fail.
- `max_tier` above 1 is refused: T2/T3 steps always need a person (ADR-017).
- An event trigger may not match `flows.>` (no flow starts another flow in this handoff) nor any `.requested` topic.

## 4. References (`flows_refs.py`)

- Grammar: `${root.key.key...}` where root is `trigger` or `steps.<id>`; keys are `[A-Za-z_][A-Za-z0-9_]*` or a list index `[0-9]+`. Nothing else: no operators, no function calls, no nesting.
- A string that is exactly one reference becomes the referenced value with its JSON type; a reference inside a longer string is inserted with `str()` and only allowed for `str`, `int`, `float`, `bool`.
- A missing key resolves to `None` for `when`; in `input` it raises `ToolError("invalid_input")` naming the step and the reference.
- Resolving is a pure function over plain JSON data; it never reads files, environment variables or the clock.
- Truthy for `when`: not `None`, not `False`, not `0`, not `""`, not an empty list or dict.

## 5. Running (`flows_run.py`)

- `start(registry, flow_id, trigger_payload, *, run_id=None)` creates a run; `run_id` from an event is `"ev-" + event.id + "-" + flow id` (one run per flow per event) so a redelivered event does not start a second run (at-least-once bus, handler idempotent).
- State: one JSON file per run, `app_dir()/flows/runs/<run_id>.json`, written with temp file + `os.replace` after every step. Fields: flow id, flow file SHA-256, status (`running`, `awaiting_approval`, `completed`, `failed`, `rejected`, `expired`), trigger payload, per-step status and output, `approval_id`, times.
- Step outputs are stored as `model_dump(mode="json")` (prefer operations that write files and return paths, such as `markitdown.export`, over ones that return document text, such as `markitdown.convert`); each stored output at most 64 KiB (`events_payload.MAX_PAYLOAD_BYTES`), else the step fails with `output_too_large`. Outputs carry references (paths, ids), not document text.
- Each `call` step runs through `run_operation(entry, op, input, channel="flow", approver=JobApprover(...))` with the flow's `max_tier`. Channel `flow` is a new value that `decide` treats like `job`.
- When a step needs more than `max_tier`, or is an `approve` step, the run pauses: status `awaiting_approval`, one ADR-018 proposal with `job = "flows"`, `plugin = "flows"`, `operation = "resume"`, `tier = "T2"`, `input = {"run_id": ..., "step": ..., "call": ..., "resolved_input": ...}`. The process may exit.
- `lfmap approvals approve <id>` (interactive terminal only, as today) on a `flows.resume` proposal resumes the run in that process: the paused step runs under `ApprovedGate` up to the tier the person saw (an `approve` step just passes), then the loop continues; a later step above the ceiling pauses again with a new proposal. `reject` sets the run `rejected`; an expired proposal sets it `expired` at the next `approvals pending` sweep.
- Resume refuses a run whose flow file SHA-256 changed since the run started (`invalid_input`, "flow changed; start a new run").
- A failing step (`ToolError`) sets the run `failed`, keeps earlier outputs, and stops. No automatic retry in the flow; the bus already retries event delivery.
- After `completed`, `failed`, `rejected` or `expired`, core publishes `flows.run.<status>` with `{run_id, flow}` (only into a bus that already exists: a run never creates `events.db`; a publish error never changes the run), so later flows or the Tauri console can react.

## 6. Triggers

- `manual`: only `lfmap flows start <id> [--input-json FILE]`.
- `schedule`: `lfmap jobs register` also registers each enabled scheduled flow as task `\LFMAP\flow-<id>` running `lfmap flows start <id>` through `scripts/Invoke-LfmapJob.ps1` (same runtime root, logs and exit codes as jobs). No new scheduler.
- `event`: one durable subscription `flows` on the bus with the union of the enabled flows' patterns (a bus subscription has one pattern, so the union is the narrowest single pattern that covers them, such as `markitdown.*.completed`, and the handler checks each flow's own pattern); its handler starts the matching flows (one run per flow per event). Only flows that pass `check_flow` are subscribed; an unusable `flows.toml` leaves the subscription as it is. Runs only when a process drains (`lfmap events run`, end of `jobs run`), as for every handler.

## 7. CLI

| Command | Does | Interactive only |
| --- | --- | --- |
| `lfmap flows list [--json]` | flows, trigger, enabled, last run status | no |
| `lfmap flows check [--json]` | section 3 checks for every flow, exit 1 on findings | no |
| `lfmap flows start <id> [--input-json FILE]` | starts a run and prints its status | no (steps keep the flow's ceiling) |
| `lfmap flows status <run_id> [--json]` | one run, step by step | no |
| `lfmap flows runs [--flow ID] [--limit N]` | recent runs | no |

No MCP or REST form in this handoff. Approval stays in `lfmap approvals approve|reject` (ADR-018).

## 8. Permissions, data and security

- A flow is configuration the user wrote; it can only call operations the registry has, through the normal gates. It never widens a grant, never raises a tier ceiling above 1, and never pre-approves.
- Every caller-supplied path inside a resolved input still reaches the plugin, which checks it with `PermissionManager.require_*` as today; Flows does no file-system access on input paths.
- Proposals shown at approval contain the resolved input, escaped with `approvals.visible` (no hidden control characters).
- Run files hold references only; `lfmap flows runs` never prints step outputs unless `--json` is given for one run.

## 9. Size limit (ADR-024 (2))

`flows_run.py` is measured like the spike's S1: the whole file, imports and models included, with `spikes/2a1-framework/common/metrics.folder_lines` rules.

- Owner decision 2026-11-06 (PR #174, option a'): the 150-line mark of ADR-024 (2) was reached (FL-2: 223 lines against 135 for the spike's `plain`). The excess is LFMAP-specific logic that ADR-024 (3) and the security rules require (`flows.resume` proposal mapping, `check_resume`, flow file hash, output limit, crash to failed run). The framework rule of the spike (score at least 1.5 higher **and** at least 30 % fewer lines or a capability `plain` needed more than 150 lines for) is not met: a framework would replace at most the run-state storage (estimated 40-50 lines, under 30 %) and add dependencies. The framework choice stays closed.
- Hard cap: **230 lines** for `flows_run.py`. FL-3 puts the event and schedule triggers in a separate module (`flows_triggers.py`) and must not grow `flows_run.py`; above the cap, stop and report.
- The next re-opening is triggered by a named capability (parallel branches, loops, execution across machines), not by a line count.

## 10. Test list (written first by each task, in `packages/lfmap-core/tests/`)

- FL-1: format and every rule of section 3; reference grammar and section 4 cases (exact reference keeps type, embedded reference, missing key in `when` vs `input`, list index, refusal of anything outside the grammar).
- FL-2: a three-step flow runs to `completed` on the echo plugin; step above ceiling pauses with one `flows.resume` proposal; process restart then approve finishes the run; reject; expiry; changed flow file refused on resume; `output_too_large`; failing step; idempotent `run_id` per event; channel `flow` audit lines.
- FL-3: event subscription starts each matching flow once even when the event is delivered twice; scheduled flow registers the right task command (no real Task Scheduler); `flows.>` and `.requested` triggers refused.
- No test touches the real `LOCALAPPDATA`, Task Scheduler or network.

## 11. Sample flows (RT-04 completion: three flows can be written in this format)

1. **Exit flow (Phase 2):** trigger `event = "email.message.received"` (plugin `email`, not built yet) → `markitdown.export` on `${trigger.payload.attachment_path}` → `knowledge.reindex` → `<summary step>.summarise` (Agent Router, 2a.2) → `approve` "Send the summary".
2. **Convert inbox:** `schedule = { daily = "06:30" }` → `markitdown.export` of an inbox folder (`recursive = true`, existing files skipped) → `knowledge.reindex`.
3. **Approved script:** `manual = true` → `powershell.run` (an allow-listed T2 script, so it pauses for approval before running) → `echo` step recording the result.

Flow 1 needs two plugins that do not exist yet (`email`, and an AI step after the Agent Router); it is the target, not part of this handoff's smoke test. The smoke test (FL-4) runs a flow made only of existing plugins (`echo`, `markitdown`, `knowledge`).

## 12. Definition of Done

- Sections 3–7 implemented with the section 10 tests green on Linux and Windows CI.
- Section 9 size limit met (number in the FL-2 PR).
- `ARCHITECTURE.md` gains the "Flow" main flow and the `flow` channel invariant; `docs/PROVENANCE.md` row; `CHANGELOG.md`.
- FL-4 smoke on DIEP-ANH: event-triggered flow pauses, the process exits, `approvals approve` in a new terminal completes it.

## 13. Jobs read as one-step flows (proposed, issue #190)

Goal: one runner and one proposal kind. A job in `jobs.toml` is translated on load into a flow; `jobs.toml` stays valid and is not rewritten. Task Scheduler, `scripts/Invoke-LfmapJob.ps1`, the approvals queue, the tier table of `docs/jobs.md` and `max_tier` semantics do not change.

### 13.1 Translation (`jobs_flow.py`, outside `flows_run.py`)

| `jobs.toml` | One-step flow |
| --- | --- |
| `id` | flow id (same value, so task `\LFMAP\<id>` and log lines keep their names); flagged `origin = "job"` in memory only |
| `schedule` | `trigger.schedule` (same `Schedule` model) |
| `plugin`, `operation`, `input` | one step `id = "run"`, `call = "<plugin>.<operation>"`, `input` as written (literal; no references) |
| `max_tier` | flow `max_tier` |
| `enabled` | `enabled` |
| `via = "call"` | step runs as today (`run_operation`) |
| `via = "event"` | step gets `via = "event"` (new optional `Step` field, default `"call"`): core publishes `<plugin>.<operation>.requested`, drains and returns the answer through the event adapter, as `jobs run` does now |

- `load_all_flows()` returns declared flows plus translated jobs. A job id equal to a flow id, or to `flow-<id>` of another flow, is a load error naming both (today's `flow-<id>` rule of `docs/jobs.md` stays).
- `check_flow` applies to translated jobs, so `jobs doctor` and `flows check` report the same findings. The rule "a step has `call` or `approve`" is met; the 20-step and reference rules are trivially met.
- **Ceilings.** The effective ceiling of a `via = "event"` step is the lower of the flow's `max_tier` and `[events] max_tier`, unchanged: the flow gate checks the first, the event adapter the second. The request still carries the flow id (`job` field of the event body) so a call stopped by either ceiling is queued under that name.

### 13.2 Runner and CLI

- `lfmap jobs run <id>` becomes a thin alias of `lfmap flows start <id>` for a translated job, followed by the event drain it does today (`--max-events`). Exit codes stay: 0 ok, 1 `ToolError`, 2 other. A run that pauses prints the same `Error [permission_denied]: Queued for approval` and exits 1, so `Invoke-LfmapJob.ps1` logs and any script reading them see no change.
- `lfmap jobs list|register|doctor` read `load_all_flows()`. `register` creates the scheduled task of a translated job under its old name (`\LFMAP\<id>`, command `jobs run <id>`), and of a real flow as `\LFMAP\flow-<id>` (section 6). No task is renamed, so a machine that registered jobs before this change needs no re-register.
- `lfmap flows list` shows translated jobs with origin `job`. `flows start <id>` works on them too.

### 13.3 Proposals and audit

- A translated job that needs more than its ceiling pauses like any flow: one `flows.resume` proposal (T2 as section 5; the tier shown to the person is still the call's own tier). `approvals pending` shows the job id in the `job` column as today.
- Run state: a translated job writes a run file **only when it pauses** (needed for resume); a run that completes or fails writes none, as jobs never had run files, so an hourly job does not create 24 files a day. Its result is the `jobs-YYYY-MM-DD.jsonl` line and `audit.jsonl`. (Open question 1.)
- Audit channel: runs of translated jobs use channel `flow`. The channel `job` stays valid in `audit.jsonl` and in `approvals` for old lines and old proposals (section 13.4).
- A `via = "event"` translated job still writes two audit lines for one T1 run (flow gate and event adapter), as `docs/jobs.md` explains.

### 13.4 Transition release

- Proposals already in `approvals/pending` written by old jobs (no `flows.resume`, a plain call) stay approvable: the legacy reader in `approvals.py` and `cli.py approvals approve` remains for **one transition release** after #190 merges, runs them once with the recorded tier as today, and audits them on channel `job`. New proposals use only the `flows.resume` kind.
- After that release the legacy path is deleted in a follow-up issue (created by the #190 PR); proposals expire after 7 days (`approval_ttl_days` up to 30), so one release is enough unless the TTL is raised.
- Rollback: the change is internal. Reverting the PR restores the old runner; run files of paused translated jobs would then be orphaned (`flows.resume` is still understood by the flows runner, so they can still be approved).

### 13.5 Size and layout

`flows_run.py` stays under the 230-line cap of section 9: translation, loading and the `jobs run` alias live in `jobs_flow.py` and `jobs.py`; the only change in `flows_run.py` is the "write state only when pausing" switch for translated jobs and routing `via = "event"` steps, and if that does not fit, stop and report (as section 9 says). `jobs.py` shrinks: `run_job` becomes a call into the flow runner; `JobApprover` use moves to the flow gate.

### 13.6 Tests (written first)

- Translation table: every field of 13.1, `via = "event"` including the lower-ceiling case, id collisions.
- A translated job: T0 runs; T1 runs at `max_tier = 1` and queues at 0; T2/T3 always queue; `[approval]` deny/ask tighten (same cases as the current `jobs` tests, now through the flow runner).
- Pause writes a `flows.resume` proposal named by the job id; approve in a new process completes it; completed run leaves no run file.
- A legacy pending proposal fixture (old format) is still listed, approved once, audited on channel `job`.
- `jobs register --dry-run` output is identical before and after for the same `jobs.toml` (golden test).
- `jobs run` exit codes and the printed `Queued for approval` line unchanged.

### 13.7 Open questions for the owner

1. No run file for completed translated jobs (13.3) is proposed. The alternative is a run file per execution (visible in `flows runs`, but needs pruning). Recommendation: no file.
2. Audit channel for translated jobs: `flow` (recommended, one meaning per channel) or keep `job` (log queries unchanged).
3. One transition release for the legacy reader (13.4) is proposed; say if you want it removed in the same PR instead (only safe if `approvals/pending` is empty on every machine).

DIEP-ANH smoke after the code PR: `jobs register --dry-run` unchanged, `jobs run echo-hello` exit 0, one T1 job at `max_tier = 0` queues, `approvals approve` in a new terminal finishes it, a pre-change pending proposal still approves.
