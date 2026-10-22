import json
import os
import shutil
from pathlib import Path

import pytest

import lfmap_powershell
from lfmap_core import ToolContext, ToolError, invoke
from lfmap_core.manifest import load_manifest
from lfmap_core.permissions import PermissionManager
from lfmap_powershell import runner, tool
from lfmap_powershell.allowlist import sha256_hex
from lfmap_powershell.runner import ProcessResult
from lfmap_powershell.tool import PowerShellTool, pwsh_path

SCRIPT = b'param([string]$Drive)\nWrite-Output "drive $Drive"\n'


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "report.ps1").write_bytes(SCRIPT)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "evil.ps1").write_bytes(SCRIPT)
    pwsh = tmp_path / "bin" / "pwsh.exe"
    pwsh.parent.mkdir()
    pwsh.write_bytes(b"")
    temp = tmp_path / "temp"
    temp.mkdir()
    return {"tmp": tmp_path, "scripts": scripts, "outside": outside, "pwsh": str(pwsh), "temp": temp}


def _settings(env, **scripts) -> dict:
    base = {
        "report": {
            "path": str(env["scripts"] / "report.ps1"),
            "sha256": sha256_hex(SCRIPT),
            "description": "Drive report",
            "timeout_s": 30,
            "params": {"Drive": {"pattern": "[A-Z]", "required": True}},
        }
    }
    return {"pwsh": env["pwsh"], "scripts": {**base, **scripts}}


def _tool(env, settings=None, dry_run=False) -> PowerShellTool:
    perms = PermissionManager([os.path.realpath(env["scripts"])], [])
    ctx = ToolContext(
        plugin_id="powershell",
        permissions=perms,
        settings=_settings(env) if settings is None else settings,
        temp_dir=env["temp"],
        channel="mcp",
        dry_run=dry_run,
    )
    return PowerShellTool(ctx)


class Calls(list):
    """What the fake runner saw; `result` is what it returns next."""

    result = ProcessResult(0, "drive C\n", "", False, False, False, 12)


@pytest.fixture
def calls(monkeypatch):
    seen = Calls()

    def fake(argv, cwd, timeout_s, max_chars):
        copy = Path(argv[5])
        seen.append(
            {
                "argv": argv,
                "cwd": cwd,
                "timeout_s": timeout_s,
                "max_chars": max_chars,
                "copy": copy,
                "bytes": copy.read_bytes(),
            }
        )
        return seen.result

    monkeypatch.setattr(runner, "run_process", fake)
    return seen


def _audit_lines(env) -> list[dict]:
    path = env["tmp"] / "appdata" / "lfmap" / "audit.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_manifest_declares_run_external_and_list_none():
    manifest = load_manifest(Path(lfmap_powershell.__file__).parent / "lfmap.toml")
    assert manifest.plugin.id == "powershell"
    assert manifest.operation("run").side_effects == "external"
    assert manifest.operation("list").side_effects == "none"
    assert manifest.permissions.fs_read == ["${scripts}"]
    assert manifest.permissions.fs_write == []
    assert manifest.permissions.exec == ["pwsh"]
    assert not manifest.permissions.network
    assert set(PowerShellTool.operations()) == {"list", "run"}


def test_list_reports_ready_and_problem_scripts(env):
    settings = _settings(
        env,
        changed={"path": str(env["scripts"] / "report.ps1"), "sha256": "0" * 64},
        outside={"path": str(env["outside"] / "evil.ps1"), "sha256": sha256_hex(SCRIPT)},
        missing={"path": str(env["scripts"] / "gone.ps1"), "sha256": sha256_hex(SCRIPT)},
        broken={"path": str(env["scripts"] / "report.ps1")},
    )
    out = invoke(_tool(env, settings), "list", {})
    by_id = {s.id: s for s in out.scripts}
    assert [s.id for s in out.scripts] == sorted(by_id)
    assert by_id["report"].ready and by_id["report"].problem == ""
    assert by_id["report"].description == "Drive report"
    assert by_id["report"].timeout_s == 30
    assert [(p.name, p.type, p.required, p.pattern) for p in by_id["report"].params] == [
        ("Drive", "string", True, "[A-Z]")
    ]
    for script_id in ("changed", "outside", "missing", "broken"):
        assert not by_id[script_id].ready
        assert by_id[script_id].problem
    assert "sha256" in by_id["changed"].problem
    assert by_id["broken"].problem.startswith("invalid entry")


def test_list_works_without_pwsh(env, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    settings = _settings(env)
    del settings["pwsh"]
    assert invoke(_tool(env, settings), "list", {}).scripts[0].ready


def test_run_executes_a_copy_of_the_hashed_bytes(env, calls):
    out = invoke(_tool(env), "run", {"script": "report", "params": {"Drive": "C"}})
    (call,) = calls
    script = os.path.realpath(env["scripts"] / "report.ps1")
    assert call["argv"][:5] == [env["pwsh"], "-NoProfile", "-NonInteractive", "-NoLogo", "-File"]
    assert call["argv"][6:] == ["-Drive", "C"]
    assert call["copy"] != Path(script)
    assert os.path.realpath(call["copy"]).startswith(os.path.realpath(env["temp"]))
    assert call["bytes"] == SCRIPT
    assert not call["copy"].exists()
    assert os.path.realpath(call["cwd"]) == os.path.realpath(env["scripts"])
    assert call["timeout_s"] == 30
    assert call["max_chars"] == 20_000
    assert out.command == [env["pwsh"], "-NoProfile", "-NonInteractive", "-NoLogo", "-File", script, "-Drive", "C"]
    assert out.exit_code == 0
    assert out.stdout == "drive C\n"
    assert out.duration_ms == 12
    assert not out.dry_run
    assert out.untrusted and out.notice


def test_run_is_audited_with_script_id_and_exit_code(env, calls):
    invoke(_tool(env), "run", {"script": "report", "params": {"Drive": "C"}})
    calls.result = ProcessResult(None, "", "", False, False, True, 30_000)
    out = invoke(_tool(env), "run", {"script": "report", "params": {"Drive": "D"}})
    assert out.timed_out and out.exit_code is None
    lines = _audit_lines(env)
    assert [(r["plugin"], r["operation"], r["tier"], r["target"], r["reason"]) for r in lines] == [
        ("powershell", "run", "T3", "report", "exit 0"),
        ("powershell", "run", "T3", "report", "timeout"),
    ]
    assert all(r["channel"] == "mcp" for r in lines)
    assert "drive" not in json.dumps(lines)


def test_dry_run_starts_nothing_and_audits_nothing(env, calls):
    out = invoke(_tool(env, dry_run=True), "run", {"script": "report", "params": {"Drive": "C"}})
    assert out.dry_run
    assert out.command[-2:] == ["-Drive", "C"]
    assert out.exit_code is None
    assert calls == []
    assert _audit_lines(env) == []


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ({"script": "nope"}, "not_found"),
        ({"script": "Bad Id"}, "invalid_input"),
        ({"script": "report"}, "invalid_input"),
        ({"script": "report", "params": {"Drive": "-C"}}, "invalid_input"),
        ({"script": "report", "params": {"Drive": "C", "Extra": "x"}}, "invalid_input"),
    ],
)
def test_bad_requests_start_nothing(env, calls, payload, code):
    with pytest.raises(ToolError) as error:
        invoke(_tool(env), "run", payload)
    assert error.value.code == code
    assert calls == []


def test_invalid_entry_is_invalid_input(env, calls):
    settings = _settings(env, broken={"path": "x"})
    with pytest.raises(ToolError) as error:
        invoke(_tool(env, settings), "run", {"script": "broken"})
    assert error.value.code == "invalid_input"
    assert calls == []


def test_changed_script_is_refused(env, calls):
    (env["scripts"] / "report.ps1").write_bytes(SCRIPT + b"Remove-Item C:\\ -Recurse\n")
    with pytest.raises(ToolError) as error:
        invoke(_tool(env), "run", {"script": "report", "params": {"Drive": "C"}})
    assert error.value.code == "permission_denied"
    assert error.value.details["expected"] == sha256_hex(SCRIPT)
    assert calls == []


def test_script_outside_the_scripts_folder_is_refused(env, calls):
    settings = _settings(env, evil={"path": str(env["outside"] / "evil.ps1"), "sha256": sha256_hex(SCRIPT)})
    with pytest.raises(ToolError) as error:
        invoke(_tool(env, settings), "run", {"script": "evil"})
    assert error.value.code == "permission_denied"
    assert calls == []


def test_unc_script_path_is_refused_before_io(env, calls):
    settings = _settings(env, unc={"path": "\\\\server\\share\\a.ps1", "sha256": sha256_hex(SCRIPT)})
    with pytest.raises(ToolError) as error:
        invoke(_tool(env, settings), "run", {"script": "unc"})
    assert error.value.code == "permission_denied"
    assert calls == []


@pytest.mark.parametrize("value", ["pwsh.exe", "\\\\server\\share\\pwsh.exe", "//server/share/pwsh.exe", 5])
def test_pwsh_setting_must_be_absolute_and_local(value):
    with pytest.raises(ToolError) as error:
        pwsh_path({"pwsh": value})
    assert error.value.code == "invalid_input"


def test_pwsh_setting_must_exist(tmp_path):
    with pytest.raises(ToolError) as error:
        pwsh_path({"pwsh": str(tmp_path / "pwsh.exe")})
    assert error.value.code == "invalid_input"


def test_pwsh_falls_back_to_path(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/pwsh" if name == "pwsh" else None)
    assert pwsh_path({}) == "/usr/bin/pwsh"
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(ToolError) as error:
        pwsh_path({})
    assert error.value.code == "backend_unavailable"


def test_health_reports_missing_pwsh(env, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert _tool(env, {"scripts": {}}).health()["ok"] is False
    assert _tool(env).health() == {"ok": True, "pwsh": env["pwsh"]}


def test_tool_module_uses_runner_module_attribute():
    # Tests replace runner.run_process; the tool must look it up at call time.
    assert tool.runner is runner


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell 7 is not installed")
def test_real_pwsh_runs_script_with_params(env):
    script = b"param([string]$Drive, [int]$Days, [switch]$Loud)\n" + (
        b"[Console]::OutputEncoding = [Text.Encoding]::UTF8\n"
        b'Write-Output "$Drive|$Days|$Loud|$(Split-Path -Leaf (Get-Location))|b\xc3\xa1o c\xc3\xa1o"\n'
        b"exit 4\n"
    )
    (env["scripts"] / "real.ps1").write_bytes(script)
    settings = {
        "scripts": {
            "real": {
                "path": str(env["scripts"] / "real.ps1"),
                "sha256": sha256_hex(script),
                "params": {"Drive": {}, "Days": {"type": "int"}, "Loud": {"type": "switch"}},
            }
        }
    }
    out = invoke(
        _tool(env, settings), "run", {"script": "real", "params": {"Drive": "C:\\a b", "Days": 3, "Loud": True}}
    )
    assert out.exit_code == 4, out.stderr
    assert out.stdout.strip() == "C:\\a b|3|True|scripts|báo cáo"


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell 7 is not installed")
def test_real_pwsh_treats_values_as_literal_text(env):
    script = b'param([string]$Text)\nWrite-Output "[$Text]"\n'
    (env["scripts"] / "echo.ps1").write_bytes(script)
    settings = {
        "scripts": {
            "echo": {"path": str(env["scripts"] / "echo.ps1"), "sha256": sha256_hex(script), "params": {"Text": {}}}
        }
    }
    value = "x; Write-Output pwned $(Get-Date) & whoami | calc '"
    out = invoke(_tool(env, settings), "run", {"script": "echo", "params": {"Text": value}})
    assert out.exit_code == 0, out.stderr
    assert out.stdout.strip() == f"[{value}]"
