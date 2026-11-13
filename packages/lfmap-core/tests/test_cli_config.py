import json
import os

import pytest
from typer.testing import CliRunner

from lfmap_core import cli
from lfmap_core.approval import audit, audit_path
from lfmap_core.cli import build_app
from lfmap_core.config import add_folder, load_config
from lfmap_core.errors import ToolError


def run(registry, *args, input=None):
    return CliRunner().invoke(build_app(registry), list(args), input=input)


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
    monkeypatch.setattr(cli, "_confirm_code", lambda: "ABC234")
    docs, scans = tmp_path / "Tài liệu", tmp_path / "scans"
    docs.mkdir()
    scans.mkdir()
    config = user_dirs / "config.toml"
    config.write_text('# my settings\n[paths]\nexports = []\n\n[plugins.x.settings]\nk = "v"\n', encoding="utf-8")
    assert run(registry, "config", "add-folder", str(docs), "--as", "documents", input="ABC234\n").exit_code == 0
    assert run(registry, "config", "add-folder", str(scans), "--as", "documents", input="ABC234\n").exit_code == 0
    assert run(registry, "config", "add-folder", str(docs), "--as", "documents", input="ABC234\n").exit_code == 0
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


def test_add_folder_with_wrong_code_writes_nothing(user_dirs, registry, monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    monkeypatch.setattr(cli, "_confirm_code", lambda: "ABC234")
    result = run(registry, "config", "add-folder", str(tmp_path), "--as", "documents", input="ABC235\n")
    assert result.exception.code == "permission_denied"
    assert not (user_dirs / "config.toml").exists()
    [record] = [json.loads(line) for line in audit_path().read_text(encoding="utf-8").splitlines()]
    assert (record["decision"], record["target"]) == ("deny", str(tmp_path))


def test_add_folder_prompt_escapes_control_characters(user_dirs, registry, monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    monkeypatch.setattr(cli, "_confirm_code", lambda: "ABC234")
    folder = str(tmp_path) + "\x1b[2K"
    result = run(registry, "config", "add-folder", folder, "--as", "documents", input="no\n")
    assert result.exception.code == "permission_denied"
    assert "\x1b" not in result.output
    assert r"\u001b[2K" in result.output


def test_require_code_refuses_without_a_terminal(user_dirs):
    with pytest.raises(ToolError) as error:
        cli._require_code("grant x", {})
    assert error.value.code == "permission_denied"


def _terminal(monkeypatch, code="ABC234"):
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    monkeypatch.setattr(cli, "_confirm_code", lambda: code)


def _audit_lines():
    return [json.loads(line) for line in audit_path().read_text(encoding="utf-8").splitlines()]


def _folders(tmp_path, *names):
    paths = []
    for name in names:
        folder = tmp_path / name
        folder.mkdir(parents=True, exist_ok=True)
        paths.append(str(folder))
    return paths


def test_classify_lowering_needs_code(user_dirs, registry, monkeypatch, tmp_path):
    from lfmap_core.data_classes import load_class_map

    _terminal(monkeypatch)
    [work] = _folders(tmp_path, "work")
    config = user_dirs / "config.toml"
    config.write_text(f"[data.classes]\n'{work}' = \"secret\"\n", encoding="utf-8")
    before = config.read_bytes()
    # Lowering secret -> scratch: a wrong code writes nothing.
    result = run(registry, "data", "classify", work, "scratch", input="WRONG1\n")
    assert result.exception.code == "permission_denied"
    assert config.read_bytes() == before
    [denied] = _audit_lines()
    assert (denied["decision"], denied["target"]) == ("deny", os.path.realpath(work))
    # The right code applies it.
    assert run(registry, "data", "classify", work, "scratch", input="ABC234\n").exit_code == 0
    assert load_class_map(load_config(config)).class_of(work) == "scratch"
    assert _audit_lines()[-1]["reason"] == "data classify secret -> scratch"
    # Raising scratch -> normal -> private: yes/no only, the code prompt is never reached.
    monkeypatch.setattr(cli, "_require_code", lambda *a, **k: pytest.fail("raising must not ask for the code"))
    assert run(registry, "data", "classify", work, "normal", input="y\n").exit_code == 0
    assert run(registry, "data", "classify", work, "private", input="y\n").exit_code == 0
    assert load_class_map(load_config(config)).class_of(work) == "private"
    # Answering no changes nothing.
    snapshot = config.read_bytes()
    declined = run(registry, "data", "classify", work, "secret", input="n\n")
    assert declined.exception.code == "permission_denied"
    assert config.read_bytes() == snapshot
    assert [r["reason"] for r in _audit_lines() if r["decision"] == "grant"] == [
        "data classify secret -> scratch",
        "data classify scratch -> normal",
        "data classify normal -> private",
    ]


def test_classify_keeps_comments(user_dirs, registry, monkeypatch, tmp_path):
    _terminal(monkeypatch)
    [tmp] = _folders(tmp_path, "tmp")
    config = user_dirs / "config.toml"
    original = '# my settings\n[paths]\nexports = [] # keep\n\n[plugins.x.settings]\nk = "v"\n'
    config.write_text(original, encoding="utf-8")
    # Table absent: it is created at the end; everything before stays byte for byte.
    assert run(registry, "data", "classify", tmp, "private", input="y\n").exit_code == 0
    created = config.read_text(encoding="utf-8")
    assert created == original + f"\n[data.classes]\n'{os.path.realpath(tmp)}' = \"private\"\n"
    # Table present with comments and a following table: only the one line changes.
    text = (
        "# top\n[data.classes]\n# note about scratch\n"
        f"'{os.path.realpath(tmp)}' = \"normal\" # why\n\n[plugins.y]\nz = 1 # tail\n"
    )
    config.write_text(text, encoding="utf-8")
    assert run(registry, "data", "classify", tmp, "private", input="y\n").exit_code == 0
    assert config.read_text(encoding="utf-8") == text.replace('"normal" # why', '"private" # why')


def test_unclassify_last_entry_turns_off(user_dirs, registry, monkeypatch, tmp_path):
    from lfmap_core.data_classes import load_class_map

    _terminal(monkeypatch)
    [work] = _folders(tmp_path, "work")
    root = os.path.realpath(work)
    config = user_dirs / "config.toml"
    config.write_text(f"[data.classes]\n'{root}' = \"normal\"\n\n[paths]\nexports = []\n", encoding="utf-8")
    # normal -> private (the default) is raising: yes/no only.
    result = run(registry, "data", "unclassify", work, input="y\n")
    assert result.exit_code == 0
    assert "feature is off" in result.output
    assert config.read_text(encoding="utf-8") == "[data.classes]\n\n[paths]\nexports = []\n"
    assert not load_class_map(load_config(config))
    assert _audit_lines()[-1]["reason"] == "data unclassify normal -> private"
    # No entry any more: nothing to remove.
    again = run(registry, "data", "unclassify", work, input="y\n")
    assert again.exception.code == "invalid_input"


def test_unclassify_a_more_protective_entry_needs_code(user_dirs, registry, monkeypatch, tmp_path):
    _terminal(monkeypatch)
    [work, vault] = _folders(tmp_path, "work", "work/vault")
    config = user_dirs / "config.toml"
    config.write_text(
        f"[data.classes]\n'{os.path.realpath(work)}' = \"normal\"\n'{os.path.realpath(vault)}' = \"secret\"\n",
        encoding="utf-8",
    )
    before = config.read_bytes()
    assert run(registry, "data", "unclassify", vault, input="NOPE12\n").exception.code == "permission_denied"
    assert config.read_bytes() == before
    assert run(registry, "data", "unclassify", vault, input="ABC234\n").exit_code == 0
    assert "vault" not in config.read_text(encoding="utf-8")
    assert _audit_lines()[-1]["reason"] == "data unclassify secret -> normal"


def test_data_commands_need_a_terminal(user_dirs, registry, tmp_path):
    [work] = _folders(tmp_path, "work")
    for args in (("classify", work, "scratch"), ("unclassify", work)):
        assert run(registry, "data", *args).exception.code == "permission_denied"
    assert not (user_dirs / "config.toml").exists()


def test_classify_refuses_unknown_class_and_relative_path(user_dirs, registry, monkeypatch, tmp_path):
    _terminal(monkeypatch)
    [work] = _folders(tmp_path, "work")
    assert run(registry, "data", "classify", work, "top-secret").exception.code == "invalid_input"
    assert run(registry, "data", "classify", "relative/dir", "scratch").exception.code == "invalid_input"
    assert not (user_dirs / "config.toml").exists()


def test_classify_refuses_a_single_quote_path(user_dirs, registry, monkeypatch, tmp_path):
    _terminal(monkeypatch)
    [odd] = _folders(tmp_path, "it's")
    result = run(registry, "data", "classify", odd, "scratch", input="y\n")
    assert result.exception.code == "invalid_input"
    assert "by hand" in result.exception.message
    assert not (user_dirs / "config.toml").exists()


@pytest.mark.parametrize("key", ["\\\\server\\share\\x", "\\\\?\\C:\\x", "\\\\.\\COM1", "//server/share/x"])
def test_data_commands_refuse_remote_paths_before_any_io(user_dirs, registry, monkeypatch, key):
    _terminal(monkeypatch)
    seen = []
    monkeypatch.setattr(os.path, "realpath", lambda p, **k: seen.append(p) or p)
    for args in (("classify", key, "scratch"), ("unclassify", key), ("explain", key)):
        assert run(registry, "data", *args, input="y\n").exception.code == "permission_denied"
    assert key not in seen
    assert not (user_dirs / "config.toml").exists()


def test_data_explain_and_classes(user_dirs, registry, tmp_path):
    work, vault, gone = (str(tmp_path / n) for n in ("work", "work/vault", "gone"))
    _folders(tmp_path, "work", "work/vault")
    (user_dirs / "config.toml").write_text(
        f"[data.classes]\n'{work}' = \"normal\"\n'{vault}' = \"secret\"\n'{gone}' = \"scratch\"\n", encoding="utf-8"
    )
    explained = json.loads(run(registry, "data", "explain", work + "/notes.md", "--json").output)
    assert explained == {
        "path": os.path.realpath(work + "/notes.md"),
        "active": True,
        "class_of": "normal",
        "entry": os.path.realpath(work),
        "class_under": "normal",
    }
    folder = json.loads(run(registry, "data", "explain", work, "--json").output)
    assert (folder["class_of"], folder["class_under"]) == ("normal", "secret")
    other = json.loads(run(registry, "data", "explain", str(tmp_path / "x.txt"), "--json").output)
    assert (other["class_of"], other["entry"], other["class_under"]) == ("private", None, "private")
    assert "class_under" in run(registry, "data", "explain", work).output
    rows = json.loads(run(registry, "data", "classes", "--json").output)
    assert rows == [
        {"path": os.path.realpath(gone), "class": "scratch", "exists": False},
        {"path": os.path.realpath(work), "class": "normal", "exists": True},
        {"path": os.path.realpath(vault), "class": "secret", "exists": True},
    ]
    assert "missing" in run(registry, "data", "classes").output


def test_data_commands_with_the_model_off(user_dirs, registry, tmp_path):
    assert "off" in run(registry, "data", "classes").output
    assert json.loads(run(registry, "data", "classes", "--json").output) == []
    off = json.loads(run(registry, "data", "explain", str(tmp_path), "--json").output)
    assert (off["active"], off["class_of"]) == (False, "private")


def test_data_edit_refuses_when_the_file_changed_while_waiting(user_dirs, registry, monkeypatch, tmp_path):
    _terminal(monkeypatch)
    [work] = _folders(tmp_path, "work")
    config = user_dirs / "config.toml"
    config.write_text("# a\n", encoding="utf-8")

    def edit_meanwhile(*args, **kwargs):
        config.write_text("# b\n", encoding="utf-8")
        return True

    monkeypatch.setattr(cli.typer, "confirm", edit_meanwhile)
    result = run(registry, "data", "classify", work, "private")
    assert result.exception.code == "invalid_input"
    assert config.read_text(encoding="utf-8") == "# b\n"


def test_data_output_and_audit_hold_no_secret(user_dirs, registry, monkeypatch, tmp_path):
    _terminal(monkeypatch)
    [work] = _folders(tmp_path, "work")
    run(registry, "data", "classify", work, "normal", input="y\n")
    run(registry, "data", "classify", work, "scratch", input="ABC234\n")
    log = audit_path().read_text(encoding="utf-8")
    assert "otpauth" not in log
    assert "ABC234" not in log
