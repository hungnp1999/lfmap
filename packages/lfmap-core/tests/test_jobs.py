import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from lfmap_core import jobs
from lfmap_core.approval import audit_path
from lfmap_core.cli import build_app
from lfmap_core.config import app_dir
from lfmap_core.errors import ToolError

runner = CliRunner()

JOBS_TOML = """
[[jobs]]
id = "hello"
plugin = "fake-plugin"
operation = "greet"
input = { name = "Hùng" }
schedule = { daily = "07:30" }

[[jobs]]
id = "weekly-write"
plugin = "fake-plugin"
operation = "write"
input = { names = ["a"] }
schedule = { weekly = "MON 07:30" }
max_tier = 1

[[jobs]]
id = "every-hour"
plugin = "fake-plugin"
operation = "greet"
input = { name = "B" }
schedule = { every_minutes = 60 }
enabled = false
"""

REPO = Path("C:/lfmap")
UV = Path("C:/Users/x/.local/bin/uv.exe")
SCRIPT = REPO / "scripts" / "Invoke-LfmapJob.ps1"


@pytest.fixture
def jobs_file(user_dirs, monkeypatch) -> Path:
    path = user_dirs / "jobs.toml"
    path.write_text(JOBS_TOML, encoding="utf-8")
    monkeypatch.setenv("LFMAP_JOBS", str(path))
    return path


def run(registry, *args):
    return runner.invoke(build_app(registry), list(args))


def job(**overrides) -> jobs.Job:
    data = {"id": "echo-hello", "plugin": "echo", "operation": "say", "schedule": {"daily": "07:30"}}
    return jobs.Job.model_validate({**data, **overrides})


def test_jobs_path_default_and_override(user_dirs, monkeypatch):
    monkeypatch.delenv("LFMAP_JOBS", raising=False)
    assert jobs.jobs_path() == app_dir() / "jobs.toml"
    monkeypatch.setenv("LFMAP_JOBS", str(user_dirs / "other.toml"))
    assert jobs.jobs_path() == user_dirs / "other.toml"


def test_missing_file_means_no_jobs(user_dirs):
    assert jobs.load_jobs(user_dirs / "absent.toml") == []


def test_load_jobs(jobs_file):
    loaded = jobs.load_jobs()
    assert [j.id for j in loaded] == ["hello", "weekly-write", "every-hour"]
    hello, weekly, hourly = loaded
    assert hello.input == {"name": "Hùng"} and hello.max_tier == 0 and hello.enabled
    assert hello.schedule.daily == "07:30"
    assert weekly.schedule.weekly == "MON 07:30" and weekly.max_tier == 1
    assert hourly.schedule.every_minutes == 60 and not hourly.enabled


@pytest.mark.parametrize(
    "overrides",
    [
        {"id": "Echo_Hello"},
        {"id": "1echo"},
        {"schedule": {"daily": "07:30", "every_minutes": 5}},
        {"schedule": {}},
        {"schedule": {"daily": "7:30"}},
        {"schedule": {"daily": "24:00"}},
        {"schedule": {"weekly": "FUN 07:30"}},
        {"schedule": {"weekly": "MON"}},
        {"schedule": {"every_minutes": 0}},
        {"schedule": {"every_minutes": 1440}},
        {"max_tier": 2},
        {"unknown": True},
    ],
)
def test_invalid_job_is_rejected(user_dirs, overrides):
    data = {"id": "echo-hello", "plugin": "echo", "operation": "say", "schedule": {"daily": "07:30"}, **overrides}
    plain = {key: value for key, value in data.items() if not isinstance(value, dict)}
    lines = ["[[jobs]]"] + [f"{key} = {json.dumps(value)}" for key, value in plain.items()]
    schedule = data["schedule"]
    lines.append("schedule = { " + ", ".join(f"{k} = {json.dumps(v)}" for k, v in schedule.items()) + " }")
    path = user_dirs / "jobs.toml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(ToolError) as error:
        jobs.load_jobs(path)
    assert error.value.code == "invalid_input"


def test_duplicate_ids_are_rejected(user_dirs):
    block = '[[jobs]]\nid = "a"\nplugin = "echo"\noperation = "say"\nschedule = { daily = "07:30" }\n'
    path = user_dirs / "jobs.toml"
    path.write_text(block + block, encoding="utf-8")
    with pytest.raises(ToolError) as error:
        jobs.load_jobs(path)
    assert error.value.code == "invalid_input"


def test_bad_toml_is_invalid_input(user_dirs):
    path = user_dirs / "jobs.toml"
    path.write_text("[[jobs]\n", encoding="utf-8")
    with pytest.raises(ToolError) as error:
        jobs.load_jobs(path)
    assert error.value.code == "invalid_input"


def test_task_command_daily():
    command = jobs.task_command(job(), REPO, UV, SCRIPT)
    assert command[:2] == ["schtasks", "/Create"]
    assert command[command.index("/TN") + 1] == "\\LFMAP\\echo-hello"
    assert command[command.index("/SC") + 1] == "DAILY"
    assert command[command.index("/ST") + 1] == "07:30"
    assert command[-1] == "/F"
    action = command[command.index("/TR") + 1]
    assert action.startswith("pwsh -NoProfile -File ")
    assert str(SCRIPT) in action and "-JobId echo-hello" in action
    assert str(REPO) in action and str(UV) in action


def test_task_command_weekly():
    command = jobs.task_command(job(schedule={"weekly": "MON 07:30"}), REPO, UV, SCRIPT)
    assert command[command.index("/SC") + 1] == "WEEKLY"
    assert command[command.index("/D") + 1] == "MON"
    assert command[command.index("/ST") + 1] == "07:30"


def test_task_command_every_minutes():
    command = jobs.task_command(job(schedule={"every_minutes": 60}), REPO, UV, SCRIPT)
    assert command[command.index("/SC") + 1] == "MINUTE"
    assert command[command.index("/MO") + 1] == "60"
    assert "/ST" not in command


def test_delete_command():
    assert jobs.delete_command("old") == ["schtasks", "/Delete", "/TN", "\\LFMAP\\old", "/F"]


QUERY_CSV = (
    '"\\LFMAP\\echo-hello","10/22/2026 7:30:00 AM","Ready"\r\n'
    '"\\LFMAP\\old","N/A","Disabled"\r\n'
    '"\\Microsoft\\Windows\\Defrag\\ScheduledDefrag","N/A","Ready"\r\n'
    '"\\LFMAPX\\fake","N/A","Ready"\r\n'
)


def test_registered_tasks_only_reads_the_lfmap_folder():
    assert jobs.registered_tasks(QUERY_CSV) == {"echo-hello", "old"}


def test_register_commands_creates_enabled_and_deletes_the_rest():
    current = [job(), job(id="paused", enabled=False), job(id="paused-new", enabled=False)]
    commands = jobs.register_commands(current, {"echo-hello", "old", "paused"}, REPO, UV, SCRIPT)
    creates = [c for c in commands if c[1] == "/Create"]
    deletes = [c for c in commands if c[1] == "/Delete"]
    assert [c[c.index("/TN") + 1] for c in creates] == ["\\LFMAP\\echo-hello"]
    assert sorted(c[3] for c in deletes) == ["\\LFMAP\\old", "\\LFMAP\\paused"]
    assert all(c[3].startswith("\\LFMAP\\") for c in deletes)


def test_cli_jobs_list(jobs_file, registry):
    result = run(registry, "jobs", "list", "--json")
    assert result.exit_code == 0
    assert json.loads(result.output) == [
        {"id": "hello", "operation": "fake-plugin.greet", "schedule": "daily 07:30", "enabled": True},
        {"id": "weekly-write", "operation": "fake-plugin.write", "schedule": "weekly MON 07:30", "enabled": True},
        {"id": "every-hour", "operation": "fake-plugin.greet", "schedule": "every 60 min", "enabled": False},
    ]


def test_cli_jobs_run(jobs_file, registry):
    result = run(registry, "jobs", "run", "hello", "--json")
    assert result.exit_code == 0
    assert json.loads(result.output) == {"message": "Hello Hùng"}


def test_jobs_run_uses_the_job_channel(jobs_file, registry, monkeypatch):
    seen = {}

    def fake_run_operation(entry, name, payload, variables=None, **kwargs):
        seen.update(plugin=entry.id, name=name, payload=payload, **kwargs)
        return jobs.JobsFile()

    monkeypatch.setattr(jobs, "run_operation", fake_run_operation)
    jobs.run_job(registry, "hello")
    assert seen["plugin"] == "fake-plugin" and seen["name"] == "greet"
    assert seen["payload"] == {"name": "Hùng"}
    assert seen["channel"] == "job"
    assert seen["approver"] is not None


def test_disabled_job_does_not_run(jobs_file, registry):
    assert run(registry, "jobs", "run", "every-hour").exception.code == "invalid_input"


def test_unknown_job(jobs_file, registry):
    assert run(registry, "jobs", "run", "khong-co").exception.code == "not_found"


def test_unknown_plugin_or_operation(user_dirs, registry, monkeypatch):
    path = user_dirs / "jobs.toml"
    path.write_text(
        '[[jobs]]\nid = "a"\nplugin = "fake-plugin"\noperation = "nope"\nschedule = { daily = "07:30" }\n'
        '[[jobs]]\nid = "b"\nplugin = "nope"\noperation = "greet"\nschedule = { daily = "07:30" }\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("LFMAP_JOBS", str(path))
    assert run(registry, "jobs", "run", "a").exception.code == "not_found"
    assert run(registry, "jobs", "run", "b").exception.code == "not_found"


def test_side_effects_above_t0_are_refused_until_j3(jobs_file, registry):
    # TC-J2 approver refuses everything above T0, even with max_tier = 1; TC-J3 replaces it.
    result = run(registry, "jobs", "run", "weekly-write")
    assert result.exception.code == "permission_denied"
    records = [json.loads(line) for line in audit_path().read_text(encoding="utf-8").splitlines()]
    assert records[-1]["channel"] == "job" and records[-1]["decision"] == "deny"


def test_register_dry_run_only_queries(jobs_file, registry, monkeypatch):
    calls = []

    def fake_schtasks(args):
        calls.append(args)
        return QUERY_CSV

    monkeypatch.setattr(jobs, "_schtasks", fake_schtasks)
    result = run(registry, "jobs", "register", "--dry-run", "--repo", str(REPO), "--uv", str(UV))
    assert result.exit_code == 0
    assert len(calls) == 1 and calls[0][:2] == ["schtasks", "/Query"]
    assert "/Create" in result.output and "\\LFMAP\\hello" in result.output
    assert "/Delete" in result.output and "\\LFMAP\\old" in result.output
    assert "Microsoft" not in result.output


def test_register_runs_each_command(jobs_file, registry, monkeypatch):
    calls = []

    def fake_schtasks(args):
        calls.append(args)
        return QUERY_CSV if args[1] == "/Query" else ""

    monkeypatch.setattr(jobs, "_schtasks", fake_schtasks)
    result = run(registry, "jobs", "register", "--repo", str(REPO), "--uv", str(UV))
    assert result.exit_code == 0
    created = {c[c.index("/TN") + 1] for c in calls if c[1] == "/Create"}
    deleted = {c[3] for c in calls if c[1] == "/Delete"}
    assert created == {"\\LFMAP\\hello", "\\LFMAP\\weekly-write"}
    assert deleted == {"\\LFMAP\\echo-hello", "\\LFMAP\\old"}


def _no_schtasks(args):
    raise ToolError("backend_unavailable", "schtasks was not found (Windows only)")


def test_register_dry_run_without_schtasks_prints_creates(jobs_file, registry, monkeypatch):
    monkeypatch.setattr(jobs, "_schtasks", _no_schtasks)
    result = run(registry, "jobs", "register", "--dry-run", "--repo", str(REPO), "--uv", str(UV))
    assert result.exit_code == 0
    assert "\\LFMAP\\hello" in result.output and "\\LFMAP\\weekly-write" in result.output
    assert "/Delete" not in result.output


def test_register_without_schtasks_fails(jobs_file, registry, monkeypatch):
    monkeypatch.setattr(jobs, "_schtasks", _no_schtasks)
    result = run(registry, "jobs", "register", "--repo", str(REPO), "--uv", str(UV))
    assert result.exception.code == "backend_unavailable"
