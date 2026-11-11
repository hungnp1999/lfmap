"""Flow triggers (docs/specs/flows.md section 6) and the `flows.run.<status>` events (section 5).

- Event: one durable subscription `flows-<id>` per enabled event flow on the user's bus, with the flow's own
  pattern; its handler starts that flow once per event (`run_id = "ev-" + event.id + "-" + flow id`, so a
  redelivery finds its run).
  Handlers run only while a process drains the bus (`lfmap events run`, the end of `lfmap jobs run`).
- Schedule: `lfmap jobs register` creates task `\\LFMAP\\flow-<id>` for each enabled scheduled flow; it runs
  `lfmap flows start <id>` through `scripts/Invoke-LfmapJob.ps1`, like a job.
- Events: core publishes `flows.run.<status>` when a run ends, only into a bus that already exists.
"""

import logging
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from lfmap_core import flows, jobs
from lfmap_core.errors import ToolError
from lfmap_core.events import Event, EventBus, topic_matches
from lfmap_core.events_adapter import bus_path, open_bus
from lfmap_core.registry import Registry

if TYPE_CHECKING:
    from lfmap_core.flows_run import FlowRun

PREFIX = "flows-"
LEGACY = "flows"  # the single FL-3 subscription, removed once by `attach`
ENDED = ("completed", "failed", "rejected", "expired")
log = logging.getLogger(__name__)


def subscription_name(flow_id: str) -> str:
    return PREFIX + flow_id


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


def attach(registry: Registry, bus: EventBus) -> dict[str, str]:
    """Give every enabled event flow its own durable subscription `flows-<id>`; return flow id -> pattern.

    An unusable flows.toml leaves every subscription (and its queued events) alone. A flow whose pattern changed
    is unsubscribed and subscribed again, which drops only its own queued deliveries. Subscriptions of flows that
    are gone, disabled, no longer sound or not event flows, and the legacy `flows` one, are removed.
    """
    declared = _declared()
    if declared is None:
        return _attached(bus)
    wanted = {f.id: str(f.trigger.event) for f in _sound(registry, declared)}
    current = bus.subscriptions()
    if LEGACY in current:
        log.warning("Removed the legacy `%s` flow subscription; its queued deliveries are dropped", LEGACY)
        bus.unsubscribe(LEGACY)
    for name in current:
        if name.startswith(PREFIX) and name[len(PREFIX) :] not in wanted:
            bus.unsubscribe(name)
    for flow_id, pattern in wanted.items():
        name = subscription_name(flow_id)
        if name in current and current[name] != pattern:
            log.warning("Flow %s changed its event pattern; its queued deliveries are dropped", flow_id)
            bus.unsubscribe(name)
        try:
            bus.subscribe(name, pattern, _handler(registry, flow_id))
        except ToolError as error:
            if error.code != "invalid_input":
                raise
            log.warning("Flow %s is not triggered by events: %s", flow_id, error.message)
    return _attached(bus)


def _attached(bus: EventBus) -> dict[str, str]:
    return {n[len(PREFIX) :]: p for n, p in bus.subscriptions().items() if n.startswith(PREFIX)}


def _handler(registry: Registry, flow_id: str) -> Callable[[Event], None]:
    return lambda event: handle(registry, flow_id, event)


def handle(registry: Registry, flow_id: str, event: Event) -> None:
    """Start flow `flow_id` with the event payload as trigger payload (`run_id = ev-<event id>-<flow id>`, so a
    redelivery finds its run). The subscription already matched the topic; flows.* and *.requested are ignored."""
    from lfmap_core import flows_run  # flows_run imports this module

    if event.topic.startswith("flows.") or event.topic.endswith(".requested"):
        return
    flows_run.start(registry, flow_id, event.payload, run_id=f"ev-{event.id}-{flow_id}")


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
