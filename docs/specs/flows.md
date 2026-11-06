# Module Spec: LFMAP Flows (in-house, on jobs + EventBus)

- Package: `lfmap-core` (flat modules next to `jobs.py` and `events*.py`)
- Roadmap: Phase 2 item "LFMAP Flows"; research plan RT-04 (this spec) and RT-09 (first working flow) in [`docs/research/2026-10-23-commercial-replacements.md`](../research/2026-10-23-commercial-replacements.md)
- Decisions: ADR-021 (build in-house, clean room for n8n), ADR-024 (no agent framework; pause = file state + `resume` in a new process; the pause maps to an ADR-018 proposal `flows.resume`, T2), ADR-017/018 (tiers, non-interactive calls go to the approvals queue), ADR-006 as amended (no background service in Phase 2)
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

- `start(registry, flow_id, trigger_payload, *, run_id=None)` creates a run; `run_id` from an event is `"ev-" + event.id` so a redelivered event does not start a second run (at-least-once bus, handler idempotent).
- State: one JSON file per run, `app_dir()/flows/runs/<run_id>.json`, written with temp file + `os.replace` after every step. Fields: flow id, flow file SHA-256, status (`running`, `awaiting_approval`, `completed`, `failed`, `rejected`, `expired`), trigger payload, per-step status and output, `approval_id`, times.
- Step outputs are stored as `model_dump(mode="json")` (prefer operations that write files and return paths, such as `markitdown.export`, over ones that return document text, such as `markitdown.convert`); each stored output at most 64 KiB (`events_payload.MAX_PAYLOAD_BYTES`), else the step fails with `output_too_large`. Outputs carry references (paths, ids), not document text.
- Each `call` step runs through `run_operation(entry, op, input, channel="flow", approver=JobApprover(...))` with the flow's `max_tier`. Channel `flow` is a new value that `decide` treats like `job`.
- When a step needs more than `max_tier`, or is an `approve` step, the run pauses: status `awaiting_approval`, one ADR-018 proposal with `job = "flows"`, `plugin = "flows"`, `operation = "resume"`, `tier = "T2"`, `input = {"run_id": ..., "step": ..., "call": ..., "resolved_input": ...}`. The process may exit.
- `lfmap approvals approve <id>` (interactive terminal only, as today) on a `flows.resume` proposal resumes the run in that process: the paused step runs under `ApprovedGate` up to the tier the person saw (an `approve` step just passes), then the loop continues; a later step above the ceiling pauses again with a new proposal. `reject` sets the run `rejected`; an expired proposal sets it `expired` at the next `approvals pending` sweep.
- Resume refuses a run whose flow file SHA-256 changed since the run started (`invalid_input`, "flow changed; start a new run").
- A failing step (`ToolError`) sets the run `failed`, keeps earlier outputs, and stops. No automatic retry in the flow; the bus already retries event delivery.
- After `completed`, `failed`, `rejected` or `expired`, core publishes `flows.run.<status>` with `{run_id, flow}` (only when the bus is open), so later flows or the Tauri console can react.

## 6. Triggers

- `manual`: only `lfmap flows start <id> [--input-json FILE]`.
- `schedule`: `lfmap jobs register` also registers each enabled scheduled flow as task `\LFMAP\flow-<id>` running `lfmap flows start <id>` through `scripts/Invoke-LfmapJob.ps1` (same runtime root, logs and exit codes as jobs). No new scheduler.
- `event`: one durable subscription `flows` on the bus with the union of the enabled flows' patterns; its handler starts the matching flows (one run per flow per event). Runs only when a process drains (`lfmap events run`, end of `jobs run`), as for every handler.

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
