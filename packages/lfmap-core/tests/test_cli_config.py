import json
import os

import pytest
from typer.testing import CliRunner

from lfmap_core import cli
from lfmap_core.approval import audit, audit_path
from lfmap_core.cli import build_app
from lfmap_core.config import add_folder, load_config
from lfmap_core.errors import ToolError


def run(registry, *args):
    return CliRunner().invoke(build_app(registry), list(args))


def test_plugins_health(registry):
    result = run(registry, "plugins", "health", "--json")
    assert result.exit_code == 0
    assert json.loads(result.output) == [{"id": "fake-plugin", "ok": True}]


def test_config_path(user_dirs, registry):
    result = run(registry, "config", "path", "--json")
    data = json.loads(result.output)
    assert data["config"] == str(user_dirs / "config.toml")
    assert data["plugins"] == [{"id": "fake-plugin", "read": [], "write": []}]


def test_add_folder_needs_a_terminal(user_dirs, registry, tmp_path):
    result = run(registry, "config", "add-folder", str(tmp_path), "--as", "documents")
    assert result.exception.code == "permission_denied"
    assert not (user_dirs / "config.toml").exists()


def test_add_folder_keeps_comments(user_dirs, registry, monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    docs, scans = tmp_path / "Tài liệu", tmp_path / "scans"
    docs.mkdir()
    scans.mkdir()
    config = user_dirs / "config.toml"
    config.write_text('# my settings\n[paths]\nexports = []\n\n[plugins.x.settings]\nk = "v"\n', encoding="utf-8")
    assert run(registry, "config", "add-folder", str(docs), "--as", "documents").exit_code == 0
    assert run(registry, "config", "add-folder", str(scans), "--as", "documents").exit_code == 0
    assert run(registry, "config", "add-folder", str(docs), "--as", "documents").exit_code == 0
    text = config.read_text(encoding="utf-8")
    assert text.startswith("# my settings\n")
    loaded = load_config(config)
    assert loaded["paths"]["documents"] == [os.path.realpath(docs), os.path.realpath(scans)]
    assert loaded["plugins"]["x"]["settings"] == {"k": "v"}
    assert [json.loads(line)["decision"] for line in audit_path().read_text(encoding="utf-8").splitlines()] == [
        "grant",
        "grant",
        "grant",
    ]


def test_add_folder_creates_the_file(user_dirs, tmp_path):
    root = add_folder("exports", str(tmp_path))
    assert load_config(user_dirs / "config.toml") == {"paths": {"exports": [root]}}


@pytest.mark.parametrize(
    ("name", "folder", "code"),
    [
        ("documents", "\\\\server\\share", "permission_denied"),
        ("documents", "//server/share", "permission_denied"),
        ("documents", "relative/folder", "invalid_input"),
        ("secrets", None, "invalid_input"),
        ("documents", "missing", "invalid_input"),
    ],
)
def test_add_folder_refuses(user_dirs, tmp_path, name, folder, code):
    if folder in (None, "missing"):
        folder = str(tmp_path / "missing") if folder else str(tmp_path)
    with pytest.raises(ToolError) as excinfo:
        add_folder(name, folder)
    assert excinfo.value.code == code
    assert not (user_dirs / "config.toml").exists()


def test_audit_tail(user_dirs, registry):
    for decision in ("allow", "deny", "grant"):
        audit({"channel": "cli", "plugin": "p", "operation": "op", "tier": "T2", "decision": decision})
    result = run(registry, "audit", "tail", "-n", "2", "--json")
    assert [row["decision"] for row in json.loads(result.output)] == ["deny", "grant"]
    assert "p.op" in run(registry, "audit", "tail").output


def test_audit_tail_without_a_log(user_dirs, registry):
    assert json.loads(run(registry, "audit", "tail", "--json").output) == []
