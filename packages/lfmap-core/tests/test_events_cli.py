import json
import os
from pathlib import Path

import anyio
import pytest
from pydantic import BaseModel
from typer.testing import CliRunner

from lfmap_core import Tool, cli, events_adapter, operation
from lfmap_core.cli import build_app
from lfmap_core.config import app_dir
from lfmap_core.errors import ToolError
from lfmap_core.events import Event, InProcessBus
from lfmap_core.events_adapter import bus_path, drain_after_job, open_bus, run_adapter, subscription_name
from lfmap_core.manifest import parse_manifest
from lfmap_core.mcp_adapter import build_server
from lfmap_core.registry import PluginEntry

PLUGIN = "ev-plugin"
SUB = subscription_name(PLUGIN)
runner = CliRunner()


class GreetInput(BaseModel):
    name: str


class Output(BaseModel):
    message: str


class EventTool(Tool):
    @operation("greet")
    def greet(self, inp: GreetInput) -> Output:
        """Greet someone."""
        return Output(message=f"Hello {inp.name}")


EVENT_MANIFEST = (
    f'[plugin]\nid = "{PLUGIN}"\nname = "Ev"\nversion = "1.0.0"\ndescription = "Test."\nlicense = "Apache-2.0"\n'
    '[plugin.entrypoint]\nmodule = "tests"\nclass = "EventTool"\n'
    '[[operations]]\nname = "greet"\ninput = "x:In"\noutput = "x:Out"\n'
    "[adapters]\nevents = true\n"
)

JOBS_TOML = """
[[jobs]]
id = "hello"
plugin = "fake-plugin"
operation = "greet"
input = { name = "A" }
schedule = { daily = "07:30" }
"""


@pytest.fixture
def ev_registry(registry):
    registry.register(PluginEntry(PLUGIN, EventTool, parse_manifest(EVENT_MANIFEST)))
    return registry


@pytest.fixture
def jobs_file(user_dirs, monkeypatch) -> Path:
    path = user_dirs / "jobs.toml"
    path.write_text(JOBS_TOML, encoding="utf-8")
    monkeypatch.setenv("LFMAP_JOBS", str(path))
    return path


@pytest.fixture
def terminal(monkeypatch):
    monkeypatch.setattr(cli, "_interactive", lambda: True)


def run(registry, *args):
    return runner.invoke(build_app(registry), list(args))


def queue_requests(registry, *names: str, source: str = "core") -> list[Event]:
    """Publish requests after the adapter subscription exists, as a running adapter would see them."""
    bus = open_bus()
    try:
        events_adapter.EventAdapter(registry, bus).attach()
        topic = f"{PLUGIN}.greet.requested"
        return [bus.publish(topic, {"input": {"name": n}}, source=source) for n in names]
    finally:
        bus.close()


def counts() -> dict:
    bus = open_bus()
    try:
        return bus.counts()
    finally:
        bus.close()


def test_bus_stays_in_the_test_folder(user_dirs) -> None:
    assert bus_path() == user_dirs / "localappdata" / "lfmap" / "events.db"
    assert Path(os.environ["LOCALAPPDATA"]).is_relative_to(user_dirs)
    assert app_dir().is_relative_to(user_dirs)


# status and dead


def test_status_lists_subscriptions_and_states(ev_registry) -> None:
    queue_requests(ev_registry, "A", "B")
    result = run(ev_registry, "events", "status", "--json")
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {SUB: {"ready": 2, "leased": 0, "done": 0, "dead": 0}}
    text = run(ev_registry, "events", "status").output
    assert text.strip() == f"{SUB}  ready=2  leased=0  done=0  dead=0"


def test_status_on_an_empty_bus(ev_registry) -> None:
    result = run(ev_registry, "events", "status", "--json")
    assert result.exit_code == 0
    assert json.loads(result.output) == {}


def test_dead_lists_dead_letters(ev_registry) -> None:
    [forged] = queue_requests(ev_registry, "A", source="other-plugin")
    assert run(ev_registry, "events", "run", "--until-idle").exit_code == 0
    result = run(ev_registry, "events", "dead", "--json")
    assert result.exit_code == 0
    [letter] = json.loads(result.output)
    assert (letter["event"]["id"], letter["subscription"]) == (forged.id, SUB)
    assert letter["error"].startswith("permission_denied")
    text = run(ev_registry, "events", "dead", "--subscription", SUB).output
    assert text.startswith(f"{forged.id}  {SUB}  {PLUGIN}.greet.requested  attempts=1  permission_denied")
    assert json.loads(run(ev_registry, "events", "dead", "--subscription", "watch", "--json").output) == []


def test_dead_escapes_control_characters(ev_registry, monkeypatch) -> None:
    def failing(self, entry, request):
        raise ToolError("invalid_input", "bad \x1b[2Jinput")

    monkeypatch.setattr(events_adapter.EventAdapter, "handle", failing)
    queue_requests(ev_registry, "A")
    run(ev_registry, "events", "run", "--until-idle")
    text = run(ev_registry, "events", "dead").output
    assert "\x1b" not in text
    assert "\\u001b[2J" in text


# retry and prune: only at an interactive terminal


@pytest.mark.parametrize("args", [["retry", "0" * 32, SUB], ["prune"], ["prune", "--days", "0"]])
def test_retry_and_prune_refuse_without_terminal(ev_registry, args) -> None:
    result = run(ev_registry, "events", *args)
    assert isinstance(result.exception, ToolError)
    assert result.exception.code == "permission_denied"
    assert not bus_path().exists()


def test_retry_requeues_a_dead_letter(ev_registry, terminal) -> None:
    [forged] = queue_requests(ev_registry, "A", source="other-plugin")
    run(ev_registry, "events", "run", "--until-idle")
    result = run(ev_registry, "events", "retry", forged.id, SUB)
    assert result.exit_code == 0, result.output
    assert counts()[SUB]["ready"] == 1
    again = run(ev_registry, "events", "retry", forged.id, SUB)
    assert again.exception.code == "not_found"


def test_prune_deletes_handled_events_only(ev_registry, terminal) -> None:
    queue_requests(ev_registry, "A")
    run(ev_registry, "events", "run", "--until-idle")
    queue_requests(ev_registry, "B", source="other-plugin")
    run(ev_registry, "events", "run", "--until-idle")
    queue_requests(ev_registry, "C")
    assert run(ev_registry, "events", "prune").output.startswith("Deleted 0 event(s)\n")
    result = run(ev_registry, "events", "prune", "--days", "0")
    assert result.exit_code == 0
    assert result.output.startswith("Deleted 2 event(s)\n")  # request A and its .completed (no subscriber)
    assert counts()[SUB] == {"ready": 1, "leased": 0, "done": 0, "dead": 1}


def test_prune_rejects_negative_days(ev_registry, terminal) -> None:
    assert run(ev_registry, "events", "prune", "--days", "-1").exit_code == 2


# run


def test_run_until_idle_handles_requests(ev_registry) -> None:
    requests = queue_requests(ev_registry, "A", "B")
    bus = open_bus()
    try:
        seen: list[Event] = []
        bus.subscribe("watch", f"{PLUGIN}.*.completed", seen.append)
    finally:
        bus.close()
    result = run(ev_registry, "events", "run", "--until-idle")
    assert result.exit_code == 0, result.output
    assert result.output.strip() == "Handled 2 event(s)"
    assert counts()[SUB]["done"] == 2
    assert counts()["watch"]["ready"] == 2
    bus = open_bus()
    try:
        bus.subscribe("watch", f"{PLUGIN}.*.completed", seen.append)
        bus.drain()
    finally:
        bus.close()
    assert [e.payload["request_id"] for e in seen] == [r.id for r in requests]
    assert [e.payload["output"] for e in seen] == [{"message": "Hello A"}, {"message": "Hello B"}]


def test_run_rejects_bad_max_seconds(ev_registry) -> None:
    assert run(ev_registry, "events", "run", "--max-seconds", "0").exit_code == 2


class FakeTime:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def test_run_adapter_waits_until_max_seconds(ev_registry) -> None:
    fake = FakeTime()
    bus = InProcessBus()
    assert run_adapter(ev_registry, bus, max_seconds=3, clock=fake.clock, sleep=fake.sleep) == 0
    assert fake.sleeps == [1.0, 1.0, 1.0]


def test_run_adapter_until_idle_returns_at_once(ev_registry) -> None:
    fake = FakeTime()
    bus = InProcessBus()
    events_adapter.EventAdapter(ev_registry, bus).attach()
    bus.publish(f"{PLUGIN}.greet.requested", {"input": {"name": "A"}}, source="core")
    handled = run_adapter(ev_registry, bus, max_seconds=60, until_idle=True, clock=fake.clock, sleep=fake.sleep)
    assert handled == 1
    assert fake.sleeps == []


def test_run_adapter_stops_at_the_deadline_while_busy(ev_registry, monkeypatch) -> None:
    fake = FakeTime()
    bus = InProcessBus()

    def slow_drain(*, max_events: int) -> int:
        fake.now += 30
        return max_events

    monkeypatch.setattr(bus, "drain", slow_drain)
    assert run_adapter(ev_registry, bus, max_seconds=60, clock=fake.clock, sleep=fake.sleep) == 200


# jobs run drains, bounded


def test_jobs_run_drains_the_bus(ev_registry, jobs_file) -> None:
    queue_requests(ev_registry, "A", "B")
    result = run(ev_registry, "jobs", "run", "hello")
    assert result.exit_code == 0, result.output
    assert "Handled 2 event(s)" in result.output
    assert counts()[SUB]["done"] == 2


def test_jobs_run_drain_is_bounded(ev_registry, jobs_file) -> None:
    queue_requests(ev_registry, "A", "B", "C")
    result = run(ev_registry, "jobs", "run", "hello", "--max-events", "2")
    assert result.exit_code == 0
    assert counts()[SUB] == {"ready": 1, "leased": 0, "done": 2, "dead": 0}
    assert run(ev_registry, "jobs", "run", "hello", "--max-events", "0").exit_code == 2


def test_jobs_run_drains_even_when_the_job_fails(ev_registry, jobs_file) -> None:
    queue_requests(ev_registry, "A")
    result = run(ev_registry, "jobs", "run", "missing")
    assert result.exception.code == "not_found"
    assert counts()[SUB]["done"] == 1


def test_jobs_run_json_output_is_unchanged_without_events(registry, jobs_file) -> None:
    result = run(registry, "jobs", "run", "hello", "--json")
    assert json.loads(result.output) == {"message": "Hello A"}
    assert not bus_path().exists()


def test_jobs_run_keeps_the_job_result_when_the_bus_fails(ev_registry, jobs_file, monkeypatch) -> None:
    def broken(registry, max_events):
        raise ToolError("backend_unavailable", "events.db was written by a newer lfmap")

    monkeypatch.setattr(cli, "drain_after_job", broken)
    result = run(ev_registry, "jobs", "run", "hello")
    assert result.exit_code == 0
    assert "Warning: events were not drained" in result.output


def test_drain_after_job_without_events_plugins_opens_nothing(registry) -> None:
    assert drain_after_job(registry, 10) == 0
    assert not bus_path().exists()


def test_no_mcp_form_for_events_commands(ev_registry) -> None:
    names = {tool.name for tool in anyio.run(build_server(ev_registry, []).list_tools)}
    assert names == {"fake_plugin_greet", "fake_plugin_write", "ev_plugin_greet"}
