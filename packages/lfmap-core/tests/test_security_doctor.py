import json
import subprocess
import sys

import pytest
from typer.testing import CliRunner

from lfmap_core import jobs_doctor, security_doctor
from lfmap_core.cli import build_app

PROFILE = r"C:\Users\me"
POWERSHELL = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"


def sample(realtime=True, cfa=1, protected=None) -> str:
    preference = {"EnableControlledFolderAccess": cfa, "ControlledFolderAccessProtectedFolders": protected}
    return json.dumps({"Status": {"RealTimeProtectionEnabled": realtime}, "Preference": preference})


def checks(text: str, folders=(), **extra):
    result = security_doctor.run_checks(
        runner=lambda command: text, folders=list(folders), profile=PROFILE, platform="win32", **extra
    )
    assert result is not None
    return {check.name: check for check in result}


def test_defender_on_is_ok() -> None:
    found = checks(sample(realtime=True))["defender_realtime"]
    assert found.ok is True


def test_defender_off_warns_not_fails() -> None:
    found = checks(sample(realtime=False))["defender_realtime"]
    assert found.ok is None
    assert "another antivirus" in found.detail
    assert "Manage settings" in found.fix


def test_cfa_off_warns() -> None:
    found = checks(sample(cfa=0))["cfa_enabled"]
    assert found.ok is None
    assert "off" in found.detail
    assert "0" in found.detail


def test_cfa_audit_warns() -> None:
    found = checks(sample(cfa=2))["cfa_enabled"]
    assert found.ok is None
    assert "audit" in found.detail


def test_cfa_on_covers_declared_folders() -> None:
    result = checks(sample(cfa=1, protected=[r"D:\Work"]), folders=[r"D:\Work\notes", r"C:\Users\me\Documents"])
    assert result["cfa_enabled"].ok is True
    assert result["cfa_covers"].ok is True


def test_cfa_on_reports_uncovered_folder() -> None:
    result = checks(sample(cfa=1, protected=[r"D:\Work"]), folders=[r"D:\Work", r"E:\Backups"])
    assert result["cfa_covers"].ok is None
    assert r"E:\Backups" in result["cfa_covers"].detail
    assert r"D:\Work" not in result["cfa_covers"].detail
    assert "Protected folders" in result["cfa_covers"].fix


def test_default_protected_folders_count() -> None:
    found = security_doctor.default_protected(PROFILE)
    assert len(found) == 6
    assert r"C:\Users\me\Documents" in found
    assert r"C:\Users\me\Desktop" in found


def test_sibling_prefix_is_not_covered() -> None:
    assert not security_doctor.covered(r"C:\Docs2", [r"C:\Doc"])
    assert security_doctor.covered(r"C:\Doc\sub", [r"C:\Doc"])
    assert security_doctor.covered(r"C:\Doc", [r"C:\Doc"])


def test_case_and_slash_insensitive() -> None:
    assert security_doctor.covered("c:/doc/Sub/", [r"C:\DOC"])
    assert not security_doctor.covered(r"C:\Doc\..\Other", [r"C:\Doc"])


def test_missing_backup_and_paths_skipped() -> None:
    assert security_doctor.declared_folders({}, r"C:\App") == [r"C:\App"]
    config = {"paths": {"documents": [r"D:\Docs"], "exports": r"D:\Out", "bad": 5}, "backup": {"folder": r"E:\B"}}
    assert security_doctor.declared_folders(config, r"C:\App") == [r"D:\Docs", r"D:\Out", r"E:\B", r"C:\App"]
    assert security_doctor.declared_folders({"backup": {"folder": 7}}, r"C:\App") == [r"C:\App"]


def test_powershell_missing_is_warn_unknown() -> None:
    def missing(command):
        raise FileNotFoundError("powershell.exe")

    result = security_doctor.run_checks(runner=missing, folders=[], profile=PROFILE, platform="win32")
    assert [check.name for check in result] == ["defender_realtime", "cfa_enabled", "cfa_covers"]
    assert all(check.ok is None for check in result)
    assert "powershell.exe" in result[0].detail


def test_bad_json_is_warn_unknown() -> None:
    result = checks("not json {")
    assert all(check.ok is None for check in result.values())
    assert "unknown" in result["defender_realtime"].detail


def test_non_windows_skipped() -> None:
    def never(command):
        raise AssertionError("must not run")

    assert security_doctor.run_checks(runner=never, platform="linux") is None


def test_script_is_constant_and_absolute_path(monkeypatch) -> None:
    monkeypatch.setenv("SystemRoot", r"C:\Windows")
    seen = []
    folders = [r"D:\Secret Folder"]
    security_doctor.run_checks(
        runner=lambda command: seen.append(command) or sample(), folders=folders, profile=PROFILE, platform="win32"
    )
    assert seen == [[POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", security_doctor.SCRIPT]]
    assert "Secret" not in " ".join(seen[0]) and "Users" not in security_doctor.SCRIPT
    assert not any(verb in security_doctor.SCRIPT for verb in ("Set-", "Add-", "Remove-", "New-", "Invoke-"))
    assert "Get-MpComputerStatus" in security_doctor.SCRIPT and "Get-MpPreference" in security_doctor.SCRIPT


def test_runner_uses_timeout(monkeypatch) -> None:
    seen = {}

    def fake(command, **kwargs):
        seen.update(kwargs)
        return subprocess.CompletedProcess(command, 0, stdout="{}", stderr="")

    monkeypatch.setattr(subprocess, "run", fake)
    assert security_doctor._run_powershell(["x"]) == "{}"
    assert seen["timeout"] == security_doctor.TIMEOUT_SECONDS == 20


@pytest.fixture
def doctor_app(registry, tmp_path, monkeypatch):
    monkeypatch.setattr(jobs_doctor, "run_checks", lambda registry, path=None: [jobs_doctor.Check("uv", True, "ok")])
    flows_file = tmp_path / "flows.toml"
    flows_file.write_text("", encoding="utf-8")
    monkeypatch.setenv("LFMAP_FLOWS", str(flows_file))
    return build_app(registry)


def test_doctor_exit_code_unchanged_by_security_warns(doctor_app, monkeypatch) -> None:
    warns = [jobs_doctor.Check("defender_realtime", None, "off", "fix it")]
    monkeypatch.setattr(security_doctor, "run_checks", lambda: warns)
    result = CliRunner().invoke(doctor_app, ["doctor"])
    assert result.exit_code == 0, result.output
    assert "security" in result.output and "defender_realtime" in result.output and "warn" in result.output


def test_doctor_json_has_security_group(doctor_app, monkeypatch) -> None:
    warns = [jobs_doctor.Check("cfa_enabled", None, "off (0)", "turn on")]
    monkeypatch.setattr(security_doctor, "run_checks", lambda: warns)
    report = json.loads(CliRunner().invoke(doctor_app, ["doctor", "--json"]).output)
    assert report["ok"] is True
    assert report["security"] == [{"name": "cfa_enabled", "ok": None, "detail": "off (0)", "fix": "turn on"}]
    monkeypatch.setattr(security_doctor, "run_checks", lambda: None)
    report = json.loads(CliRunner().invoke(doctor_app, ["doctor", "--json"]).output)
    assert report["security"] == {"skipped": "Windows only"}


def test_real_platform_is_skipped_off_windows() -> None:
    if sys.platform == "win32":
        pytest.skip("Windows")
    assert security_doctor.run_checks() is None
