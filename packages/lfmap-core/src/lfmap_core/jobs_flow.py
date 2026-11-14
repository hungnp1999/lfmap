"""Jobs read as one-step flows (docs/specs/flows.md section 13, issue #190).

`jobs.toml` is not rewritten: each job is translated on load into a flow with a `schedule` trigger and one step
`run`, and `run_job` runs it through the Flows runner. A translated job writes a run file only while it waits
for approval, and its audit channel is `flow`.
"""

import hashlib
from contextvars import ContextVar
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from lfmap_core import approvals, flows
from lfmap_core.errors import ToolError
from lfmap_core.jobs import Job, load_jobs
from lfmap_core.registry import PluginEntry, Registry
from lfmap_core.runtime import run_operation

EVENT_DRAIN: ContextVar[int] = ContextVar("event_drain", default=1000)


class JobOutput(BaseModel):
    """The output of a job's step, whatever fields the operation returns."""

    model_config = ConfigDict(extra="allow")


def job_to_flow(job: Job) -> flows.Flow:
    step = flows.Step(id="run", call=f"{job.plugin}.{job.operation}", input=job.input, via=job.via)
    trigger = flows.Trigger(schedule=job.schedule)
    return flows.Flow(id=job.id, trigger=trigger, steps=[step], max_tier=job.max_tier, enabled=job.enabled)


def translated(path: Path | None = None) -> list[flows.Flow]:
    return [job_to_flow(job) for job in load_jobs(path)]


def is_job(flow_id: str) -> bool:
    return any(flow.id == flow_id for flow in translated())


def extend(declared: list[flows.Flow], digest: str) -> tuple[list[flows.Flow], dict[str, str]]:
    """The declared flows plus the translated jobs, and the hash a run binds to for each: `digest` of
    `flows.toml` for a declared flow, the hash of the translation for a job. A shared id is an error."""
    extra = translated()
    clash = sorted({f.id for f in declared} & {f.id for f in extra})
    if clash:
        raise ToolError("invalid_input", f"Job and flow share the id {', '.join(clash)}", {"ids": clash})
    shas = {f.id: digest for f in declared}
    shas |= {f.id: hashlib.sha256(f.model_dump_json().encode("utf-8")).hexdigest() for f in extra}
    return declared + extra, shas


def load_all() -> list[flows.Flow]:
    """Declared flows and translated jobs, for `flows list` and `flows check`."""
    declared = flows.load_flows()
    return extend(declared, "")[0]


def call(
    registry: Registry, entry: PluginEntry, flow_id: str, step: flows.Step, resolved: dict, gate, approved
) -> BaseModel:
    """Run a step's operation. A `via = "event"` step publishes `<plugin>.<operation>.requested` and drains the
    bus (the event adapter applies `[events] max_tier` on top of the flow's), unless a person approved it already."""
    plugin, _, operation = (step.call or "").partition(".")
    if step.via == "event" and approved is None:
        from lfmap_core.events_adapter import request_operation  # events_adapter imports jobs

        return request_operation(registry, entry, operation, resolved, max_events=EVENT_DRAIN.get(), job_id=flow_id)
    return run_operation(entry, operation, resolved, channel="flow" if approved is None else "cli", approver=gate)


def expire(approval_id: str | None) -> None:
    """Move a waiting job run's proposal to `expired` and close its run, as `approvals.sweep` does at its end of life.
    A proposal that is already gone (approved, rejected or swept meanwhile) leaves nothing to do."""
    from lfmap_core import flows_run  # flows_run imports this module

    try:
        proposal = approvals.load(approval_id or "")
        approvals.move(proposal.id, "expired")
    except ToolError as error:
        if error.code != "not_found":
            raise
        return
    flows_run.close(proposal, "expired")


def run_job(registry: Registry, job_id: str, path: Path | None = None, *, max_events: int = 1000) -> BaseModel:
    """Run one job through the Flows runner. A run that waits for approval raises `permission_denied`
    ("Queued for approval"), a failed run raises its error, so exit codes and messages are those of `jobs run`."""
    from lfmap_core import flows_run  # flows_run imports this module

    job = next((j for j in load_jobs(path) if j.id == job_id), None)
    if job is None:
        raise ToolError("not_found", f"Unknown job {job_id!r}", {"job": job_id})
    if registry.get(job.plugin).manifest.operation(job.operation) is None:
        raise ToolError("not_found", f"Unknown operation {job.plugin}.{job.operation}", {"job": job_id})
    approvals.sweep()
    [last] = flows_run.list_runs(job_id, 1) or [None]
    if last is not None and last.status == "awaiting_approval":
        if last.flow_sha256 == flows_run._flows_file()[1].get(job_id):  # the same call keeps its pending proposal
            raise ToolError(
                "permission_denied", "Queued for approval", {"approval_id": last.approval_id, "job": job_id}
            )
        expire(
            last.approval_id
        )  # the job was edited: the old proposal can no longer be approved, so a new run replaces it
    token = EVENT_DRAIN.set(max_events)
    try:
        run = flows_run.start(registry, job_id, {})
    except ToolError as error:
        if error.code == "invalid_input" and "findings" in error.details:
            raise ToolError(error.code, "; ".join(error.details["findings"]), error.details) from error
        raise
    finally:
        EVENT_DRAIN.reset(token)
    if run.status == "awaiting_approval":
        raise ToolError("permission_denied", "Queued for approval", {"approval_id": run.approval_id, "job": job_id})
    if run.status != "completed":
        error = run.error or {}
        raise ToolError(error.get("code", "internal"), error.get("message", "Job failed"), error.get("details", {}))
    return JobOutput(**(run.steps[0].output or {}))
