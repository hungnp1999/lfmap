"""ADR-020: per-script approval tiers for powershell.run."""

import json
from pathlib import Path

import pytest

import lfmap_powershell
from lfmap_core import ToolContext, invoke
from lfmap_core.manifest import load_manifest
from lfmap_core.permissions import PermissionManager
from lfmap_core.registry import PluginEntry
from lfmap_core.runtime import call_tier
from lfmap_powershell import runner
from lfmap_powershell.allowlist import load_allowlist, sha256_hex
from lfmap_powershell.runner import ProcessResult
from lfmap_powershell.tool import PowerShellTool

SCRIPT = b"Write-Output ok\n"


def _entry(**extra) -> dict:
    return {"path": "C:/scripts/a.ps1", "sha256": "a" * 64, **extra}


@pytest.fixture
def plugin() -> PluginEntry:
    manifest = load_manifest(Path(lfmap_powershell.__file__).parent / "lfmap.toml")
    return PluginEntry("powershell", PowerShellTool, manifest)


def _config(**scripts: dict) -> dict:
    return {"plugins": {"powershell": {"settings": {"scripts": scripts}}}}


def test_manifest_lets_run_go_down_to_t1_only():
    manifest = load_manifest(Path(lfmap_powershell.__file__).parent / "lfmap.toml")
    assert manifest.operation("run").min_tier == "T1"
    assert manifest.operation("list").min_tier is None


def test_tier_defaults_to_t3():
    entries, _ = load_allowlist({"scripts": {"disk": _entry()}})
    assert entries["disk"].tier == "T3"


@pytest.mark.parametrize("tier", ["T0", "T4", "t1", 1])
def test_tier_outside_t1_to_t3_is_an_invalid_entry(tier):
    entries, problems = load_allowlist({"scripts": {"disk": _entry(tier=tier)}})
    assert "disk" not in entries
    assert problems["disk"].startswith("invalid entry")


@pytest.mark.parametrize(
    ("script", "expected"),
    [("low", "T1"), ("mid", "T2"), ("default", "T3"), ("broken", "T3"), ("unknown", "T3")],
)
def test_run_is_gated_on_the_script_tier(plugin, script, expected):
    config = _config(low=_entry(tier="T1"), mid=_entry(tier="T2"), default=_entry(), broken={"path": "x", "tier": "T1"})
    assert call_tier(plugin, "run", {"script": script, "params": {}}, config) == expected


def test_list_is_always_t0(plugin):
    assert call_tier(plugin, "list", {}, _config(low=_entry(tier="T1"))) == "T0"


def test_list_shows_the_tier_and_audit_records_it(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "a.ps1").write_bytes(SCRIPT)
    pwsh = tmp_path / "pwsh.exe"
    pwsh.write_bytes(b"")
    settings = {
        "pwsh": str(pwsh),
        "scripts": {"low": {"path": str(scripts / "a.ps1"), "sha256": sha256_hex(SCRIPT), "tier": "T1"}},
    }
    monkeypatch.setattr(runner, "run_process", lambda *args: ProcessResult(0, "ok\n", "", False, False, False, 5))
    ctx = ToolContext(
        plugin_id="powershell",
        permissions=PermissionManager([str(scripts.resolve())], []),
        settings=settings,
        temp_dir=tmp_path / "temp",
        channel="mcp",
    )
    tool = PowerShellTool(ctx)
    assert invoke(tool, "list", {}).scripts[0].tier == "T1"
    invoke(tool, "run", {"script": "low"})
    (line,) = (tmp_path / "appdata" / "lfmap" / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(line)["tier"] == "T1"
