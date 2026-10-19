import json
import os
from pathlib import Path

import pytest
from pydantic import BaseModel
from typer.testing import CliRunner

from lfmap_core import cli
from lfmap_core.approval import audit_path
from lfmap_core.cli import build_app
from lfmap_core.errors import ToolError
from lfmap_core.manifest import Permissions
from lfmap_core.permissions import PermissionManager
from lfmap_core.runtime import build_tool


@pytest.fixture
def dirs(tmp_path):
    data, out, sibling = tmp_path / "data", tmp_path / "out", tmp_path / "data2"
    for folder in (data, out, sibling):
        folder.mkdir()
    return data, out, sibling


def denied(call, *args):
    with pytest.raises(ToolError) as caught:
        call(*args)
    assert caught.value.code == "permission_denied"


def test_explicit_read_is_off_by_default(dirs):
    data, out, sibling = dirs
    perms = PermissionManager([str(data)], [str(out)])
    denied(perms.require_read, str(sibling / "a.txt"))


def test_explicit_read_allows_a_typed_local_path(dirs):
    data, out, sibling = dirs
    seen = []
    perms = PermissionManager([str(data)], [str(out)], explicit_read=True, on_outside_read=seen.append)
    target = sibling / "a.txt"
    assert perms.require_read(str(target)) == Path(os.path.realpath(target))
    assert seen == [os.path.realpath(target)]


def test_explicit_read_inside_roots_is_not_reported(dirs):
    data, out, _ = dirs
    seen = []
    perms = PermissionManager([str(data)], [str(out)], explicit_read=True, on_outside_read=seen.append)
    perms.require_read(str(data / "a.txt"))
    assert seen == []


@pytest.mark.parametrize(
    "path", ["\\\\server\\share\\a.txt", "//server/share/a.txt", "\\\\?\\C:\\a.txt", "\\\\.\\PhysicalDrive0"]
)
def test_explicit_read_still_refuses_network_paths(dirs, path):
    data, out, _ = dirs
    seen = []
    perms = PermissionManager([str(data)], [str(out)], explicit_read=True, on_outside_read=seen.append)
    denied(perms.require_read, path)
    assert seen == []


def test_explicit_read_never_widens_write(dirs):
    data, out, sibling = dirs
    perms = PermissionManager([str(data)], [str(out)], explicit_read=True)
    denied(perms.require_write, str(sibling / "a.txt"))


def test_from_manifest_passes_explicit_read(dirs):
    data, _, sibling = dirs
    declared = Permissions(fs_read=["${input_dir}"], fs_write=[])
    perms = PermissionManager.from_manifest(declared, {"input_dir": str(data)}, explicit_read=True)
    assert perms.require_read(str(sibling / "a.txt")) == Path(os.path.realpath(sibling / "a.txt"))


def test_build_tool_reads_only_roots_by_default(user_dirs, registry):
    tool = build_tool(registry.get("fake-plugin"))
    denied(tool.ctx.permissions.require_read, str(user_dirs / "notes.txt"))


def test_explicit_read_outside_roots_is_audited(user_dirs, registry):
    tool = build_tool(registry.get("fake-plugin"), channel="cli", explicit_read=True)
    target = user_dirs / "notes.txt"
    tool.ctx.permissions.require_read(str(target))
    record = json.loads(audit_path().read_text(encoding="utf-8"))
    assert record["reason"] == "read_outside_roots"
    assert record["channel"] == "cli"
    assert record["plugin"] == "fake-plugin"
    assert record["target"] == os.path.realpath(target)


class _Out(BaseModel):
    message: str


@pytest.mark.parametrize("interactive", [True, False])
def test_cli_passes_channel_and_explicit_read(registry, monkeypatch, interactive):
    seen = {}

    def fake_run(entry, name, payload, **kwargs):
        seen.update(kwargs)
        return _Out(message="ok")

    monkeypatch.setattr(cli, "_interactive", lambda: interactive)
    monkeypatch.setattr(cli, "run_operation", fake_run)
    result = CliRunner().invoke(build_app(registry), ["fake-plugin", "greet", "--name", "A"])
    assert result.exit_code == 0
    assert seen["channel"] == "cli"
    assert seen["explicit_read"] is interactive
