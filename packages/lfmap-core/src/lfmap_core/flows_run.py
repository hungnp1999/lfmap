"""Flow runs (docs/specs/flows.md section 5): one JSON file per run in `app_dir()/flows/runs/`, saved after every step.

A call step above the flow's `max_tier`, or an `approve` step, pauses the run behind one `flows.resume` proposal
(T2, ADR-018, ADR-024); `lfmap approvals approve` resumes it in a new process. Run files hold references, not text.
`_save` also announces a run that ended as `flows.run.<status>` (`flows_triggers.announce`).
"""

import hashlib
import json
import os
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError

from lfmap_core import approvals, flows_triggers, jobs_flow
from lfmap_core.approval import Asker, Gate, Policy, Tier
from lfmap_core.config import app_dir, load_config
from lfmap_core.errors import ToolError
from lfmap_core.events import MAX_PAYLOAD_BYTES, encode_payload
from lfmap_core.flows import Flow, Step, check_flow, flows_path, parse_flows
from lfmap_core.flows_refs import resolve, truthy
from lfmap_core.registry import Registry
from lfmap_core.runtime import call_tier

Status = Literal["running", "awaiting_approval", "completed", "failed", "rejected", "expired"]
StepStatus = Literal["pending", "awaiting_approval", "completed", "skipped", "failed"]
_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", re.ASCII)
MAX_ERROR_BYTES = 4096
RESUME = "flows.resume"


class StepRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    status: StepStatus = "pending"
    output: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


class FlowRun(BaseModel):
    """`flow_sha256` is the hash of the whole `flows.toml` the run started with; `payload` is the trigger payload."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    flow: str
    flow_sha256: str
    status: Status = "running"
    payload: dict[str, Any]
    steps: list[StepRun]
    approval_id: str | None = None
    error: dict[str, Any] | None = None
    created: AwareDatetime
    updated: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))


def runs_dir() -> Path:
    return app_dir() / "flows" / "runs"


def _path(run_id: str) -> Path:
    if not _RUN_ID.fullmatch(run_id):
        raise ToolError("invalid_input", "Not a run id", {"run_id": run_id})
    base = os.path.realpath(runs_dir())
    candidate = os.path.realpath(os.path.join(base, run_id + ".json"))
    if not candidate.startswith(base + os.sep):
        raise ToolError("permission_denied", "Run path leaves the runs folder", {"run_id": run_id})
    return Path(candidate)


def _parse(text: str, name: str) -> FlowRun:
    try:
        run = FlowRun.model_validate_json(text)
    except ValidationError as error:
        raise ToolError("invalid_input", f"{name} is not a valid flow run", {"error": str(error)}) from error
    if run.run_id != name:
        raise ToolError("invalid_input", f"{name} holds another run id", {"run_id": run.run_id})
    return run


def load_run(run_id: str) -> FlowRun:
    try:
        text = _path(run_id).read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise ToolError("not_found", f"No flow run {run_id!r}", {"run_id": run_id}) from error
    return _parse(text, run_id)


def list_runs(flow: str | None = None, limit: int = 20) -> list[FlowRun]:
    """Newest first. Unreadable or invalid run files are skipped."""
    found = []
    for path in runs_dir().glob("*.json"):
        try:
            run = _parse(path.read_text(encoding="utf-8"), path.stem)
        except (OSError, ToolError):  # noqa: S112 - an unreadable run file is skipped
            continue
        if flow in (None, run.flow):
            found.append(run)
    return sorted(found, key=lambda r: (r.created, r.run_id), reverse=True)[:limit]


def _save(run: FlowRun) -> None:
    run.updated = datetime.now(UTC)
    path = _path(run.run_id)
    if run.status != "awaiting_approval" and not path.exists() and jobs_flow.is_job(run.flow):
        return flows_triggers.announce(run)  # a job run leaves a file only while it waits for approval
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(run.model_dump_json(indent=2), encoding="utf-8")
    os.replace(tmp, path)
    flows_triggers.announce(run)


def _flows_file() -> tuple[list[Flow], dict[str, str]]:
    """The flows (declared and translated jobs) and, per flow id, the hash a run binds to: the SHA-256 of the
    exact `flows.toml` bytes for a declared flow."""
    path = flows_path()
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        raw = b""
    try:
        return jobs_flow.extend(parse_flows(raw.decode("utf-8"), path).flows, hashlib.sha256(raw).hexdigest())
    except UnicodeDecodeError as error:
        raise ToolError("invalid_input", f"{path} is not UTF-8 text") from error


def _error(error: ToolError) -> dict[str, Any]:
    details = json.dumps(error.details, default=str)
    return {
        "code": error.code,
        "message": error.message,
        "details": json.loads(details) if len(details) <= MAX_ERROR_BYTES else {"truncated": True},
    }


def _scope(run: FlowRun) -> dict[str, Any]:
    done = {s.id: {"output": s.output} for s in run.steps if s.status == "completed"}
    return {"trigger": {"payload": run.payload}, "steps": done}


def _call(step: Step) -> tuple[str, str]:
    plugin, _, operation = (step.call or RESUME).partition(".")
    return plugin, operation


def start(registry: Registry, flow_id: str, trigger_payload: dict[str, Any], *, run_id: str | None = None) -> FlowRun:
    """Start a run and carry it on until it ends or pauses; a `run_id` that already has a run returns that run."""
    encode_payload(trigger_payload)
    now = datetime.now(UTC)
    run_id = f"{now:%Y%m%dT%H%M%SZ}-{flow_id[:40]}-{uuid.uuid4().hex[:8]}" if run_id is None else run_id
    if _path(run_id).exists():
        return load_run(run_id)
    flows, shas = _flows_file()
    flow = next((f for f in flows if f.id == flow_id), None)
    if flow is None:
        raise ToolError("not_found", f"Unknown flow {flow_id!r}", {"flow": flow_id})
    if not flow.enabled:
        raise ToolError("invalid_input", f"Flow {flow_id!r} is disabled", {"flow": flow_id})
    if findings := check_flow(registry, flow):
        raise ToolError("invalid_input", f"Flow {flow_id!r} did not pass its checks", {"findings": findings})
    steps = [StepRun(id=s.id) for s in flow.steps]
    run = FlowRun(
        run_id=run_id, flow=flow.id, flow_sha256=shas[flow.id], payload=trigger_payload, steps=steps, created=now
    )
    return advance(registry, flow, run)


def advance(registry: Registry, flow: Flow, run: FlowRun, approved: approvals.ApprovedGate | None = None) -> FlowRun:
    """The step loop: run the steps not done yet, saving after each; stop at the first failure or pause.

    `approved` covers the step that is waiting (a person approved its `flows.resume` proposal).
    """
    config = load_config()
    policy, lifetime = Policy.from_config(config), approvals.ttl(config)
    run.status, run.approval_id = "running", None
    _save(run)
    for step, state in zip(flow.steps, run.steps, strict=True):
        if state.status in ("completed", "skipped"):
            continue
        gate = approved if state.status == "awaiting_approval" else None
        try:
            scope = _scope(run)
            if step.when is not None and not truthy(resolve(step.when, scope, step=step.id)):
                state.status = "skipped"
            else:
                resolved = resolve(step.input, scope, step=step.id, strict=True)
                state.output = _execute(registry, flow, run, step, resolved, (config, policy, lifetime), gate)
                state.status = "completed"
        except Exception as error:  # noqa: BLE001 - recorded on the run: a bug must not leave it "running"
            failure = error if isinstance(error, ToolError) else ToolError("internal", f"Step {step.id!r} crashed")
            if failure.code == "permission_denied" and "approval_id" in failure.details:
                state.status = run.status = "awaiting_approval"
                run.approval_id = failure.details["approval_id"]
            else:
                state.status, run.status = "failed", "failed"
                state.error = run.error = _error(failure)
            _save(run)
            return run
        _save(run)
    run.status = "completed"
    _save(run)
    return run


def _execute(
    registry: Registry,
    flow: Flow,
    run: FlowRun,
    step: Step,
    resolved: dict[str, Any],
    settings: tuple[dict[str, Any], Policy, Any],
    approved: approvals.ApprovedGate | None,
) -> dict[str, Any] | None:
    """One step: an `approve` step asks for T2, a call runs through `run_operation` on channel `flow`."""
    config, policy, lifetime = settings
    plugin, operation = _call(step)

    def propose(tier: Tier, reason: str, detail: str) -> str:
        what = f"{step.call} needs {tier} ({reason}), flow ceiling T{flow.max_tier}" if step.call else reason
        asked = {"run_id": run.run_id, "step": step.id, "call": step.call, "resolved_input": resolved}
        call = approvals.EventCall("flows", "resume", asked, id=flow.id if jobs_flow.is_job(flow.id) else "flows")
        return approvals.queue(call, "T2", f"{run.flow}/{step.id}: {what}", detail, lifetime)

    job = approvals.EventCall(plugin, operation, resolved, flow.max_tier)
    gate = approved or approvals.JobApprover(job, policy, lifetime, "flow", proposer=propose)
    if step.approve is not None:
        gate("T2", step.approve)
        return None
    entry = registry.get(plugin)
    gate(call_tier(entry, operation, resolved, config), "side_effects")
    output = jobs_flow.call(registry, entry, flow.id, step, resolved, gate, approved).model_dump(mode="json")
    size = len(json.dumps(output, ensure_ascii=False).encode("utf-8"))
    if size > MAX_PAYLOAD_BYTES:
        raise ToolError(
            "internal",
            f"Output of step {step.id!r} is too large",
            {"reason": "output_too_large", "bytes": size, "limit": MAX_PAYLOAD_BYTES},
        )
    return output


def check_resume(proposal: approvals.Proposal) -> tuple[Flow, FlowRun, int]:
    """Refuse unless `proposal` is the one its run waits for, the flow file is the one the run started with, and
    the proposal still says exactly what the step will do. Returns the flow, the run and the waiting step's index."""
    if not approvals.is_flow_resume(proposal):
        raise ToolError("invalid_input", "Not a flows.resume proposal", {"id": proposal.id})
    run = load_run(str(proposal.input.get("run_id")))
    if run.status != "awaiting_approval" or run.approval_id != proposal.id:
        raise ToolError("invalid_input", f"Run {run.run_id} is not waiting for this proposal", {"id": proposal.id})
    flows, shas = _flows_file()
    if shas.get(run.flow) != run.flow_sha256:
        raise ToolError("invalid_input", "flow changed; start a new run", {"run_id": run.run_id})
    flow = next((f for f in flows if f.id == run.flow), None)
    index = next((i for i, s in enumerate(run.steps) if s.status == "awaiting_approval"), None)
    if flow is None or index is None or len(flow.steps) != len(run.steps):
        raise ToolError("invalid_input", f"Run {run.run_id} does not match its flow", {"run_id": run.run_id})
    step = flow.steps[index]
    resolved = resolve(step.input, _scope(run), step=step.id, strict=True)
    if proposal.input != {"run_id": run.run_id, "step": step.id, "call": step.call, "resolved_input": resolved}:
        raise ToolError("invalid_input", "The proposal does not match the waiting step", {"id": proposal.id})
    return flow, run, index


def resume(registry: Registry, proposal: approvals.Proposal, ask: Asker) -> FlowRun:
    """Run the approved step under `ApprovedGate` (up to the proposal's tier; `ask` is the fallback gate's prompt),
    then carry on with the rest of the flow, which may pause again with a new proposal."""
    flow, run, index = check_resume(proposal)
    approvals.move(proposal.id, "done")
    plugin, operation = _call(flow.steps[index])
    covered = proposal.model_copy(update={"plugin": plugin, "operation": operation})
    gate = approvals.ApprovedGate(covered, Gate(plugin, operation, "cli", Policy.from_config(load_config()), ask=ask))
    return advance(registry, flow, run, gate)


def close(proposal: approvals.Proposal, status: Literal["rejected", "expired"]) -> None:
    """Mark the run waiting for `proposal` rejected or expired; any other proposal is ignored."""
    try:
        run = load_run(str(proposal.input.get("run_id")))
    except ToolError:
        return
    if run.status != "awaiting_approval" or run.approval_id != proposal.id:
        return
    run.status = status
    for step in run.steps:
        if step.status == "awaiting_approval":
            step.status, step.error = "failed", {"code": "permission_denied", "message": f"Approval {status}"}
    _save(run)
