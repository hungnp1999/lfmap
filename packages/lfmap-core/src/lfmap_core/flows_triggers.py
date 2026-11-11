"""Flow triggers (docs/specs/flows.md section 6) and the `flows.run.<status>` events (section 5).

- Event: one durable subscription `flows` on the user's bus; its handler starts every enabled flow whose pattern
  matches, once per flow per event (`run_id = "ev-" + event.id + "-" + flow id`, so a redelivery finds its run).
  Handlers run only while a process drains the bus (`lfmap events run`, the end of `lfmap jobs run`).
- Schedule: `lfmap jobs register` creates task `\\LFMAP\\flow-<id>` for each enabled scheduled flow; it runs
  `lfmap flows start <id>` through `scripts/Invoke-LfmapJob.ps1`, like a job.
- Events: core publishes `flows.run.<status>` when a run ends, only into a bus that already exists.
"""

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from lfmap_core import flows, jobs
from lfmap_core.errors import ToolError
from lfmap_core.events import Event, EventBus, topic_matches
from lfmap_core.events_adapter import bus_path, open_bus
from lfmap_core.registry import Registry

if TYPE_CHECKING:
    from lfmap_core.flows_run import FlowRun

SUBSCRIPTION = "flows"
ENDED = ("completed", "failed", "rejected", "expired")
log = logging.getLogger(__name__)


def covering_pattern(patterns: list[str]) -> str:
    """One subscription pattern that matches everything `patterns` match, as narrow as the topic grammar allows
    (a bus subscription has one pattern). The handler still checks each flow's own pattern."""
    tokens = [p.split(".") for p in patterns]
    if len({len(t) for t in tokens}) == 1 and all(t[-1] != ">" for t in tokens):
        return ".".join(col[0] if len(set(col)) == 1 else "*" for col in zip(*tokens, strict=True))
    head = min(len(t) for t in tokens) - 1  # the tokens every pattern fixes before it needs a ">"
    merged = [col[0] if len(set(col)) == 1 else "*" for col in zip(*(t[:head] for t in tokens), strict=True)]
    return ".".join([*merged, ">"])


def _declared() -> list[flows.Flow] | None:
    """The flows in flows.toml, or None (and a log line) when the file cannot be read."""
    try:
        return flows.load_flows()
    except ToolError as error:
        log.warning("Flow triggers skipped, flows.toml is unusable: %s", error.message)
        return None


def _sound(registry: Registry, declared: list[flows.Flow]) -> list[flows.Flow]:
    """Enabled event flows that pass `check_flow`; this also keeps out any trigger that could match `flows.*`."""
    found = []
    for flow in declared:
        if not flow.enabled or flow.trigger.event is None:
            continue
        if findings := flows.check_flow(registry, flow):
            log.warning("Flow %s is not triggered by events: %s", flow.id, findings[0])
            continue
        found.append(flow)
    return found


def event_flows(registry: Registry) -> list[flows.Flow]:
    return _sound(registry, _declared() or [])


def attach(registry: Registry, bus: EventBus) -> str | None:
    """Subscribe `flows` with the union of the patterns of the enabled event flows; return that pattern.

    No event flow removes the subscription. An unusable flows.toml leaves it alone, so queued events wait.
    A changed union replaces the subscription; deliveries still queued for the old one are dropped.
    """
    declared = _declared()
    if declared is None:
        return None
    found = _sound(registry, declared)
    if not found:
        try:
            bus.unsubscribe(SUBSCRIPTION)
        except ToolError:  # noqa: S110 - there was no subscription
            pass
        return None
    pattern = covering_pattern([str(f.trigger.event) for f in found])

    def handler(event: Event) -> None:
        handle(registry, event)

    try:
        bus.subscribe(SUBSCRIPTION, pattern, handler)
    except ToolError as error:
        if error.code != "invalid_input":
            raise
        log.warning("Flow trigger pattern changed to %s; queued deliveries of the old one are dropped", pattern)
        bus.unsubscribe(SUBSCRIPTION)
        bus.subscribe(SUBSCRIPTION, pattern, handler)
    return pattern


def handle(registry: Registry, event: Event) -> None:
    """Start each matching flow with the event payload as trigger payload; a flow that cannot start does not
    stop the others, and the first such error is raised at the end so the bus retries (then dead-letters)."""
    from lfmap_core import flows_run  # flows_run imports this module

    if event.topic.startswith("flows.") or event.topic.endswith(".requested"):
        return
    failure: ToolError | None = None
    for flow in event_flows(registry):
        if not topic_matches(str(flow.trigger.event), event.topic):
            continue
        try:
            flows_run.start(registry, flow.id, event.payload, run_id=f"ev-{event.id}-{flow.id}")
        except ToolError as error:
            failure = failure or error
    if failure is not None:
        raise failure


def task_commands(
    declared: list[flows.Flow], repo: Path, uv: Path, script: Path, pwsh: Path | None = None
) -> dict[str, list[str]]:
    """`schtasks /Create` for each enabled scheduled flow, by task name (`flow-<id>`, in `\\LFMAP\\`)."""
    return {
        f"flow-{flow.id}": jobs.schedule_command(
            f"flow-{flow.id}", f"-FlowId {flow.id}", flow.trigger.schedule, repo, uv, script, pwsh
        )
        for flow in declared
        if flow.enabled and flow.trigger.schedule is not None
    }


def announce(run: "FlowRun") -> None:
    """Publish `flows.run.<status>` for a run that ended. Never raises: the run file is already saved, and there
    is no bus to open when the user has no events.db (a flow run does not create one)."""
    if run.status not in ENDED or not bus_path().exists():
        return
    try:
        bus = open_bus()
        try:
            bus.publish(f"flows.run.{run.status}", {"run_id": run.run_id, "flow": run.flow}, source="core")
        finally:
            bus.close()
    except Exception as error:  # noqa: BLE001 - a bus problem must not change the outcome of a run
        log.warning("flows.run.%s was not published: %s", run.status, error)
