import json

import pytest
from typer.testing import CliRunner

from lfmap_core import jobs_doctor
from lfmap_core.cli import build_app
from lfmap_core.config import app_dir
from lfmap_core.errors import ToolError
from lfmap_core.events_adapter import bus_path, open_bus

runner = CliRunner()

GOOD_FLOW = """
[[flows]]
id = "by-hand"
trigger = { manual = true }
steps = [{ id = "hello", call = "fake-plugin.greet", input = { name = "B" } }]
"""

BAD_FLOW = """
[[flows]]
id = "broken"
trigger = { manual = true }
steps = [{ id = "s", call = "nope.x" }]
"""


@pytest.fixture
def jobs_checks(monkeypatch):
    """Fake `jobs doctor` results; the checks themselves are tested in test_jobs_doctor.py."""
    checks = [
        jobs_doctor.Check("uv", True, "uv 0.5"),
        jobs_doctor.Check("wake", None, "not set", "set it"),
    ]
    monkeypatch.setattr(jobs_doctor, "run_checks", lambda registry, path=None: checks)
    return checks


@pytest.fixture
def put_flows(user_dirs, monkeypatch):
    def _put(text: str) -> None:
        path = user_dirs / "flows.toml"
        path.write_text(text, encoding="utf-8")
        monkeypatch.setenv("LFMAP_FLOWS", str(path))

    return _put


def doctor(registry, *args):
    return runner.invoke(build_app(registry), ["doctor", *args])


def make_dead_letter() -> None:
    bus = open_bus()
    try:

        def fail(event) -> None:
            raise ToolError("invalid_input", "no")

        bus.subscribe("watch", "demo.>", fail)
        bus.publish("demo.x", {}, source="demo")
        bus.drain()
    finally:
        bus.close()


def test_exit_0_without_failures(registry, jobs_checks, put_flows) -> None:
    put_flows(GOOD_FLOW)
    result = doctor(registry)
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert [line for line in lines if not line.startswith(" ")] == ["jobs", "flows", "events"]
    assert "All flows ok" in result.output


def test_exit_1_on_failed_job_check(registry, jobs_checks, put_flows) -> None:
    put_flows(GOOD_FLOW)
    jobs_checks.append(jobs_doctor.Check("tasks", False, "missing"))
    assert doctor(registry).exit_code == 1


def test_exit_1_on_flow_finding(registry, jobs_checks, put_flows) -> None:
    put_flows(BAD_FLOW)
    result = doctor(registry)
    assert result.exit_code == 1
    assert "FAIL" in result.output


def test_exit_1_on_unreadable_flows_file(registry, jobs_checks, put_flows) -> None:
    put_flows("not = [valid")
    assert doctor(registry).exit_code == 1


def test_json_groups(registry, jobs_checks, put_flows) -> None:
    put_flows(BAD_FLOW)
    result = doctor(registry, "--json")
    assert result.exit_code == 1
    report = json.loads(result.output)
    assert set(report) == {"ok", "jobs", "flows", "events"}
    assert report["ok"] is False
    assert [row["name"] for row in report["jobs"]] == ["uv", "wake"]
    assert report["flows"] and "finding" in report["flows"][0]
    assert report["events"]["subscriptions"] == {}


def test_does_not_create_events_db(registry, jobs_checks, put_flows) -> None:
    put_flows(GOOD_FLOW)
    assert not bus_path().exists()
    assert "no events.db yet" in doctor(registry).output
    assert not bus_path().exists()
    assert not app_dir().joinpath("events.db").exists()


def test_dead_letters_warn_but_do_not_fail(registry, jobs_checks, put_flows) -> None:
    put_flows(GOOD_FLOW)
    make_dead_letter()
    result = doctor(registry)
    assert result.exit_code == 0, result.output
    assert "warn  watch" in result.output
    report = json.loads(doctor(registry, "--json").output)
    assert report["ok"] is True
    assert report["events"]["warn"] == ["watch"]
    assert report["events"]["subscriptions"]["watch"]["dead"] == 1


def test_old_commands_are_unchanged(registry, jobs_checks, put_flows) -> None:
    put_flows(GOOD_FLOW)
    app = build_app(registry)
    jobs = runner.invoke(app, ["jobs", "doctor"])
    assert jobs.output.splitlines() == ["uv    ok    uv 0.5", "wake  warn  not set  -> set it"]
    assert jobs.exit_code == 0
    flows = runner.invoke(app, ["flows", "check"])
    assert flows.output.strip() == "All flows ok"
    assert flows.exit_code == 0
    events = runner.invoke(app, ["events", "status", "--json"])
    assert json.loads(events.output) == {}
