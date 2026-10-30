import json
from pathlib import Path

import pytest
from pydantic import BaseModel
from typer.testing import CliRunner

from lfmap_core import Tool, jobs, jobs_doctor, operation
from lfmap_core.approvals import approvals_dir
from lfmap_core.cli import build_app
from lfmap_core.errors import ToolError
from lfmap_core.events_adapter import RequestResult, open_bus
from lfmap_core.events_payload import MAX_PAYLOAD_BYTES
from lfmap_core.manifest import parse_manifest
from lfmap_core.registry import PluginEntry

PLUGIN = "ev-plugin"
runner = CliRunner()


class GreetInput(BaseModel):
    name: str
    times: int = 1


class WriteInput(BaseModel):
    names: list[str]


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
        return Output(message=",".join(inp.names))


EVENT_MANIFEST = (
    f'[plugin]\nid = "{PLUGIN}"\nname = "Ev"\nversion = "1.0.0"\ndescription = "Test."\nlicense = "Apache-2.0"\n'
    '[plugin.entrypoint]\nmodule = "tests"\nclass = "EventTool"\n'
    '[[operations]]\nname = "greet"\ninput = "x:In"\noutput = "x:Out"\n'
    '[[operations]]\nname = "write"\ninput = "x:In"\noutput = "x:Out"\nside_effects = "local_write"\n'
    "[adapters]\nevents = true\n"
)


@pytest.fixture
def ev_registry(registry):
    registry.register(PluginEntry(PLUGIN, EventTool, parse_manifest(EVENT_MANIFEST)))
    return registry


def job_block(job_id: str, plugin: str, op: str, inp: str, max_tier: int = 0, via: str = "event") -> str:
    return (
        f'[[jobs]]\nid = "{job_id}"\nplugin = "{plugin}"\noperation = "{op}"\ninput = {inp}\n'
        f'schedule = {{ daily = "07:30" }}\nmax_tier = {max_tier}\nvia = "{via}"\n'
    )


@pytest.fixture
def write_jobs(user_dirs, monkeypatch):
    def write(*blocks: str) -> Path:
        path = user_dirs / "jobs.toml"
        path.write_text("\n".join(blocks), encoding="utf-8")
        monkeypatch.setenv("LFMAP_JOBS", str(path))
        return path

    return write


def write_config(user_dirs, text: str) -> None:
    (user_dirs / "config.toml").write_text(text, encoding="utf-8")


def events(topic_suffix: str) -> list[dict]:
    bus = open_bus()
    try:
        rows = bus._conn().execute("SELECT topic, payload FROM events ORDER BY seq").fetchall()
    finally:
        bus.close()
    return [json.loads(p) for t, p in rows if t.endswith(topic_suffix)]


def counts() -> dict:
    bus = open_bus()
    try:
        return bus.counts()
    finally:
        bus.close()


def test_via_defaults_to_call_and_rejects_other_values() -> None:
    base = {"id": "j", "plugin": "p", "operation": "o", "schedule": {"daily": "07:30"}}
    assert jobs.Job.model_validate(base).via == "call"
    with pytest.raises(ValueError):
        jobs.Job.model_validate({**base, "via": "mcp"})


def test_event_job_publishes_request_and_returns_completed(ev_registry, write_jobs) -> None:
    write_jobs(job_block("hello", PLUGIN, "greet", '{ name = "Hùng", times = 2 }'))
    output = jobs.run_job(ev_registry, "hello")
    assert output == Output(message="Hello Hùng Hello Hùng")
    [request] = events(".greet.requested")
    [done] = events(".greet.completed")
    assert request == {"input": {"name": "Hùng", "times": 2}}
    assert done["output"] == {"message": "Hello Hùng Hello Hùng"}
    assert counts() == {f"adapter-{PLUGIN}": {"ready": 0, "leased": 0, "done": 1, "dead": 0}}


def test_cli_prints_the_output_as_json(ev_registry, write_jobs) -> None:
    write_jobs(job_block("hello", PLUGIN, "greet", '{ name = "A" }'))
    result = runner.invoke(build_app(ev_registry), ["jobs", "run", "hello", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {"message": "Hello A"}


def test_failed_request_raises_its_tool_error(ev_registry, write_jobs) -> None:
    write_jobs(job_block("oops", PLUGIN, "greet", '{ name = "error" }'))
    with pytest.raises(ToolError) as error:
        jobs.run_job(ev_registry, "oops")
    assert (error.value.code, error.value.message) == ("not_found", "No such person")
    [failed] = events(".greet.failed")
    assert error.value.details == {"name": "error", "request_id": failed["request_id"]}


def test_event_job_needs_an_events_plugin(ev_registry, write_jobs) -> None:
    path = write_jobs(job_block("plain", "fake-plugin", "greet", '{ name = "A" }'))
    with pytest.raises(ToolError) as error:
        jobs.run_job(ev_registry, "plain")
    assert error.value.code == "invalid_input"
    assert "events = false" in error.value.message
    check, _ = jobs_doctor._load(ev_registry, path)
    assert check.ok is False
    assert "plain" in check.detail


def test_doctor_accepts_event_jobs_of_events_plugins(ev_registry, write_jobs) -> None:
    path = write_jobs(job_block("hello", PLUGIN, "greet", '{ name = "A" }'))
    check, _ = jobs_doctor._load(ev_registry, path)
    assert check.ok is True


@pytest.mark.parametrize(
    ("job_tier", "events_tier", "queued_as"),
    [(1, 0, "events"), (0, 1, "write-job"), (0, 0, "write-job")],
)
def test_the_lower_of_both_ceilings_applies(ev_registry, write_jobs, user_dirs, job_tier, events_tier, queued_as):
    write_jobs(job_block("write-job", PLUGIN, "write", '{ names = ["a"] }', max_tier=job_tier))
    write_config(user_dirs, f"[events]\nmax_tier = {events_tier}\n")
    with pytest.raises(ToolError) as error:
        jobs.run_job(ev_registry, "write-job")
    assert error.value.code == "permission_denied"
    [path] = (approvals_dir() / "pending").glob("*.json")
    assert json.loads(path.read_text(encoding="utf-8"))["job"] == queued_as
    assert bool(events(".write.requested")) == (queued_as == "events")


def test_both_ceilings_at_one_run_t1(ev_registry, write_jobs, user_dirs) -> None:
    write_jobs(job_block("write-job", PLUGIN, "write", '{ names = ["a", "b"] }', max_tier=1))
    write_config(user_dirs, "[events]\nmax_tier = 1\n")
    assert jobs.run_job(ev_registry, "write-job") == Output(message="a,b")
    assert not (approvals_dir() / "pending").exists()


def test_request_not_reached_within_max_events_times_out(ev_registry, write_jobs) -> None:
    write_jobs(job_block("hello", PLUGIN, "greet", '{ name = "A" }'))
    jobs.run_job(ev_registry, "hello")  # attaches the adapter subscription
    bus = open_bus()
    try:
        bus.publish(f"{PLUGIN}.greet.requested", {"input": {"name": "older"}}, source="core")
    finally:
        bus.close()
    with pytest.raises(ToolError) as error:
        jobs.run_job(ev_registry, "hello", max_events=1)
    assert error.value.code == "timeout"
    assert counts()[f"adapter-{PLUGIN}"]["ready"] == 1
    assert not any(name.startswith("request-") for name in counts())


def test_large_output_returns_a_marker(ev_registry, write_jobs) -> None:
    times = MAX_PAYLOAD_BYTES // 1000 + 1
    write_jobs(job_block("big", PLUGIN, "greet", f'{{ name = "{"x" * 1000}", times = {times} }}'))
    result = jobs.run_job(ev_registry, "big")
    assert isinstance(result, RequestResult)
    assert result.output_too_large


def test_watcher_subscription_is_removed(ev_registry, write_jobs) -> None:
    write_jobs(job_block("hello", PLUGIN, "greet", '{ name = "A" }'))
    jobs.run_job(ev_registry, "hello")
    assert list(counts()) == [f"adapter-{PLUGIN}"]


def test_call_jobs_are_unchanged(ev_registry, write_jobs) -> None:
    write_jobs(job_block("direct", PLUGIN, "greet", '{ name = "A" }', via="call"))
    assert jobs.run_job(ev_registry, "direct") == Output(message="Hello A")
    assert events(".greet.requested") == []


def test_answer_must_come_from_core_and_the_request() -> None:
    from datetime import UTC, datetime

    from lfmap_core.events import Event
    from lfmap_core.events_adapter import _answer

    def event(source: str, causation: str | None) -> Event:
        payload = {"request_id": "r" * 32, "output": {}}
        now = datetime.now(UTC)
        return Event(
            id="a" * 32,
            topic=f"{PLUGIN}.greet.completed",
            source=source,
            payload=payload,
            created_at=now,
            correlation_id="r" * 32,
            causation_id=causation,
        )

    assert _answer([event(PLUGIN, "r" * 32)], "r" * 32) is None
    assert _answer([event("core", "b" * 32)], "r" * 32) is None
    assert _answer([event("core", "r" * 32)], "r" * 32) is not None
