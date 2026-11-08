You are a careful Python 3.12 developer. Write ONE new module in the `lfmap` monorepo: `packages/lfmap-core/src/lfmap_core/flows_run.py` (task FL-2 of `docs/handoff/2026-11-06-lfmap-flows.md`, spec `docs/specs/flows.md` section 5). Code, comments and docstrings in English. Standard library and pydantic only. Small functions, type hints everywhere.

RULES
- Do NOT edit the tests; the frozen tests are `packages/lfmap-core/tests/test_flows_run.py` and `test_flows_run_cli.py`.
- The whole file (imports and models included) is at most 230 lines by `spikes/2a1-framework/common/metrics.folder_lines` (ADR-024 note, spec section 9).
- Caller-supplied paths (the run id) go through a `realpath` + inline `startswith` guard before any file-system call.

SPEC (section 5, shortened)
- `start(registry, flow_id, trigger_payload, *, run_id=None)` creates a run; a `run_id` that already has a run returns it (at-least-once bus).
- One JSON file per run, `app_dir()/flows/runs/<run_id>.json`, temp file + `os.replace` after every step. Fields: flow id, flow file SHA-256, status (`running`, `awaiting_approval`, `completed`, `failed`, `rejected`, `expired`), trigger payload, per-step status and output, `approval_id`, times.
- Step outputs stored as `model_dump(mode="json")`, at most `MAX_PAYLOAD_BYTES`, else the step fails with `output_too_large`.
- Each `call` step runs through `run_operation(..., channel="flow", approver=JobApprover(...))` with the flow's `max_tier`.
- A step above `max_tier`, or an `approve` step, pauses the run: status `awaiting_approval`, one ADR-018 proposal `flows.resume` (T2) with `{run_id, step, call, resolved_input}`.
- `resume` (after `lfmap approvals approve`) runs the paused step under `ApprovedGate`, then continues; refuses when the flow file hash changed (`flow changed; start a new run`). `reject` sets `rejected`, an expired proposal `expired`.
- A failing step (`ToolError`) sets the run `failed`, keeps earlier outputs, stops. No retry.

This case reviews a copy of the real module as merged in PR #174 (written by a Sonnet Working session, not by qwen); there is no Plan run.
This copy carries one seeded bug.
