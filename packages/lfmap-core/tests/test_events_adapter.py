import json
import os
from pathlib import Path

import pytest
from pydantic import BaseModel

from lfmap_core import Tool, operation
from lfmap_core.approval import TIERS, Policy, audit_path, decide
from lfmap_core.approvals import approvals_dir
from lfmap_core.errors import ToolError
from lfmap_core.events import Event, InProcessBus
from lfmap_core.events_adapter import (
    EventAdapter,
    PluginEvents,
    bus_path,
    events_max_tier,
    open_bus,
    subscription_name,
)
from lfmap_core.events_payload import MAX_PAYLOAD_BYTES
from lfmap_core.manifest import parse_manifest
from lfmap_core.registry import PluginEntry, Registry
from lfmap_core.runtime import build_tool, default_context

PLUGIN = "ev-plugin"


class GreetInput(BaseModel):
    name: str
    times: int = 1


class WriteInput(BaseModel):
    names: list[str]
    escalate: str | None = None


class TopicInput(BaseModel):
    topic: str


class Output(BaseModel):
    message: str


class EventTool(Tool):
    @operation("greet")
    def greet(self, inp: GreetInput) -> Output:
        """Greet someone."""
        if inp.name == "error":
            raise ToolError("not_found", "No such person", {"name": inp.name})
        return Output(message=" ".join([f"Hello {inp.name}"] * inp.times))

    @operation("write")
    def write(self, inp: WriteInput) -> Output:
        """Pretend to write something."""
        if inp.escalate:
            self.ctx.require_approval(inp.escalate, detail="out.txt")
        return Output(message=",".join(inp.names))

    @operation("announce")
    def announce(self, inp: TopicInput) -> Output:
        """Publish one event."""
        return Output(message=self.ctx.events.publish(inp.topic, {"n": 1}).id)

    @operation("boom")
    def boom(self, inp: TopicInput) -> Output:
        """Fail with an unexpected error."""
        raise RuntimeError("backend crashed")


def _operation(name: str, side_effects: str = "none") -> str:
    return f'[[operations]]\nname = "{name}"\ninput = "x:In"\noutput = "x:Out"\nside_effects = "{side_effects}"\n'


EVENT_MANIFEST = (
    f'[plugin]\nid = "{PLUGIN}"\nname = "Ev"\nversion = "1.0.0"\ndescription = "Test."\nlicense = "Apache-2.0"\n'
    '[plugin.entrypoint]\nmodule = "tests"\nclass = "EventTool"\n'
    + _operation("greet")
    + _operation("write", "local_write")
    + _operation("announce")
    + _operation("boom")
    + "[adapters]\nevents = true\n"
)


@pytest.fixture
def entry() -> PluginEntry:
    return PluginEntry(PLUGIN, EventTool, parse_manifest(EVENT_MANIFEST))


@pytest.fixture
def plain_entry(registry) -> PluginEntry:
    return registry.get("fake-plugin")


@pytest.fixture
def bus() -> InProcessBus:
    return InProcessBus()


@pytest.fixture
def seen(bus) -> list[Event]:
    events: list[Event] = []
    bus.subscribe("watch", f"{PLUGIN}.>", events.append)
    return events


@pytest.fixture
def adapter(entry, plain_entry, bus) -> EventAdapter:
    reg = Registry()
    reg.register(entry)
    reg.register(plain_entry)
    adapter = EventAdapter(reg, bus)
    assert adapter.attach() == [subscription_name(PLUGIN)]
    return adapter


def write_config(user_dirs: Path, text: str) -> None:
    (user_dirs / "config.toml").write_text(text, encoding="utf-8")


def request(bus, op: str, inp: dict, source: str = "core") -> Event:
    return bus.publish(f"{PLUGIN}.{op}.requested", {"input": inp}, source=source)


def answers(events: list[Event]) -> list[Event]:
    return [e for e in events if not e.topic.endswith(".requested")]


# decide treats the event channel like a job: nobody is asked


@pytest.mark.parametrize("tier", TIERS)
@pytest.mark.parametrize("can_elicit", [True, False])
@pytest.mark.parametrize("granted", [True, False])
def test_decide_treats_event_like_job(tier, can_elicit, granted) -> None:
    for policy in (Policy(), Policy(T1="ask", T2="audit")):
        args = (policy, "p", "op", tier)
        job = decide(*args, "job", {"p.op"}, can_elicit, granted=granted)
        assert decide(*args, "event", {"p.op"}, can_elicit, granted=granted) == job
        assert job != "ask"


# ctx.events


def test_ctx_events_refused_without_opt_in(plain_entry) -> None:
    tool = build_tool(plain_entry)
    with pytest.raises(ToolError) as error:
        tool.ctx.events.publish("fake-plugin.done", {})
    assert error.value.code == "permission_denied"
    with pytest.raises(ToolError) as error:
        _ = default_context("fake-plugin").events
    assert error.value.code == "permission_denied"


def test_ctx_events_publishes_with_plugin_source(entry, bus, seen) -> None:
    tool = build_tool(entry, events=PluginEvents(PLUGIN, bus))
    event = tool.ctx.events.publish(f"{PLUGIN}.indexed", {"count": 3})
    assert (event.source, event.payload, event.causation_id) == (PLUGIN, {"count": 3}, None)
    bus.drain()
    assert [e.id for e in seen] == [event.id]


@pytest.mark.parametrize(
    "topic",
    [
        "other-plugin.indexed",
        PLUGIN,
        f"{PLUGIN}.greet.requested",
        f"{PLUGIN}.greet.completed",
        f"{PLUGIN}.greet.failed",
        f"{PLUGIN}x.indexed",
        42,
    ],
)
def test_plugin_events_refuses_foreign_and_operation_topics(bus, seen, topic) -> None:
    with pytest.raises(ToolError) as error:
        PluginEvents(PLUGIN, bus).publish(topic, {})
    assert error.value.code == "permission_denied"
    bus.drain()
    assert seen == []


def test_plugin_events_without_bus_uses_user_bus(entry, user_dirs) -> None:
    assert bus_path() == user_dirs / "localappdata" / "lfmap" / "events.db"
    event = build_tool(entry).ctx.events.publish(f"{PLUGIN}.indexed", {"count": 1})
    assert event.source == PLUGIN
    assert bus_path().is_file()
    db = open_bus()
    try:
        assert db.dead_letters() == []
    finally:
        db.close()


# events_max_tier


@pytest.mark.parametrize(("config", "expected"), [({}, 0), ({"events": {}}, 0), ({"events": {"max_tier": 1}}, 1)])
def test_events_max_tier(config, expected) -> None:
    assert events_max_tier(config) == expected


@pytest.mark.parametrize("value", [2, -1, True, "1", 1.0])
def test_events_max_tier_rejects(value) -> None:
    with pytest.raises(ToolError) as error:
        events_max_tier({"events": {"max_tier": value}})
    assert error.value.code == "invalid_input"


# the adapter


def test_attach_subscribes_only_events_plugins(adapter, bus) -> None:
    bus.publish("fake-plugin.greet.requested", {"input": {"name": "Ann"}}, source="core")
    assert bus.drain() == 0


def test_t0_request_runs_and_completes(adapter, bus, seen) -> None:
    req = request(bus, "greet", {"name": "Ann", "times": 2})
    bus.drain()
    [done] = answers(seen)
    assert done.topic == f"{PLUGIN}.greet.completed"
    assert done.source == "core"
    assert done.payload == {"request_id": req.id, "output": {"message": "Hello Ann Hello Ann"}}
    assert (done.causation_id, done.correlation_id) == (req.id, req.correlation_id)
    assert bus.dead_letters() == []


def test_t1_with_max_tier_0_becomes_proposal(adapter, bus, seen) -> None:
    req = request(bus, "write", {"names": ["a"]})
    bus.drain()
    [failed] = answers(seen)
    assert failed.topic == f"{PLUGIN}.write.failed"
    error = failed.payload["error"]
    assert failed.payload["request_id"] == req.id
    assert error["code"] == "permission_denied"
    assert error["message"] == "Queued for approval"
    [path] = (approvals_dir() / "pending").glob("*.json")
    proposal = json.loads(path.read_text(encoding="utf-8"))
    assert proposal["id"] == error["details"]["approval_id"]
    assert (proposal["job"], proposal["plugin"], proposal["operation"]) == ("events", PLUGIN, "write")
    assert (proposal["input"], proposal["tier"]) == ({"names": ["a"]}, "T1")
    [record] = [json.loads(line) for line in audit_path().read_text(encoding="utf-8").splitlines()]
    assert (record["channel"], record["decision"]) == ("event", "queue")
    assert bus.dead_letters() == []


def test_t1_with_max_tier_1_runs_and_is_audited(adapter, bus, seen, user_dirs) -> None:
    write_config(user_dirs, "[events]\nmax_tier = 1\n")
    request(bus, "write", {"names": ["a", "b"]})
    bus.drain()
    [done] = answers(seen)
    assert done.topic == f"{PLUGIN}.write.completed"
    assert done.payload["output"] == {"message": "a,b"}
    [record] = [json.loads(line) for line in audit_path().read_text(encoding="utf-8").splitlines()]
    assert (record["channel"], record["decision"], record["tier"]) == ("event", "allow", "T1")
    assert not (approvals_dir() / "pending").exists()


def test_t2_escalation_is_queued_even_with_max_tier_1(adapter, bus, seen, user_dirs) -> None:
    write_config(user_dirs, "[events]\nmax_tier = 1\n")
    request(bus, "write", {"names": ["a"], "escalate": "overwrite"})
    bus.drain()
    [failed] = answers(seen)
    assert failed.payload["error"]["details"]["tier"] == "T2"
    [path] = (approvals_dir() / "pending").glob("*.json")
    assert json.loads(path.read_text(encoding="utf-8"))["tier"] == "T2"


def test_invalid_max_tier_fails_the_call(adapter, bus, seen, user_dirs) -> None:
    write_config(user_dirs, "[events]\nmax_tier = 3\n")
    request(bus, "greet", {"name": "Ann"})
    bus.drain()
    [failed] = answers(seen)
    assert failed.payload["error"]["code"] == "invalid_input"


def test_tool_error_publishes_failed(adapter, bus, seen) -> None:
    req = request(bus, "greet", {"name": "error"})
    bus.drain()
    [failed] = answers(seen)
    assert failed.topic == f"{PLUGIN}.greet.failed"
    assert failed.payload == {
        "request_id": req.id,
        "error": {"code": "not_found", "message": "No such person", "details": {"name": "error"}},
    }
    assert failed.causation_id == req.id
    assert bus.dead_letters() == []


@pytest.mark.parametrize(
    ("op", "inp", "code"),
    [("greet", {"times": 1}, "invalid_input"), ("missing", {}, "not_found")],
)
def test_bad_request_publishes_failed(adapter, bus, seen, op, inp, code) -> None:
    request(bus, op, inp)
    bus.drain()
    [failed] = answers(seen)
    assert failed.topic == f"{PLUGIN}.{op}.failed"
    assert failed.payload["error"]["code"] == code


def test_payload_with_extra_keys_publishes_failed(adapter, bus, seen) -> None:
    bus.publish(f"{PLUGIN}.greet.requested", {"input": {"name": "A"}, "run_as": "x"}, source="core")
    bus.drain()
    [failed] = answers(seen)
    assert failed.payload["error"]["code"] == "invalid_input"


def test_large_output_is_flagged(adapter, bus, seen) -> None:
    req = request(bus, "greet", {"name": "x" * 1000, "times": MAX_PAYLOAD_BYTES // 1000 + 1})
    bus.drain()
    [done] = answers(seen)
    assert done.topic == f"{PLUGIN}.greet.completed"
    assert done.payload == {"request_id": req.id, "output": None, "output_too_large": True}


def test_large_error_details_are_dropped(entry, bus, seen) -> None:
    error = ToolError("internal", "m" * 2000, {"blob": "x" * MAX_PAYLOAD_BYTES})
    req = request(bus, "greet", {"name": "Ann"})

    class Failing(EventAdapter):
        def _run(self, entry, operation, request):
            raise error

    Failing(Registry(), bus).handle(entry, req)
    bus.drain()
    [failed] = answers(seen)
    assert failed.payload["error"] == {"code": "internal", "message": "m" * 500, "details": {}}


def test_request_from_a_plugin_is_dead_lettered(adapter, bus, seen) -> None:
    req = request(bus, "greet", {"name": "Ann"}, source="other-plugin")
    bus.drain()
    assert answers(seen) == []
    [dead] = bus.dead_letters(subscription_name(PLUGIN))
    assert dead.event.id == req.id
    assert dead.error.startswith("permission_denied")


def test_other_exceptions_are_retried(adapter, bus, seen) -> None:
    request(bus, "boom", {"topic": "x"})
    assert bus.drain() == 2  # the watcher and one failed adapter attempt
    assert answers(seen) == []
    assert bus.dead_letters() == []


def test_plugin_events_during_a_call_continue_the_chain(adapter, bus, seen) -> None:
    req = request(bus, "announce", {"topic": f"{PLUGIN}.indexed"})
    bus.drain()
    indexed, done = answers(seen)
    assert indexed.topic == f"{PLUGIN}.indexed"
    assert (indexed.source, indexed.causation_id, indexed.correlation_id) == (PLUGIN, req.id, req.id)
    assert done.payload["output"] == {"message": indexed.id}


def test_plugin_cannot_request_another_operation(adapter, bus, seen) -> None:
    request(bus, "announce", {"topic": f"{PLUGIN}.greet.requested"})
    bus.drain()
    [failed] = answers(seen)
    assert failed.topic == f"{PLUGIN}.announce.failed"
    assert failed.payload["error"]["code"] == "permission_denied"


def test_handle_refuses_a_foreign_topic(adapter, entry, bus) -> None:
    other = bus.publish("other-plugin.greet.requested", {"input": {}}, source="core")
    with pytest.raises(ToolError) as error:
        adapter.handle(entry, other)
    assert error.value.code == "invalid_input"


def test_attach_skips_a_plugin_whose_name_is_too_long(bus, caplog) -> None:
    long_id = "p" + "x" * 60
    manifest = parse_manifest(EVENT_MANIFEST.replace(f'id = "{PLUGIN}"', f'id = "{long_id}"'))
    reg = Registry()
    reg.register(PluginEntry(long_id, EventTool, manifest))
    assert EventAdapter(reg, bus).attach() == []
    assert "Skipping events" in caplog.text


def test_sqlite_bus_end_to_end(entry, user_dirs) -> None:
    reg = Registry()
    reg.register(entry)
    db = open_bus()
    try:
        assert os.path.dirname(bus_path()) == str(user_dirs / "localappdata" / "lfmap")
        seen: list[Event] = []
        db.subscribe("watch", f"{PLUGIN}.*.completed", seen.append)
        EventAdapter(reg, db).attach()
        req = db.publish(f"{PLUGIN}.greet.requested", {"input": {"name": "Bo"}}, source="core")
        db.drain()
        assert [e.payload for e in seen] == [{"request_id": req.id, "output": {"message": "Hello Bo"}}]
    finally:
        db.close()
