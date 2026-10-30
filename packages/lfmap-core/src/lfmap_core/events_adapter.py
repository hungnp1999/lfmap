"""Events for plugins (docs/specs/events.md section 6): `ctx.events`, the user's bus and the event adapter.

A plugin publishes only its own topics. Only core publishes `<plugin>.<operation>.requested`; the adapter
runs that operation like a scheduled job (channel "event", never asks anyone, capped at `[events] max_tier`)
and answers with `.completed` or `.failed`. No plugin-specific code lives here.
"""

import contextlib
import logging
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any, get_args

from pydantic import BaseModel

from lfmap_core.approval import Policy
from lfmap_core.approvals import EventCall, JobApprover, ttl
from lfmap_core.config import app_dir, load_config
from lfmap_core.errors import ErrorCode, ToolError
from lfmap_core.events import Event, EventBus, Handler
from lfmap_core.events_names import operation_topic, parse_operation_topic, plugin_may_publish
from lfmap_core.events_payload import encode_payload
from lfmap_core.events_sqlite import SqliteBus
from lfmap_core.jobs import check_input
from lfmap_core.registry import PluginEntry, Registry
from lfmap_core.runtime import call_tier, run_operation

MAX_ERROR_MESSAGE = 500
RUN_BATCH = 100
IDLE_SLEEP_SECONDS = 1.0
log = logging.getLogger(__name__)


def bus_path() -> Path:
    return app_dir() / "events.db"


def open_bus() -> SqliteBus:
    """The user's durable bus. Its path is fixed; no caller-supplied path reaches it."""
    return SqliteBus(bus_path())


class PluginEvents:
    """What a plugin sees as `ctx.events`: it publishes its own topics, with `source` set to its id.

    Without a bus, each publish opens the user's bus and closes it again. During an event call the adapter
    passes its bus and the request, so events the plugin publishes continue that chain.
    """

    def __init__(self, plugin_id: str, bus: EventBus | None = None, *, causation: Event | None = None) -> None:
        self.plugin_id = plugin_id
        self._bus = bus
        self._causation = causation

    def publish(self, topic: str, payload: dict[str, Any] | None = None) -> Event:
        if not plugin_may_publish(self.plugin_id, topic):
            details = {"plugin": self.plugin_id, "topic": topic if isinstance(topic, str) else repr(topic)}
            message = "A plugin publishes only its own topics, never <plugin>.<operation>.requested|completed|failed"
            raise ToolError("permission_denied", message, details)
        if self._bus is not None:
            return self._bus.publish(topic, payload, source=self.plugin_id, causation=self._causation)
        bus = open_bus()
        try:
            return bus.publish(topic, payload, source=self.plugin_id, causation=self._causation)
        finally:
            bus.close()


def events_max_tier(config: dict[str, Any]) -> int:
    """`[events] max_tier` in config.toml: the highest tier an event call runs without a person (default 0)."""
    section = config.get("events", {})
    value = section.get("max_tier", 0) if isinstance(section, dict) else None
    if type(value) is not int or value not in (0, 1):
        raise ToolError("invalid_input", "[events] max_tier must be 0 or 1", {"value": repr(value)})
    return value


def subscription_name(plugin_id: str) -> str:
    return f"adapter-{plugin_id}"


def _completed(request_id: str, output: BaseModel) -> dict[str, Any]:
    payload = {"request_id": request_id, "output": output.model_dump(mode="json")}
    try:
        encode_payload(payload)
    except ToolError as error:
        if error.details.get("reason") != "too_large":
            raise ToolError(
                "internal", "Operation output is not JSON", {"reason": error.details.get("reason")}
            ) from error
        return {"request_id": request_id, "output": None, "output_too_large": True}
    return payload


def _failed(request_id: str, error: ToolError) -> dict[str, Any]:
    payload = {"request_id": request_id, "error": error.to_dict()}
    try:
        encode_payload(payload)
    except ToolError:
        short = {"code": error.code, "message": error.message[:MAX_ERROR_MESSAGE], "details": {}}
        return {"request_id": request_id, "error": short}
    return payload


class EventAdapter:
    """Subscribes `adapter-<plugin-id>` to `<plugin-id>.*.requested` for every plugin with
    `[adapters] events = true` and runs each request like a scheduled job."""

    def __init__(self, registry: Registry, bus: EventBus) -> None:
        self._registry = registry
        self._bus = bus

    def attach(self) -> list[str]:
        """Subscribe every events-enabled plugin; return the subscription names."""
        names = []
        for entry in self._registry.all():
            if not entry.manifest.adapters.events:
                continue
            name = subscription_name(entry.id)
            try:
                self._bus.subscribe(name, f"{entry.id}.*.requested", self._handler(entry))
            except ToolError as error:
                log.warning("Skipping events for plugin %s: %s", entry.id, error)
                continue
            names.append(name)
        return names

    def _handler(self, entry: PluginEntry) -> Handler:
        def handle(event: Event) -> None:
            self.handle(entry, event)

        return handle

    def handle(self, entry: PluginEntry, request: Event) -> None:
        """Run one request. A ToolError from the call is published as `.failed` and the delivery is done;
        a request that is not a core request for this plugin raises and becomes a dead letter."""
        parsed = parse_operation_topic(request.topic)
        if parsed is None or parsed[0] != entry.id or parsed[2] != "requested":
            raise ToolError("invalid_input", "Not a request for this plugin", {"topic": request.topic})
        if request.source != "core":
            details = {"topic": request.topic, "source": request.source}
            raise ToolError("permission_denied", "Only core requests an operation", details)
        operation = parsed[1]
        try:
            payload = _completed(request.id, self._run(entry, operation, request))
            phase = "completed"
        except ToolError as error:
            payload, phase = _failed(request.id, error), "failed"
        topic = operation_topic(entry.id, operation, phase)
        self._bus.publish(topic, payload, source="core", causation=request)

    def _run(self, entry: PluginEntry, operation: str, request: Event) -> BaseModel:
        inp = request.payload.get("input", {})
        if set(request.payload) - {"input"} or not isinstance(inp, dict):
            raise ToolError("invalid_input", 'A request payload is {"input": {...}}', {"keys": sorted(request.payload)})
        if entry.manifest.operation(operation) is None:
            raise ToolError("not_found", f"Unknown operation {entry.id}.{operation}", {"operation": operation})
        check_input(entry, operation, inp)
        config = load_config()
        call = EventCall(entry.id, operation, inp, events_max_tier(config))
        gate = JobApprover(call, Policy.from_config(config), ttl(config), channel="event")
        gate(call_tier(entry, operation, inp, config), "side_effects")
        publisher = PluginEvents(entry.id, self._bus, causation=request)
        return run_operation(entry, operation, inp, channel="event", approver=gate, events=publisher)


def run_adapter(
    registry: Registry,
    bus: EventBus,
    *,
    max_seconds: float,
    until_idle: bool = False,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """`lfmap events run`: attach the adapter and drain in batches until `max_seconds` have passed, or until
    nothing is ready with `until_idle`. Returns the number of handler calls."""
    EventAdapter(registry, bus).attach()
    deadline = clock() + max_seconds
    total = 0
    while True:
        count = bus.drain(max_events=RUN_BATCH)
        total += count
        left = deadline - clock()
        if left <= 0 or (count == 0 and until_idle):
            return total
        if count == 0:
            sleep(min(IDLE_SLEEP_SECONDS, left))


def drain_after_job(registry: Registry, max_events: int) -> int:
    """The bounded drain at the end of `lfmap jobs run`; nothing to do without an events-enabled plugin."""
    if not any(entry.manifest.adapters.events for entry in registry.all()):
        return 0
    bus = open_bus()
    try:
        EventAdapter(registry, bus).attach()
        return bus.drain(max_events=max_events)
    finally:
        bus.close()


class RequestResult(BaseModel):
    """What `request_operation` returns when the output did not fit in the `.completed` event."""

    request_id: str
    output_too_large: bool = True


def _answer(events: list[Event], request_id: str) -> Event | None:
    """The core answer caused by this request; anything else on the watched topics is ignored."""
    phases = (".completed", ".failed")
    return next(
        (
            e
            for e in events
            if e.topic.endswith(phases)
            and e.source == "core"
            and e.causation_id == request_id
            and e.payload.get("request_id") == request_id
        ),
        None,
    )


def request_operation(
    registry: Registry, entry: PluginEntry, operation: str, inp: dict[str, Any], *, max_events: int
) -> BaseModel:
    """Publish `<plugin>.<operation>.requested` as core, drain at most `max_events` handler calls and return
    the output from `.completed`. `.failed` raises its ToolError; no answer within the drain raises `timeout`
    and the request stays queued for the next drain."""
    bus = open_bus()
    watcher = f"request-{uuid.uuid4().hex[:16]}"
    seen: list[Event] = []
    try:
        EventAdapter(registry, bus).attach()
        bus.subscribe(watcher, f"{entry.id}.{operation}.*", seen.append)
        request = bus.publish(operation_topic(entry.id, operation, "requested"), {"input": inp}, source="core")
        bus.drain(max_events=max_events)
    finally:
        with contextlib.suppress(ToolError):  # the watcher may not exist if subscribing failed
            bus.unsubscribe(watcher)
        bus.close()
    answer = _answer(seen, request.id)
    if answer is None:
        message = "The request was not handled within --max-events; it stays queued for the next drain"
        raise ToolError("timeout", message, {"request_id": request.id})
    if answer.topic.endswith(".failed"):
        error = answer.payload.get("error") or {}
        code = error.get("code") if error.get("code") in get_args(ErrorCode) else "internal"
        details = error.get("details") if isinstance(error.get("details"), dict) else {}
        raise ToolError(code, str(error.get("message", "The operation failed")), {**details, "request_id": request.id})
    if answer.payload.get("output_too_large"):
        return RequestResult(request_id=request.id)
    return entry.tool_class.operations()[operation].output_model.model_validate(answer.payload["output"])
