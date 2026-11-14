"""FL-3: flow triggers and `flows.run.<status>` events (docs/specs/flows.md sections 5, 6 and 10).

The plugin is conftest's `fake-plugin` (`greet` is T0, `write` is T1). Nothing here calls the real Task Scheduler:
`jobs._schtasks` is replaced, and the buses live in the test's temporary `LOCALAPPDATA`."""

import io
import subprocess
import tokenize
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from lfmap_core import approvals, flows, flows_run, flows_triggers, jobs
from lfmap_core.cli import build_app
from lfmap_core.errors import ToolError
from lfmap_core.events import Event, InProcessBus
from lfmap_core.events_adapter import bus_path, drain_after_job, open_bus, run_adapter
from lfmap_core.events_sqlite import SqliteBus

runner = CliRunner()

REPO = Path("C:/lfmap")
UV = Path("C:/Users/x/.local/bin/uv.exe")
PWSH = Path("C:/Program Files/PowerShell/7/pwsh.exe")
SCRIPT = REPO / "scripts" / "Invoke-LfmapJob.ps1"
SCRIPT_IN_REPO = jobs.repo_root() / "scripts" / "Invoke-LfmapJob.ps1"
FLOWS_RUN = Path(flows_run.__file__)
TOPIC = "fake-plugin.greet.completed"


def flow_text(
    flow_id: str,
    trigger: str = f'{{ event = "{TOPIC}" }}',
    *,
    enabled: bool = True,
    max_tier: int = 0,
    steps: str | None = None,
) -> str:
    steps = steps or 'id = "hi"\ncall = "fake-plugin.greet"\ninput = { name = "${trigger.payload.who}" }'
    head = f'[[flows]]\nid = "{flow_id}"\nmax_tier = {max_tier}\nenabled = {str(enabled).lower()}\n'
    return f"{head}trigger = {trigger}\n\n[[flows.steps]]\n{steps}\n\n"


WRITE = 'id = "save"\ncall = "fake-plugin.write"\ninput = { names = ["${trigger.payload.who}"] }'


@pytest.fixture
def put(user_dirs, monkeypatch):
    def _put(*texts: str) -> Path:
        path = user_dirs / "flows.toml"
        path.write_text("".join(texts), encoding="utf-8")
        monkeypatch.setenv("LFMAP_FLOWS", str(path))
        return path

    return _put


@pytest.fixture
def jobs_toml(user_dirs, monkeypatch):
    def _put(text: str = "") -> Path:
        path = user_dirs / "jobs.toml"
        path.write_text(text, encoding="utf-8")
        monkeypatch.setenv("LFMAP_JOBS", str(path))
        return path

    return _put


def event_on(bus, topic: str = TOPIC, payload: dict | None = None) -> Event:
    return bus.publish(topic, {"who": "Ann"} if payload is None else payload, source="core")


def runs(flow: str | None = None) -> list[flows_run.FlowRun]:
    return flows_run.list_runs(flow, limit=50)


def run_ids(flow: str | None = None) -> set[str]:
    return {r.run_id for r in runs(flow)}


# --- the event trigger: one durable subscription "flows-<id>" per flow ---------------------------------------


def test_attach_subscribes_one_flows_dash_id_per_enabled_event_flow(registry, put):
    put(
        flow_text("one", '{ event = "fake-plugin.greet.completed" }'),
        flow_text("two", '{ event = "fake-plugin.write.completed" }'),
        flow_text("off", '{ event = "other.thing.done" }', enabled=False),
        flow_text("manual", "{ manual = true }"),
        flow_text("daily", "{ schedule = { daily = '06:30' } }"),
    )
    bus = InProcessBus()
    assert flows_triggers.attach(registry, bus) == {"one": TOPIC, "two": "fake-plugin.write.completed"}
    assert bus.subscriptions() == {"flows-one": TOPIC, "flows-two": "fake-plugin.write.completed"}
    event_on(bus)
    event_on(bus, "other.thing.done")
    assert bus.drain() == 1  # only the first event reached a subscription, and only flow one's
    assert {r.flow for r in runs()} == {"one"}


def test_attach_does_nothing_without_an_enabled_event_flow(registry, put):
    put(flow_text("manual", "{ manual = true }"), flow_text("off", enabled=False))
    bus = InProcessBus()
    assert flows_triggers.attach(registry, bus) == {}
    event_on(bus)
    assert bus.drain() == 0
    put()
    assert flows_triggers.attach(registry, bus) == {}


def test_a_broken_flows_file_never_stops_the_event_adapter(registry, put, caplog):
    put("[[flows]]\nid = 'x'\nthis is not toml")
    assert flows_triggers.attach(registry, InProcessBus()) == {}
    assert "flows" in caplog.text
    assert flows_triggers.event_flows(registry) == []


def test_each_matching_flow_starts_once_with_the_event_payload(registry, put):
    put(
        flow_text("convert", f'{{ event = "{TOPIC}" }}'),
        flow_text("also", '{ event = "fake-plugin.*.completed" }'),
        flow_text("elsewhere", '{ event = "fake-plugin.write.completed" }'),
        flow_text("manual", "{ manual = true }"),
        flow_text("off", f'{{ event = "{TOPIC}" }}', enabled=False),
    )
    bus = InProcessBus()
    flows_triggers.attach(registry, bus)
    event = event_on(bus)
    assert bus.drain() == 2  # one delivery per matching flow
    assert {r.flow for r in runs()} == {"convert", "also"}
    for run in runs():
        assert run.run_id == f"ev-{event.id}-{run.flow}"
        assert run.status == "completed" and run.payload == {"who": "Ann"}
        assert run.steps[0].output == {"message": "Hello Ann"}


def test_an_event_delivered_twice_starts_no_second_run(registry, put):
    put(flow_text("convert"), flow_text("also", '{ event = "fake-plugin.*.completed" }'))
    bus = InProcessBus()
    flows_triggers.attach(registry, bus)
    seen: list[Event] = []
    bus.subscribe("watch", "fake-plugin.>", seen.append)
    event_on(bus)
    bus.drain()
    first = run_ids()
    assert len(first) == 2
    for flow_id in ("convert", "also"):
        flows_triggers.handle(registry, flow_id, seen[0])
        flows_triggers.handle(registry, flow_id, seen[0].model_copy(update={"attempt": 2}))
    assert run_ids() == first


def test_a_redelivery_after_a_crash_finishes_without_a_duplicate_run(registry, put, monkeypatch):
    put(flow_text("convert"))
    real, calls = flows_run.start, []

    def crash_after_start(*args, **kwargs):
        calls.append(kwargs["run_id"])
        run = real(*args, **kwargs)
        if len(calls) == 1:
            raise RuntimeError("process died after the run was saved")
        return run

    monkeypatch.setattr(flows_run, "start", crash_after_start)
    now = [1000.0]
    bus = InProcessBus(clock=lambda: now[0])
    flows_triggers.attach(registry, bus)
    event = event_on(bus)
    assert bus.drain() == 1
    now[0] += 3600
    assert bus.drain() == 1 and bus.dead_letters() == []
    assert calls == [f"ev-{event.id}-convert"] * 2 and len(runs()) == 1


def test_a_run_started_by_an_event_can_pause_for_approval(registry, put):
    put(flow_text("convert", steps=WRITE))
    bus = InProcessBus()
    flows_triggers.attach(registry, bus)
    event_on(bus)
    assert bus.drain() == 1 and bus.dead_letters() == []
    [run] = runs()
    assert run.status == "awaiting_approval"
    assert [p.id for p in approvals.pending()] == [run.approval_id]


def test_a_failing_step_is_a_failed_run_and_the_delivery_is_done(registry, put):
    put(
        flow_text("convert", steps='id = "x"\ncall = "fake-plugin.greet"\ninput = { name = "${trigger.payload.nope}" }')
    )
    bus = InProcessBus(max_attempts=1)
    flows_triggers.attach(registry, bus)
    event_on(bus)
    bus.drain()
    [run] = runs()
    assert run.status == "failed" and bus.dead_letters() == []


def test_a_flow_whose_id_is_too_long_for_a_subscription_name_is_left_out(registry, put, caplog):
    too_long = "a" * 100  # "flows-" + id is then longer than a subscription name may be
    put(flow_text(too_long), flow_text("convert"))
    bus = InProcessBus(max_attempts=1)
    assert flows_triggers.attach(registry, bus) == {"convert": TOPIC}
    event = event_on(bus)
    assert bus.drain() == 1 and bus.dead_letters() == []
    assert run_ids() == {f"ev-{event.id}-convert"} and too_long in caplog.text


@pytest.mark.parametrize(
    "pattern",
    ["flows.>", "flows.run.completed", ">", "*.*.*", "fake-plugin.greet.requested", "fake-plugin.*.requested", "a.>"],
)
def test_triggers_that_could_match_flows_or_requested_topics_are_refused(registry, put, pattern):
    put(flow_text("loop", f'{{ event = "{pattern}" }}'))
    assert flows_triggers.event_flows(registry) == []
    assert flows_triggers.attach(registry, InProcessBus()) == {}
    assert any(pattern in finding for finding in flows.check_flow(registry, flows.load_flows()[0]))


def test_the_handler_starts_only_its_own_flow(registry, put):
    put(flow_text("one"), flow_text("two"))
    flows_triggers.handle(registry, "one", event_on(InProcessBus()))
    assert {r.flow for r in runs()} == {"one"}


def test_the_handler_ignores_topics_no_flow_asked_for(registry, put):
    put(flow_text("convert", '{ event = "fake-plugin.greet.completed" }'))
    bus = InProcessBus()
    for topic in ("flows.run.completed", "fake-plugin.greet.requested"):
        flows_triggers.handle(registry, "convert", event_on(bus, topic))
    assert runs() == []


def test_changing_one_pattern_replaces_only_that_subscription(registry, put, caplog):
    put(flow_text("one"), flow_text("two", '{ event = "x.y.z" }'))
    bus = open_bus()
    try:
        flows_triggers.attach(registry, bus)
        first, second = event_on(bus), event_on(bus, "x.y.z")  # both queued, nothing drained yet
        put(flow_text("one"), flow_text("two", '{ event = "x.y.w" }'))
        assert flows_triggers.attach(registry, bus) == {"one": TOPIC, "two": "x.y.w"}
        assert "Flow two changed" in caplog.text
        assert bus.drain() == 1  # flow two lost its delivery; flow one's is intact
    finally:
        bus.close()
    assert run_ids() == {f"ev-{first.id}-one"} and second.id not in "".join(run_ids())


def test_removing_or_disabling_a_flow_unsubscribes_only_its_subscription(registry, put):
    put(flow_text("one"), flow_text("two"), flow_text("three"))
    bus = open_bus()
    try:
        flows_triggers.attach(registry, bus)
        put(flow_text("one", "{ manual = true }"), flow_text("two"), flow_text("three", enabled=False))
        assert flows_triggers.attach(registry, bus) == {"two": TOPIC}
        assert set(bus.subscriptions()) == {"flows-two"}
        event_on(bus)
        assert bus.drain() == 1
        put()
        assert flows_triggers.attach(registry, bus) == {}
        assert bus.subscriptions() == {}
    finally:
        bus.close()


def test_a_flow_removed_from_flows_toml_loses_its_subscription(registry, put):
    put(flow_text("keep"), flow_text("gone"))
    bus = open_bus()
    try:
        flows_triggers.attach(registry, bus)
        put(flow_text("keep"))  # "gone" has no id left to unsubscribe by
        flows_triggers.attach(registry, bus)
        assert set(bus.subscriptions()) == {"flows-keep"}
    finally:
        bus.close()


def test_the_legacy_flows_subscription_is_removed_once(registry, put, caplog):
    put(flow_text("convert"))
    bus = open_bus()
    try:
        bus.subscribe("flows", TOPIC, lambda event: None)
        event_on(bus)  # queued for the legacy subscription, dropped with it
        bus.subscribe("other", "a.b", lambda event: None)
        assert flows_triggers.attach(registry, bus) == {"convert": TOPIC}
        assert set(bus.subscriptions()) == {"flows-convert", "other"}
        assert caplog.text.count("legacy") == 1
        flows_triggers.attach(registry, bus)
        assert caplog.text.count("legacy") == 1
    finally:
        bus.close()


def test_an_unusable_flows_file_leaves_all_subscriptions_and_queued_events_alone(registry, put):
    path = put(flow_text("convert"))
    bus = open_bus()
    try:
        flows_triggers.attach(registry, bus)
        event = event_on(bus)
        path.write_text("[[flows]\n", encoding="utf-8")  # a typo while editing
        assert flows_triggers.attach(registry, bus) == {"convert": TOPIC}
        put(flow_text("convert"))
        assert flows_triggers.attach(registry, bus) == {"convert": TOPIC}
        assert bus.drain() == 1
    finally:
        bus.close()
    assert run_ids() == {f"ev-{event.id}-convert"}


def test_the_subscription_is_durable_across_processes(registry, put):
    put(flow_text("convert"))
    first = open_bus()
    flows_triggers.attach(registry, first)
    event = event_on(first)
    first.close()
    second = open_bus()  # a new process: attach again, then drain what was queued meanwhile
    try:
        assert flows_triggers.attach(registry, second) == {"convert": TOPIC}
        assert second.drain() == 1
    finally:
        second.close()
    assert run_ids() == {f"ev-{event.id}-convert"}


def test_events_run_drains_into_flows(registry, put):
    put(flow_text("convert"))
    bus = open_bus()
    flows_triggers.attach(registry, bus)
    event_on(bus)
    try:
        assert run_adapter(registry, bus, max_seconds=5, until_idle=True) == 1
    finally:
        bus.close()
    assert [r.status for r in runs()] == ["completed"]


def test_the_end_of_jobs_run_drains_flows_even_without_an_events_plugin(registry, put):
    put(flow_text("convert"))
    assert not any(entry.manifest.adapters.events for entry in registry.all())
    bus = open_bus()
    flows_triggers.attach(registry, bus)
    event_on(bus)
    bus.close()
    assert drain_after_job(registry, 100) == 1
    assert [r.status for r in runs()] == ["completed"]


def test_the_end_of_jobs_run_stays_idle_without_event_flows(registry, put):
    put(flow_text("manual", "{ manual = true }"))
    assert drain_after_job(registry, 100) == 0
    assert not bus_path().exists()


def test_a_broken_flows_file_does_not_break_events_run(registry, put):
    put("not [valid")
    bus = open_bus()
    try:
        assert run_adapter(registry, bus, max_seconds=5, until_idle=True) == 0
    finally:
        bus.close()


# --- the schedule trigger: \LFMAP\flow-<id> through `lfmap jobs register` ----------------------


def scheduled(*texts: str) -> list[flows.Flow]:
    return flows.parse_flows("".join(texts), Path("flows.toml")).flows


DAILY = flow_text("daily-report", "{ schedule = { daily = '06:30' } }")
WEEKLY = flow_text("weekly-report", "{ schedule = { weekly = 'MON 07:45' } }")


def test_a_scheduled_flow_registers_the_right_task_command():
    found = flows_triggers.task_commands(scheduled(DAILY), REPO, UV, SCRIPT, PWSH)
    assert list(found) == ["flow-daily-report"]
    action = f'"{PWSH}" -NoProfile -File "{SCRIPT}" -FlowId daily-report -RepoPath "{REPO}" -UvPath "{UV}"'
    assert found["flow-daily-report"] == [
        "schtasks", "/Create", "/TN", "\\LFMAP\\flow-daily-report", "/TR", action, "/SC", "DAILY", "/ST", "06:30", "/F",
    ]  # fmt: skip


def test_the_weekly_and_minute_schedules_are_the_jobs_ones():
    every = flow_text("poll", "{ schedule = { every_minutes = 15 } }")
    found = flows_triggers.task_commands(scheduled(WEEKLY, every), REPO, UV, SCRIPT, PWSH)
    assert found["flow-weekly-report"][6:] == ["/SC", "WEEKLY", "/D", "MON", "/ST", "07:45", "/F"]
    assert found["flow-poll"][6:] == ["/SC", "MINUTE", "/MO", "15", "/F"]


def test_only_enabled_flows_with_a_schedule_get_a_task():
    texts = [
        DAILY,
        flow_text("paused", "{ schedule = { daily = '07:00' } }", enabled=False),
        flow_text("by-event"),
        flow_text("by-hand", "{ manual = true }"),
    ]
    assert list(flows_triggers.task_commands(scheduled(*texts), REPO, UV, SCRIPT, PWSH)) == ["flow-daily-report"]


def test_a_task_action_longer_than_schtasks_allows_is_refused():
    long_repo = Path("C:/" + "x" * 250)
    with pytest.raises(ToolError) as error:
        flows_triggers.task_commands(scheduled(DAILY), long_repo, UV, SCRIPT, PWSH)
    assert error.value.code == "invalid_input"


def test_register_commands_keeps_flow_tasks_and_deletes_stale_ones():
    job = jobs.Job.model_validate(
        {"id": "echo-hello", "plugin": "echo", "operation": "say", "schedule": {"daily": "07:30"}}
    )
    extra = flows_triggers.task_commands(scheduled(DAILY), REPO, UV, SCRIPT, PWSH)
    existing = {"echo-hello", "flow-daily-report", "flow-gone", "old"}
    commands = jobs.register_commands([job], existing, REPO, UV, SCRIPT, PWSH, extra=extra)
    names = [c[c.index("/TN") + 1] for c in commands if c[1] == "/Create"]
    assert names == ["\\LFMAP\\echo-hello", "\\LFMAP\\flow-daily-report"]
    assert sorted(c[3] for c in commands if c[1] == "/Delete") == ["\\LFMAP\\flow-gone", "\\LFMAP\\old"]


def test_a_job_named_like_a_flow_task_is_refused():
    job = jobs.Job.model_validate(
        {"id": "flow-daily-report", "plugin": "echo", "operation": "say", "schedule": {"daily": "07:30"}}
    )
    extra = flows_triggers.task_commands(scheduled(DAILY), REPO, UV, SCRIPT, PWSH)
    with pytest.raises(ToolError) as error:
        jobs.register_commands([job], set(), REPO, UV, SCRIPT, PWSH, extra=extra)
    assert error.value.code == "invalid_input" and "flow-daily-report" in error.value.message


def register(registry, monkeypatch, *args, existing: str = ""):
    calls: list[list[str]] = []

    def fake_schtasks(command):
        calls.append(command)
        return existing if command[1] == "/Query" else ""

    monkeypatch.setattr(jobs, "_schtasks", fake_schtasks)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("the real Task Scheduler was called"))
    result = runner.invoke(
        build_app(registry), ["jobs", "register", "--repo", str(REPO), "--uv", str(UV), "--pwsh", str(PWSH), *args]
    )
    return result, calls


def test_jobs_register_also_registers_scheduled_flows(registry, put, jobs_toml, monkeypatch):
    jobs_toml()
    put(DAILY, flow_text("by-event"))
    existing = '"\\LFMAP\\flow-old","N/A","Ready"\r\n"\\LFMAP\\flow-daily-report","N/A","Ready"\r\n'
    result, calls = register(registry, monkeypatch, existing=existing)
    assert result.exit_code == 0, result.output
    created = [c for c in calls if c[1] == "/Create"]
    assert [c[c.index("/TN") + 1] for c in created] == ["\\LFMAP\\flow-daily-report"]
    assert "-FlowId daily-report" in created[0][created[0].index("/TR") + 1]
    assert [c[3] for c in calls if c[1] == "/Delete"] == ["\\LFMAP\\flow-old"]


def test_jobs_register_dry_run_prints_the_flow_task_and_changes_nothing(registry, put, jobs_toml, monkeypatch):
    jobs_toml()
    put(DAILY)
    result, calls = register(registry, monkeypatch, "--dry-run")
    assert result.exit_code == 0 and "\\LFMAP\\flow-daily-report" in result.output
    assert "-FlowId daily-report" in result.output
    assert [c[1] for c in calls] == ["/Query"]


def test_an_invalid_flows_file_registers_nothing(registry, put, jobs_toml, monkeypatch):
    jobs_toml()
    put("[[flows]]\nid = 'x'\nnope = 1\n")
    result, calls = register(registry, monkeypatch)
    assert result.exception is not None and result.exception.code == "invalid_input"
    assert [c for c in calls if c[1] in ("/Create", "/Delete")] == []


def test_a_task_runs_lfmap_flows_start_through_the_job_runner_script():
    text = SCRIPT_IN_REPO.read_text(encoding="utf-8")
    assert "[string]$FlowId" in text and "[string]$JobId" in text
    assert "@('flows', 'start', $FlowId)" in text and "@('jobs', 'run', $JobId)" in text
    assert "job       = $taskName" in text and '"flow-$FlowId"' in text  # same log file, the task name in `job`


# --- flows.run.<status> events -------------------------------------------------------------------


@pytest.fixture
def watch():
    """Subscribe `watch` to flows.run.* the way a later flow or console would; `collect()` reads what arrived."""
    bus = open_bus()
    bus.subscribe("watch", "flows.run.*", lambda event: None)
    bus.close()

    def collect() -> list[Event]:
        seen: list[Event] = []
        bus = open_bus()
        try:
            bus.subscribe("watch", "flows.run.*", seen.append)
            bus.drain()
        finally:
            bus.close()
        return seen

    return collect


def test_a_completed_run_publishes_flows_run_completed(registry, put, watch):
    put(flow_text("convert", "{ manual = true }"))
    run = flows_run.start(registry, "convert", {"who": "Ann"})
    [event] = watch()
    assert (event.topic, event.source) == ("flows.run.completed", "core")
    assert event.payload == {"run_id": run.run_id, "flow": "convert"}


def test_a_failed_run_publishes_flows_run_failed(registry, put, watch):
    put(
        flow_text(
            "convert", "{ manual = true }", steps='id = "x"\ncall = "fake-plugin.greet"\ninput = { name = "error" }'
        )
    )
    run = flows_run.start(registry, "convert", {})
    [event] = watch()
    assert event.topic == "flows.run.failed" and event.payload == {"run_id": run.run_id, "flow": "convert"}


def test_a_paused_run_publishes_nothing_until_it_ends(registry, put, watch):
    put(flow_text("convert", "{ manual = true }", steps=WRITE))
    paused = flows_run.start(registry, "convert", {"who": "Ann"})
    assert paused.status == "awaiting_approval" and watch() == []
    flows_run.resume(registry, approvals.load(paused.approval_id), lambda question: True)
    [event] = watch()
    assert event.topic == "flows.run.completed" and event.payload["run_id"] == paused.run_id


@pytest.mark.parametrize("status", ["rejected", "expired"])
def test_a_rejected_or_expired_run_publishes_its_status(registry, put, watch, status):
    put(flow_text("convert", "{ manual = true }", steps=WRITE))
    paused = flows_run.start(registry, "convert", {"who": "Ann"})
    flows_run.close(approvals.load(paused.approval_id), status)
    [event] = watch()
    assert event.topic == f"flows.run.{status}" and event.payload == {"run_id": paused.run_id, "flow": "convert"}


def test_an_expired_proposal_publishes_at_the_next_sweep(registry, put, watch):
    put(flow_text("convert", "{ manual = true }", steps=WRITE))
    flows_run.start(registry, "convert", {"who": "Ann"})
    approvals.sweep(datetime.now(UTC) + timedelta(days=8))
    assert [e.topic for e in watch()] == ["flows.run.expired"]


def test_each_ending_publishes_exactly_one_event(registry, put, watch):
    put(flow_text("convert", "{ manual = true }"))
    for _ in range(3):
        flows_run.start(registry, "convert", {"who": "Ann"})
    assert [e.topic for e in watch()] == ["flows.run.completed"] * 3


def test_without_a_bus_nothing_is_published_and_none_is_created(registry, put):
    put(flow_text("convert", "{ manual = true }"))
    assert not bus_path().exists()
    assert flows_run.start(registry, "convert", {"who": "Ann"}).status == "completed"
    assert not bus_path().exists()


def test_a_bus_that_cannot_be_opened_never_fails_the_run(registry, put):
    put(flow_text("convert", "{ manual = true }"))
    bus_path().parent.mkdir(parents=True, exist_ok=True)
    bus_path().write_bytes(b"this is not a database" * 100)
    run = flows_run.start(registry, "convert", {"who": "Ann"})
    assert run.status == "completed" and flows_run.load_run(run.run_id).status == "completed"


def test_a_publish_error_never_fails_the_run(registry, put, watch, monkeypatch):
    put(flow_text("convert", "{ manual = true }"))

    def refuse(self, *args, **kwargs):
        raise ToolError("backend_unavailable", "bus is full")

    monkeypatch.setattr(SqliteBus, "publish", refuse)
    assert flows_run.start(registry, "convert", {"who": "Ann"}).status == "completed"


def test_an_event_started_run_publishes_when_it_ends(registry, put, watch):
    put(flow_text("convert"))
    bus = open_bus()
    flows_triggers.attach(registry, bus)
    event_on(bus)
    bus.drain()
    bus.close()
    [done] = watch()
    assert done.topic == "flows.run.completed" and done.payload["flow"] == "convert"


def test_flows_run_events_never_start_a_flow(registry, put, watch):
    put(flow_text("convert"), flow_text("chain", '{ event = "flows.run.completed" }'))
    bus = open_bus()
    assert flows_triggers.attach(registry, bus) == {"convert": TOPIC}  # the flows.* flow was left out
    event_on(bus)
    bus.drain()
    bus.drain()
    bus.close()
    assert {r.flow for r in runs()} == {"convert"}


# --- size cap (spec section 9) -------------------------------------------------------------------


def code_lines(path: Path) -> int:
    """The rules of `spikes/2a1-framework/common/metrics.code_lines`: no blank, comment or docstring lines."""
    source = path.read_text(encoding="utf-8")
    skip: set[int] = set()
    previous = tokenize.INDENT
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type == tokenize.STRING and previous in (tokenize.INDENT, tokenize.NEWLINE, tokenize.DEDENT):
            skip.update(range(tok.start[0], tok.end[0] + 1))
        if tok.type not in (tokenize.NL, tokenize.COMMENT):
            previous = tok.type
    lines = enumerate(source.splitlines(), 1)
    return sum(1 for no, line in lines if line.strip() and not line.lstrip().startswith("#") and no not in skip)


def test_flows_run_stays_within_the_230_line_cap():
    assert code_lines(FLOWS_RUN) <= 230


def test_the_triggers_live_in_their_own_module():
    source = FLOWS_RUN.read_text(encoding="utf-8")
    assert "covering_pattern" not in source and "task_commands" not in source
    assert "covering_pattern" not in Path(flows_triggers.__file__).read_text(encoding="utf-8")
