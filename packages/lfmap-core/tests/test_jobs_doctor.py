import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from lfmap_core import jobs, jobs_doctor
from lfmap_core.cli import build_app
from lfmap_core.errors import ToolError
from lfmap_core.registry import PluginEntry, Registry

runner = CliRunner()

JOBS_TOML = """
[[jobs]]
id = "hello"
plugin = "fake-plugin"
operation = "greet"
schedule = { daily = "07:30" }
input = { name = "x" }

[[jobs]]
id = "off"
plugin = "fake-plugin"
operation = "greet"
schedule = { daily = "08:00" }
input = { name = "x" }
enabled = false
"""

QUERY = tuple(jobs.QUERY)
XML_QUERY = ("schtasks", "/Query", "/TN", "\\LFMAP\\hello", "/XML")
POWER = ("powercfg", "/query", "SCHEME_CURRENT", "SUB_SLEEP", "STANDBYIDLE")

TASKS_CSV = '"\\LFMAP\\hello","N/A","Ready"\n"\\Microsoft\\Windows\\Other","N/A","Ready"\n'


def task_xml(logon: str = "InteractiveToken", wake: str = "false", command: str | None = None) -> str:
    action = f"\n  <Actions><Exec><Command>{command}</Command></Exec></Actions>" if command else ""
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Principals>
    <Principal id="Author">
      <UserId>DIEP-ANH\\Admin</UserId>
      <LogonType>{logon}</LogonType>
    </Principal>
  </Principals>
  <Settings>
    <WakeToRun>{wake}</WakeToRun>
  </Settings>{action}
</Task>
"""


def powercfg(ac: int, dc: int = 900) -> str:
    return f"""Power Scheme GUID: 381b4222-f694-41f0-9685-ff5bb260df2e  (Balanced)
  GUID Alias: SCHEME_BALANCED
  Subgroup GUID: 238c9fa8-0aad-41ed-83f4-97be242c8f20  (Sleep)
    GUID Alias: SUB_SLEEP
    Power Setting GUID: 29f6c1db-86da-48c5-9fdb-f2b67b1f44da  (Sleep after)
      GUID Alias: STANDBYIDLE
      Minimum Possible Setting: 0x00000000
      Maximum Possible Setting: 0xffffffff
      Possible Settings increment: 0x00000001
      Possible Settings units: Seconds
    Current AC Power Setting Index: 0x{ac:08x}
    Current DC Power Setting Index: 0x{dc:08x}
"""


@pytest.fixture
def jobs_file(user_dirs, monkeypatch) -> Path:
    path = user_dirs / "jobs.toml"
    path.write_text(JOBS_TOML, encoding="utf-8")
    monkeypatch.setenv("LFMAP_JOBS", str(path))
    return path


@pytest.fixture
def network_registry(registry) -> Registry:
    entry = registry.get("fake-plugin")
    permissions = entry.manifest.permissions.model_copy(update={"network": True})
    manifest = entry.manifest.model_copy(update={"permissions": permissions})
    reg = Registry()
    reg.register(PluginEntry(entry.id, entry.tool_class, manifest))
    return reg


@pytest.fixture
def system(monkeypatch):
    """Fake uv, schtasks, powercfg and Ollama; tests change `outputs` to set up a case."""
    outputs: dict[tuple[str, ...], str | ToolError] = {
        QUERY: TASKS_CSV,
        XML_QUERY: task_xml(),
        POWER: powercfg(1800),
    }
    calls: list[tuple[str, ...]] = []

    def fake_run(args: list[str]) -> str:
        calls.append(tuple(args))
        result = outputs[tuple(args)]
        if isinstance(result, ToolError):
            raise result
        return result

    http: dict[str, str | OSError] = {"http://localhost:11434/api/version": '{"version": "0.12.0"}'}

    def fake_http_get(url: str, timeout: float) -> str:
        assert timeout == 2
        result = http[url]
        if isinstance(result, OSError):
            raise result
        return result

    monkeypatch.setattr(jobs_doctor, "_run", fake_run)
    monkeypatch.setattr(jobs_doctor, "_http_get", fake_http_get)
    monkeypatch.setattr(jobs, "find_uv", lambda: Path("C:/uv/uv.exe"))
    monkeypatch.setattr(jobs, "find_pwsh", lambda: Path("C:/Program Files/PowerShell/7/pwsh.exe"))
    return {"outputs": outputs, "http": http, "calls": calls}


def by_name(checks: list[jobs_doctor.Check]) -> dict[str, jobs_doctor.Check]:
    return {check.name: check for check in checks}


def no_schtasks() -> ToolError:
    return ToolError("backend_unavailable", "schtasks was not found (Windows only)")


def test_check_names_and_order(jobs_file, registry, system):
    names = [check.name for check in jobs_doctor.run_checks(registry)]
    assert names == ["uv", "pwsh", "jobs_file", "tasks", "logon_mode", "wake", "sleep", "ollama"]


def test_default_machine(jobs_file, registry, system):
    checks = by_name(jobs_doctor.run_checks(registry))
    assert checks["uv"].ok is True
    assert "uv.exe" in checks["uv"].detail
    assert checks["jobs_file"].ok is True
    assert checks["tasks"].ok is True
    assert checks["logon_mode"].ok is None
    assert "logged on" in checks["logon_mode"].detail
    assert checks["logon_mode"].fix
    assert checks["sleep"].ok is None
    assert "30" in checks["sleep"].detail
    assert checks["wake"].ok is False
    assert "hello" in checks["wake"].detail
    assert checks["wake"].fix
    assert checks["ollama"].ok is None


def test_disabled_jobs_are_not_inspected(jobs_file, registry, system):
    jobs_doctor.run_checks(registry)
    assert ("schtasks", "/Query", "/TN", "\\LFMAP\\off", "/XML") not in system["calls"]


def test_all_good(jobs_file, registry, system):
    system["outputs"][XML_QUERY] = task_xml(logon="Password", wake="true")
    checks = jobs_doctor.run_checks(registry)
    assert all(check.ok is not False for check in checks)
    assert by_name(checks)["logon_mode"].ok is True
    assert by_name(checks)["wake"].ok is True


def test_s4u_logon_is_ok(jobs_file, registry, system):
    system["outputs"][XML_QUERY] = task_xml(logon="S4U")
    assert by_name(jobs_doctor.run_checks(registry))["logon_mode"].ok is True


def test_never_sleeping_machine_needs_no_wake(jobs_file, registry, system):
    system["outputs"][POWER] = powercfg(0)
    checks = by_name(jobs_doctor.run_checks(registry))
    assert checks["sleep"].ok is True
    assert checks["wake"].ok is True


def test_sleep_reads_the_ac_value_in_any_language(jobs_file, registry, system):
    localized = powercfg(1800, dc=0).replace("Current AC Power Setting Index", "Aktueller Wechselstromindex")
    system["outputs"][POWER] = localized.replace("Current DC Power Setting Index", "Aktueller Gleichstromindex")
    assert by_name(jobs_doctor.run_checks(registry))["sleep"].ok is None


def test_unreadable_powercfg_is_unknown(jobs_file, registry, system):
    system["outputs"][POWER] = "something unexpected"
    checks = by_name(jobs_doctor.run_checks(registry))
    assert checks["sleep"].ok is None
    assert checks["wake"].ok is not True


def test_missing_uv(jobs_file, registry, system, monkeypatch):
    def missing() -> Path:
        raise ToolError("not_found", "uv was not found; pass --uv")

    monkeypatch.setattr(jobs, "find_uv", missing)
    check = by_name(jobs_doctor.run_checks(registry))["uv"]
    assert check.ok is False
    assert check.fix


def test_invalid_jobs_file(user_dirs, registry, system, monkeypatch):
    path = user_dirs / "jobs.toml"
    path.write_text("[[jobs]]\nid = 'Bad Id'\n", encoding="utf-8")
    monkeypatch.setenv("LFMAP_JOBS", str(path))
    checks = by_name(jobs_doctor.run_checks(registry))
    assert checks["jobs_file"].ok is False
    assert checks["jobs_file"].fix


def test_job_with_unknown_plugin_or_operation(user_dirs, registry, system, monkeypatch):
    path = user_dirs / "jobs.toml"
    path.write_text(
        JOBS_TOML
        + '\n[[jobs]]\nid = "ghost"\nplugin = "nope"\noperation = "x"\nschedule = { daily = "09:00" }\n'
        + '\n[[jobs]]\nid = "typo"\nplugin = "fake-plugin"\noperation = "nope"\nschedule = { daily = "09:00" }\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("LFMAP_JOBS", str(path))
    check = by_name(jobs_doctor.run_checks(registry))["jobs_file"]
    assert check.ok is False
    assert "ghost" in check.detail
    assert "typo" in check.detail


def test_no_jobs_file(user_dirs, registry, system, monkeypatch):
    monkeypatch.setenv("LFMAP_JOBS", str(user_dirs / "missing.toml"))
    system["outputs"][QUERY] = '"\\Microsoft\\Windows\\Other","N/A","Ready"\n'
    checks = by_name(jobs_doctor.run_checks(registry))
    assert checks["jobs_file"].ok is None
    assert checks["tasks"].ok is None
    assert checks["logon_mode"].ok is None
    assert checks["wake"].ok is None


def test_missing_task(jobs_file, registry, system):
    system["outputs"][QUERY] = '"\\Microsoft\\Windows\\Other","N/A","Ready"\n'
    check = by_name(jobs_doctor.run_checks(registry))["tasks"]
    assert check.ok is False
    assert "hello" in check.detail
    assert "jobs register" in check.fix


def test_stale_task(jobs_file, registry, system):
    system["outputs"][QUERY] = TASKS_CSV + '"\\LFMAP\\off","N/A","Ready"\n'
    system["outputs"][("schtasks", "/Query", "/TN", "\\LFMAP\\off", "/XML")] = task_xml()
    check = by_name(jobs_doctor.run_checks(registry))["tasks"]
    assert check.ok is False
    assert "off" in check.detail
    assert "jobs register" in check.fix


def test_without_schtasks_task_checks_are_unknown(jobs_file, registry, system):
    system["outputs"][QUERY] = no_schtasks()
    system["outputs"][XML_QUERY] = no_schtasks()
    checks = by_name(jobs_doctor.run_checks(registry))
    assert checks["tasks"].ok is None
    assert checks["logon_mode"].ok is None
    assert checks["wake"].ok is None


def test_without_powercfg_sleep_is_unknown(jobs_file, registry, system):
    system["outputs"][POWER] = ToolError("backend_unavailable", "powercfg was not found")
    assert by_name(jobs_doctor.run_checks(registry))["sleep"].ok is None


def test_ollama_checked_for_network_plugins(jobs_file, network_registry, system):
    check = by_name(jobs_doctor.run_checks(network_registry))["ollama"]
    assert check.ok is True
    assert "0.12.0" in check.detail


def test_ollama_down(jobs_file, network_registry, system):
    system["http"]["http://localhost:11434/api/version"] = OSError("connection refused")
    check = by_name(jobs_doctor.run_checks(network_registry))["ollama"]
    assert check.ok is False
    assert check.fix


def test_doctor_only_reads(jobs_file, registry, system):
    system["outputs"][XML_QUERY] = task_xml(logon="Password", wake="true")
    jobs_doctor.run_checks(registry)
    for call in system["calls"]:
        assert call[0] in {"schtasks", "powercfg"}
        if call[0] == "schtasks":
            assert call[1] == "/Query"
        else:
            assert call[1] == "/query"


def test_cli_doctor_exit_1_on_false(jobs_file, registry, system):
    result = runner.invoke(build_app(registry), ["jobs", "doctor"])
    assert result.exit_code == 1
    assert "wake" in result.output


def test_cli_doctor_exit_0_without_false(jobs_file, registry, system):
    system["outputs"][XML_QUERY] = task_xml(logon="Password", wake="true")
    result = runner.invoke(build_app(registry), ["jobs", "doctor"])
    assert result.exit_code == 0
    for name in ("uv", "pwsh", "jobs_file", "tasks", "logon_mode", "wake", "sleep", "ollama"):
        assert name in result.output


def test_cli_doctor_json(jobs_file, registry, system):
    result = runner.invoke(build_app(registry), ["jobs", "doctor", "--json"])
    assert result.exit_code == 1
    rows = json.loads(result.output)
    assert [row["name"] for row in rows][:3] == ["uv", "pwsh", "jobs_file"]
    assert set(rows[0]) == {"name", "ok", "detail", "fix"}
    assert {row["name"]: row["ok"] for row in rows}["wake"] is False


def test_pwsh_found(jobs_file, registry, system):
    check = by_name(jobs_doctor.run_checks(registry))["pwsh"]
    assert check.ok is True
    assert "pwsh.exe" in check.detail


def test_task_with_bare_pwsh_fails(jobs_file, registry, system):
    system["outputs"][XML_QUERY] = task_xml(command="pwsh")
    check = by_name(jobs_doctor.run_checks(registry))["pwsh"]
    assert check.ok is False
    assert "hello" in check.detail
    assert "jobs register" in check.fix


def test_task_with_full_pwsh_path_is_ok(jobs_file, registry, system):
    system["outputs"][XML_QUERY] = task_xml(command=r"C:\Users\x\AppData\Local\Microsoft\WindowsApps\pwsh.exe")
    assert by_name(jobs_doctor.run_checks(registry))["pwsh"].ok is True


def test_missing_pwsh(jobs_file, registry, system, monkeypatch):
    def missing() -> Path:
        raise ToolError("not_found", "pwsh was not found; pass --pwsh")

    monkeypatch.setattr(jobs, "find_pwsh", missing)
    check = by_name(jobs_doctor.run_checks(registry))["pwsh"]
    assert check.ok is False
    assert check.fix
