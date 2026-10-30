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


def task_xml(
    logon: str = "InteractiveToken", wake: str = "false", command: str | None = None, root: Path | None = None
) -> str:
    executable = f"<Command>{command}</Command>" if command else ""
    arguments = f"-NoProfile -File &quot;x.ps1&quot; -JobId hello -RepoPath &quot;{root or jobs.repo_root()}&quot;"
    action = f"\n  <Actions><Exec>{executable}<Arguments>{arguments}</Arguments></Exec></Actions>"
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


USER_SID = "S-1-5-21-3501978580-2174309771-332471541-1001"
AGENT_SID = "S-1-5-21-3501978580-2174309771-332471541-1002"
# Recorded with `icacls <folder> /save` on pc-01 (second line of the file).
DEV_TREE_SDDL = (
    "D:(A;ID;FA;;;BA)(A;OICIIOID;GA;;;BA)(A;ID;FA;;;SY)(A;OICIIOID;GA;;;SY)(A;ID;0x1301bf;;;AU)"
    "(A;OICIIOID;SDGXGWGR;;;AU)(A;ID;0x1200a9;;;BU)(A;OICIIOID;GXGR;;;BU)"
)
PROFILE_SDDL = f"D:(A;OICIID;FA;;;SY)(A;OICIID;FA;;;BA)(A;OICIID;FA;;;{USER_SID})"
DRIVE_SDDL = (
    "D:(A;;FA;;;BA)(A;OICIIO;GA;;;BA)(A;;FA;;;SY)(A;OICIIO;GA;;;SY)(A;;0x1301bf;;;AU)"
    "(A;OICIIO;SDGXGWGR;;;AU)(A;;0x1200a9;;;BU)(A;OICIIO;GXGR;;;BU)"
)
# What Setup-LfmapAgent.ps1 aims for: inheritance off, the agent may read and execute only.
RUNTIME_SDDL = f"D:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FA;;;{USER_SID})(A;OICI;0x1200a9;;;{AGENT_SID})"


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
    acl: dict = {"sddl": RUNTIME_SDDL, "sid": USER_SID, "by_path": {}}

    def fake_read_acl(folder: Path) -> str:
        acl.setdefault("root", str(folder))
        result = acl["by_path"].get(str(folder), acl["sddl"])
        if isinstance(result, ToolError):
            raise result
        return result

    monkeypatch.setattr(jobs_doctor, "_read_acl", fake_read_acl)
    monkeypatch.setattr(jobs_doctor, "_current_sid", lambda: acl["sid"])
    return {"outputs": outputs, "http": http, "calls": calls, "acl": acl}


def by_name(checks: list[jobs_doctor.Check]) -> dict[str, jobs_doctor.Check]:
    return {check.name: check for check in checks}


def no_schtasks() -> ToolError:
    return ToolError("backend_unavailable", "schtasks was not found (Windows only)")


def test_check_names_and_order(jobs_file, registry, system):
    names = [check.name for check in jobs_doctor.run_checks(registry)]
    assert names == [
        "uv", "pwsh", "jobs_file", "tasks", "logon_mode", "wake", "sleep", "ollama", "runtime_root", "runtime_acl"
    ]  # fmt: skip


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
    for name in ("uv", "pwsh", "jobs_file", "tasks", "logon_mode", "wake", "sleep", "ollama", "runtime_acl"):
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


def runtime_tree(tmp_path: Path) -> Path:
    root = tmp_path / "lfmap-runtime"
    (root / "scripts").mkdir(parents=True)
    (root / "scripts" / "Invoke-LfmapJob.ps1").write_text("# runner\n", encoding="utf-8")
    return root


def use_runtime(jobs_file: Path, root: Path) -> None:
    jobs_file.write_text(f"[runtime]\nroot = '{root}'\n" + JOBS_TOML, encoding="utf-8")


def test_runtime_defaults_to_this_checkout(jobs_file, registry, system):
    checks = by_name(jobs_doctor.run_checks(registry))
    assert checks["runtime_root"].ok is True
    assert checks["runtime_root"].detail == str(jobs.repo_root())
    assert system["acl"]["root"] == str(jobs.repo_root())


def test_runtime_root_from_jobs_toml(jobs_file, registry, system, tmp_path):
    root = runtime_tree(tmp_path)
    use_runtime(jobs_file, root)
    system["outputs"][XML_QUERY] = task_xml(root=root)
    checks = by_name(jobs_doctor.run_checks(registry))
    assert checks["runtime_root"].ok is True
    assert checks["runtime_acl"].ok is True
    assert system["acl"]["root"] == str(root)


def test_task_running_from_another_tree_warns(jobs_file, registry, system, tmp_path):
    use_runtime(jobs_file, runtime_tree(tmp_path))
    check = by_name(jobs_doctor.run_checks(registry))["runtime_root"]
    assert check.ok is None
    assert "hello" in check.detail
    assert "jobs register" in check.fix


def test_runtime_root_without_runner_fails(jobs_file, registry, system, tmp_path):
    use_runtime(jobs_file, tmp_path / "empty")
    checks = by_name(jobs_doctor.run_checks(registry))
    assert checks["runtime_root"].ok is False
    assert checks["runtime_root"].fix
    assert checks["runtime_acl"].ok is None
    assert "root" not in system["acl"]


def test_runtime_unknown_when_jobs_file_is_invalid(user_dirs, registry, system, monkeypatch):
    path = user_dirs / "jobs.toml"
    path.write_text("[runtime]\nroot = 'relative'\n", encoding="utf-8")
    monkeypatch.setenv("LFMAP_JOBS", str(path))
    checks = by_name(jobs_doctor.run_checks(registry))
    assert checks["runtime_root"].ok is None
    assert checks["runtime_acl"].ok is None


def test_runtime_writable_by_others_warns(jobs_file, registry, system):
    system["acl"]["sddl"] = DEV_TREE_SDDL
    check = by_name(jobs_doctor.run_checks(registry))["runtime_acl"]
    assert check.ok is None
    assert "Authenticated Users (S-1-5-11)" in check.detail
    assert "[runtime] root" in check.fix


def test_parent_that_others_can_move_warns(jobs_file, registry, system, tmp_path):
    root = runtime_tree(tmp_path)
    use_runtime(jobs_file, root)
    system["acl"]["by_path"][str(root.parent)] = DEV_TREE_SDDL
    check = by_name(jobs_doctor.run_checks(registry))["runtime_acl"]
    assert check.ok is None
    assert f"{root.parent} (can move what is below): Authenticated Users (S-1-5-11)" in check.detail
    assert f"{root}:" not in check.detail


def test_every_parent_is_read(jobs_file, registry, system, tmp_path, monkeypatch):
    root = runtime_tree(tmp_path)
    use_runtime(jobs_file, root)
    read = []
    fake = jobs_doctor._read_acl
    monkeypatch.setattr(jobs_doctor, "_read_acl", lambda folder: read.append(folder) or fake(folder))
    jobs_doctor.run_checks(registry)
    assert read == [root, *root.parents]


@pytest.mark.parametrize(
    ("sddl", "mask", "expected"),
    [
        (DRIVE_SDDL, jobs_doctor._DRIVE_MOVE_MASK, []),
        (DRIVE_SDDL, jobs_doctor._MOVE_MASK, ["Authenticated Users (S-1-5-11)"]),
        (DEV_TREE_SDDL, jobs_doctor._MOVE_MASK, ["Authenticated Users (S-1-5-11)"]),
        ("D:(A;OICIIO;GA;;;AU)(A;;0x1200a9;;;BU)", jobs_doctor._MOVE_MASK, []),
        (f"D:(A;;DT;;;{AGENT_SID})", jobs_doctor._DRIVE_MOVE_MASK, [AGENT_SID]),
        (f"D:(A;;WD;;;{AGENT_SID})", jobs_doctor._DRIVE_MOVE_MASK, [AGENT_SID]),
    ],
)
def test_who_can_move_a_parent(sddl, mask, expected):
    assert jobs_doctor.other_writers(sddl, USER_SID, mask, own_only=True) == expected


def test_unreadable_acl_is_unknown(jobs_file, registry, system):
    system["acl"]["sddl"] = ToolError("backend_unavailable", "icacls.exe was not found (Windows only)")
    check = by_name(jobs_doctor.run_checks(registry))["runtime_acl"]
    assert check.ok is None
    assert "icacls" in check.detail


@pytest.mark.parametrize(
    ("sddl", "expected"),
    [
        (DEV_TREE_SDDL, ["Authenticated Users (S-1-5-11)"]),
        (PROFILE_SDDL, []),
        (RUNTIME_SDDL, []),
        (f"D:PAI(A;OICI;FA;;;SY)(A;OICI;0x1301bf;;;{AGENT_SID})", [AGENT_SID]),
        (f"D:(A;OICI;FA;;;{AGENT_SID})", [AGENT_SID]),
        ("D:(A;OICIIO;GW;;;WD)", ["Everyone (S-1-1-0)"]),
        ("D:(A;;WD;;;BU)", ["Users (S-1-5-32-545)"]),
        ("D:(A;;SD;;;BU)", ["Users (S-1-5-32-545)"]),
        ("D:(A;;DCLC;;;BU)", ["Users (S-1-5-32-545)"]),
        ("D:(A;;FRFX;;;BU)(A;;0x1200a9;;;AU)(A;OICIIO;GXGR;;;BU)", []),
        (f"D:(D;OICI;FA;;;{AGENT_SID})(A;OICIIO;GA;;;CO)(A;OICI;FA;;;S-1-5-32-544)", []),
        ("D:(A;;ZZ;;;BU)", ["Users (S-1-5-32-545)"]),
        (f'D:(XA;;FA;;;{AGENT_SID};(@User.Project == "x"))', [AGENT_SID]),
        (f"D:(A;;FA;;;{USER_SID})", []),
    ],
)
def test_other_writers(sddl, expected):
    assert jobs_doctor.other_writers(sddl, USER_SID) == expected


@pytest.mark.parametrize("sddl", ["D:(A;;FA;;;BU", "D:(A;;FA)"])
def test_unreadable_sddl(sddl):
    with pytest.raises(ToolError):
        jobs_doctor.other_writers(sddl, USER_SID)


def test_read_acl_runs_icacls_from_system32(monkeypatch, tmp_path):
    seen = []

    def fake_run(args: list[str]) -> str:
        seen.append(args)
        Path(args[3]).write_bytes(f"lfmap-runtime\r\n{RUNTIME_SDDL}\r\n".encode("utf-16-le"))
        return "processed file"

    monkeypatch.setenv("SystemRoot", r"C:\Windows")
    monkeypatch.setattr(jobs_doctor, "_run", fake_run)
    assert jobs_doctor._read_acl(tmp_path) == RUNTIME_SDDL
    assert seen[0][0] == r"C:\Windows\System32\icacls.exe"
    assert seen[0][1:3] == [str(tmp_path), "/save"]
    assert not Path(seen[0][3]).exists()


def test_read_acl_without_dacl(monkeypatch, tmp_path):
    def fake_run(args: list[str]) -> str:
        Path(args[3]).write_bytes("lfmap-runtime\r\n".encode("utf-16-le"))
        return ""

    monkeypatch.setattr(jobs_doctor, "_run", fake_run)
    with pytest.raises(ToolError):
        jobs_doctor._read_acl(tmp_path)


def test_current_sid_from_whoami(monkeypatch):
    seen = []

    def fake_run(args: list[str]) -> str:
        seen.append(args)
        return f'"diep-anh\\hungnp","{USER_SID}"\r\n'

    monkeypatch.setenv("SystemRoot", r"C:\Windows")
    monkeypatch.setattr(jobs_doctor, "_run", fake_run)
    assert jobs_doctor._current_sid() == USER_SID
    assert seen == [[r"C:\Windows\System32\whoami.exe", "/user", "/fo", "csv", "/nh"]]


def test_current_sid_missing(monkeypatch):
    monkeypatch.setattr(jobs_doctor, "_run", lambda args: "nothing")
    with pytest.raises(ToolError):
        jobs_doctor._current_sid()
