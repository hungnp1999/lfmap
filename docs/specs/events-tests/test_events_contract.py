"""Contract every EventBus implementation passes (docs/specs/events.md section 4)."""

import json
import re
import time
from datetime import UTC, datetime

import pytest

from lfmap_core import ToolError
from lfmap_core.events import Event, EventBus, InProcessBus
from lfmap_core.events_payload import MAX_PAYLOAD_BYTES
from lfmap_core.events_sqlite import SqliteBus


class Clock:
    def __init__(self) -> None:
        self.now = time.time()

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture(params=["memory", "sqlite"])
def make_bus(request, tmp_path):
    buses = []

    def make(clock=None, max_attempts=5):
        clock = clock or Clock()
        if request.param == "memory":
            bus = InProcessBus(clock=clock, max_attempts=max_attempts)
        else:
            bus = SqliteBus(tmp_path / "events.db", clock=clock, max_attempts=max_attempts)
        buses.append(bus)
        return bus

    yield make
    for bus in buses:
        bus.close()


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def bus(make_bus, clock):
    return make_bus(clock)


def record(into):
    return into.append


def test_implements_protocol(bus):
    assert isinstance(bus, EventBus)


def test_publish_returns_event(bus):
    event = bus.publish("jobs.done", {"job": "nightly"}, source="core")
    assert isinstance(event, Event)
    assert re.fullmatch(r"[0-9a-f]{32}", event.id)
    assert event.topic == "jobs.done"
    assert event.source == "core"
    assert event.payload == {"job": "nightly"}
    assert event.created_at.tzinfo is not None
    assert event.created_at.utcoffset().total_seconds() == 0
    assert abs((datetime.now(UTC) - event.created_at).total_seconds()) < 60
    assert event.correlation_id == event.id
    assert event.causation_id is None
    assert event.attempt == 1


def test_payload_defaults_to_empty(bus):
    assert bus.publish("jobs.done", source="core").payload == {}


def test_ids_are_unique(bus):
    ids = {bus.publish("jobs.done", source="core").id for _ in range(50)}
    assert len(ids) == 50


@pytest.mark.parametrize("topic", ["", "Jobs.done", "jobs..done", "jobs.*", "jobs.>", "jobs.done\n", None])
def test_publish_rejects_bad_topic(bus, topic):
    with pytest.raises(ToolError) as caught:
        bus.publish(topic, {}, source="core")
    assert caught.value.code == "invalid_input"


@pytest.mark.parametrize("source", ["", "Core", "my plugin", "1abc", None])
def test_publish_rejects_bad_source(bus, source):
    with pytest.raises(ToolError) as caught:
        bus.publish("jobs.done", {}, source=source)
    assert caught.value.code == "invalid_input"


@pytest.mark.parametrize("payload", [[1], {"a": float("nan")}, {"k": "x" * MAX_PAYLOAD_BYTES}])
def test_publish_rejects_bad_payload_and_delivers_nothing(bus, payload):
    got = []
    bus.subscribe("watch", ">", record(got))
    with pytest.raises(ToolError) as caught:
        bus.publish("jobs.done", payload, source="core")
    assert caught.value.code == "invalid_input"
    assert bus.drain() == 0
    assert got == []


@pytest.mark.parametrize("name", ["", "Watch", "a.b", "a b", "-a", "a" * 65, None])
def test_subscribe_rejects_bad_name(bus, name):
    with pytest.raises(ToolError) as caught:
        bus.subscribe(name, "jobs.>", lambda event: None)
    assert caught.value.code == "invalid_input"


@pytest.mark.parametrize("pattern", ["", "jobs.", "jobs.>.x", "jobs.x*", "JOBS.*"])
def test_subscribe_rejects_bad_pattern(bus, pattern):
    with pytest.raises(ToolError) as caught:
        bus.subscribe("watch", pattern, lambda event: None)
    assert caught.value.code == "invalid_input"


def test_publish_does_not_call_handlers(bus):
    got = []
    bus.subscribe("watch", "jobs.>", record(got))
    bus.publish("jobs.done", {}, source="core")
    assert got == []
    assert bus.drain() == 1
    assert [event.topic for event in got] == ["jobs.done"]


def test_drain_with_nothing_to_do(bus):
    assert bus.drain() == 0


def test_patterns(bus):
    star, tail, exact = [], [], []
    bus.subscribe("star", "jobs.*", record(star))
    bus.subscribe("tail", "jobs.>", record(tail))
    bus.subscribe("exact", "jobs.done", record(exact))
    for topic in ["jobs", "jobs.done", "jobs.done.late", "job.done", "jobsx.done"]:
        bus.publish(topic, {}, source="core")
    bus.drain()
    assert [event.topic for event in star] == ["jobs.done"]
    assert [event.topic for event in tail] == ["jobs.done", "jobs.done.late"]
    assert [event.topic for event in exact] == ["jobs.done"]


def test_fan_out_one_delivery_per_subscription(bus):
    first, second = [], []
    bus.subscribe("first", "jobs.>", record(first))
    bus.subscribe("second", "*.done", record(second))
    event = bus.publish("jobs.done", {"n": 1}, source="core")
    assert bus.drain() == 2
    assert [e.id for e in first] == [event.id]
    assert [e.id for e in second] == [event.id]


def test_fifo_per_subscription(bus):
    got = []
    bus.subscribe("watch", "jobs.>", record(got))
    for number in range(20):
        bus.publish("jobs.done", {"n": number}, source="core")
    assert bus.drain() == 20
    assert [event.payload["n"] for event in got] == list(range(20))


def test_no_delivery_of_events_older_than_the_subscription(bus):
    bus.publish("jobs.done", {"n": 1}, source="core")
    got = []
    bus.subscribe("watch", "jobs.>", record(got))
    bus.publish("jobs.done", {"n": 2}, source="core")
    bus.drain()
    assert [event.payload["n"] for event in got] == [2]


def test_delivered_payload_is_a_json_copy(bus):
    got = []
    bus.subscribe("watch", "jobs.>", record(got))
    payload = {"items": (1, 2), "nested": {"a": 1}}
    event = bus.publish("jobs.done", payload, source="knowledge")
    payload["nested"]["a"] = 99
    bus.drain()
    assert event.payload == {"items": [1, 2], "nested": {"a": 1}}
    assert got[0].payload == {"items": [1, 2], "nested": {"a": 1}}
    assert got[0].source == "knowledge"
    assert got[0].created_at == event.created_at


def test_event_round_trips_through_json(bus):
    event = bus.publish("jobs.done", {"a": [1, "x"]}, source="core")
    assert Event.model_validate(json.loads(event.model_dump_json())) == event


def test_events_published_by_a_handler_run_in_the_same_drain(bus):
    seen = []

    def relay(event):
        seen.append(event)
        if event.topic == "flows.step.one":
            bus.publish("flows.step.two", {"from": event.id}, source="core", causation=event)

    bus.subscribe("relay", "flows.>", relay)
    first = bus.publish("flows.step.one", {}, source="core")
    assert bus.drain() == 2
    second = seen[1]
    assert second.topic == "flows.step.two"
    assert second.causation_id == first.id
    assert second.correlation_id == first.correlation_id == first.id


def test_correlation_is_kept_along_a_chain(bus):
    first = bus.publish("flows.a", {}, source="core")
    second = bus.publish("flows.b", {}, source="core", causation=first)
    third = bus.publish("flows.c", {}, source="core", causation=second)
    assert third.correlation_id == first.id
    assert third.causation_id == second.id


def test_failure_is_retried_after_backoff(bus, clock):
    calls = []

    def flaky(event):
        calls.append(event.attempt)
        if len(calls) == 1:
            raise ValueError("first time fails")

    bus.subscribe("flaky", "jobs.>", flaky)
    bus.publish("jobs.done", {}, source="core")
    assert bus.drain() == 1
    assert calls == [1]
    clock.advance(1.9)
    assert bus.drain() == 0
    clock.advance(0.2)
    assert bus.drain() == 1
    assert calls == [1, 2]
    assert bus.dead_letters() == []


def test_backoff_doubles(bus, clock):
    calls = []

    def failing(event):
        calls.append(clock())
        raise RuntimeError("down")

    bus.subscribe("failing", "jobs.>", failing)
    bus.publish("jobs.done", {}, source="core")
    for _ in range(20):
        bus.drain()
        clock.advance(1.0)
    start = calls[0]
    assert [round(at - start) for at in calls] == [0, 2, 6, 14]


def test_dead_letter_after_max_attempts(make_bus, clock):
    bus = make_bus(clock, max_attempts=3)
    calls = []

    def failing(event):
        calls.append(event.attempt)
        raise RuntimeError("still down\nsecond line")

    bus.subscribe("failing", "jobs.>", failing)
    event = bus.publish("jobs.done", {"n": 1}, source="core")
    for _ in range(10):
        bus.drain()
        clock.advance(600)
    assert calls == [1, 2, 3]
    [dead] = bus.dead_letters()
    assert dead.event.id == event.id
    assert dead.event.payload == {"n": 1}
    assert dead.subscription == "failing"
    assert dead.attempts == 3
    assert dead.error == "RuntimeError: still down second line"


def test_permanent_error_goes_dead_at_once(bus):
    calls = []

    def refuse(event):
        calls.append(event.attempt)
        raise ToolError("invalid_input", "bad request")

    bus.subscribe("refuse", "jobs.>", refuse)
    bus.publish("jobs.done", {}, source="core")
    bus.drain()
    [dead] = bus.dead_letters()
    assert calls == [1]
    assert dead.attempts == 1
    assert dead.error == "invalid_input: bad request"


def test_failure_does_not_block_other_subscriptions(bus):
    good = []

    def bad(event):
        raise RuntimeError("no")

    bus.subscribe("bad", "jobs.>", bad)
    bus.subscribe("good", "jobs.>", record(good))
    bus.publish("jobs.done", {}, source="core")
    assert bus.drain() == 2
    assert len(good) == 1


def test_retrying_delivery_does_not_block_later_events(bus):
    got = []

    def picky(event):
        if event.payload["n"] == 0:
            raise RuntimeError("not yet")
        got.append(event.payload["n"])

    bus.subscribe("picky", "jobs.>", picky)
    for number in range(3):
        bus.publish("jobs.done", {"n": number}, source="core")
    assert bus.drain() == 3
    assert got == [1, 2]


def test_dead_letters_filter_by_subscription(bus):
    def bad(event):
        raise ToolError("not_found", "gone")

    bus.subscribe("one", "jobs.>", bad)
    bus.subscribe("two", "jobs.>", bad)
    bus.publish("jobs.done", {}, source="core")
    bus.drain()
    assert {dead.subscription for dead in bus.dead_letters()} == {"one", "two"}
    assert [dead.subscription for dead in bus.dead_letters("one")] == ["one"]


def test_retry_dead_letter(bus):
    state = {"fail": True}
    got = []

    def handler(event):
        if state["fail"]:
            raise ToolError("permission_denied", "not allowed yet")
        got.append(event.attempt)

    bus.subscribe("handler", "jobs.>", handler)
    event = bus.publish("jobs.done", {}, source="core")
    bus.drain()
    assert len(bus.dead_letters()) == 1
    state["fail"] = False
    bus.retry(event.id, "handler")
    assert bus.dead_letters() == []
    assert bus.drain() == 1
    assert got == [1]


def test_retry_unknown_dead_letter(bus):
    bus.subscribe("handler", "jobs.>", lambda event: None)
    event = bus.publish("jobs.done", {}, source="core")
    with pytest.raises(ToolError) as caught:
        bus.retry(event.id, "handler")
    assert caught.value.code == "not_found"
    with pytest.raises(ToolError) as caught:
        bus.retry("0" * 32, "handler")
    assert caught.value.code == "not_found"


def test_unsubscribe_drops_pending_deliveries(bus):
    got = []
    bus.subscribe("watch", "jobs.>", record(got))
    bus.publish("jobs.done", {}, source="core")
    bus.unsubscribe("watch")
    assert bus.drain() == 0
    bus.publish("jobs.done", {}, source="core")
    assert bus.drain() == 0
    assert got == []


def test_unsubscribe_unknown(bus):
    with pytest.raises(ToolError) as caught:
        bus.unsubscribe("nobody")
    assert caught.value.code == "not_found"


def test_subscribe_again_with_same_pattern_replaces_handler(bus):
    old, new = [], []
    bus.subscribe("watch", "jobs.>", record(old))
    bus.subscribe("watch", "jobs.>", record(new))
    bus.publish("jobs.done", {}, source="core")
    assert bus.drain() == 1
    assert old == []
    assert len(new) == 1


def test_subscribe_again_with_other_pattern_is_refused(bus):
    bus.subscribe("watch", "jobs.>", lambda event: None)
    with pytest.raises(ToolError) as caught:
        bus.subscribe("watch", "flows.>", lambda event: None)
    assert caught.value.code == "invalid_input"


def test_drain_max_events(bus):
    got = []
    bus.subscribe("watch", "jobs.>", record(got))
    for number in range(5):
        bus.publish("jobs.done", {"n": number}, source="core")
    assert bus.drain(max_events=2) == 2
    assert bus.drain(max_events=10) == 3
    assert [event.payload["n"] for event in got] == [0, 1, 2, 3, 4]


def test_drain_rejects_bad_max_events(bus):
    with pytest.raises(ToolError) as caught:
        bus.drain(max_events=0)
    assert caught.value.code == "invalid_input"


def test_handler_errors_never_escape_drain(bus):
    def broken(event):
        raise KeyError("missing")

    bus.subscribe("broken", "jobs.>", broken)
    bus.publish("jobs.done", {}, source="core")
    assert bus.drain() == 1


def test_closed_bus_refuses_work(make_bus):
    bus = make_bus()
    bus.close()
    with pytest.raises(ToolError) as caught:
        bus.publish("jobs.done", {}, source="core")
    assert caught.value.code == "backend_unavailable"
    with pytest.raises(ToolError) as caught:
        bus.drain()
    assert caught.value.code == "backend_unavailable"
    bus.close()
