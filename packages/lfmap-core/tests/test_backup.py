import json
import sqlite3
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from lfmap_core import backup, cli
from lfmap_core.cli import build_app
from lfmap_core.config import app_dir
from lfmap_core.errors import ToolError

T0 = datetime(2026, 11, 10, 3, 0, 0, tzinfo=UTC)


def make_catalog(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE files (file_id INTEGER PRIMARY KEY, status TEXT, reason_code TEXT DEFAULT '');
        CREATE TABLE contents (content_hash TEXT PRIMARY KEY);
        CREATE TABLE chunks (chunk_id INTEGER PRIMARY KEY, content_hash TEXT, text TEXT);
        CREATE VIRTUAL TABLE chunks_fts USING fts5(folded, content='');
        INSERT INTO files VALUES (1, 'indexed', '');
        INSERT INTO contents VALUES ('h');
        INSERT INTO chunks VALUES (1, 'h', 'secret contract text');
        INSERT INTO chunks_fts(rowid, folded) VALUES (1, 'secret contract text');
        """
    )
    conn.commit()
    conn.close()


@pytest.fixture
def state(user_dirs):
    app = app_dir()
    app.mkdir(parents=True)
    (user_dirs / "backups").mkdir()
    (user_dirs / "config.toml").write_text(
        f"[backup]\nfolder = '{user_dirs / 'backups'}'\nkeep = 2\n", encoding="utf-8"
    )
    (app / "grants.json").write_text("[]", encoding="utf-8")
    (app / "audit.jsonl").write_text('{"a": 1}\n', encoding="utf-8")
    (app / "approvals" / "pending").mkdir(parents=True)
    (app / "approvals" / "pending" / "p1.json").write_text("{}", encoding="utf-8")
    (app / "flows" / "runs").mkdir(parents=True)
    (app / "flows" / "runs" / "r1.json").write_text("{}", encoding="utf-8")
    (app / "knowledge" / "vectors").mkdir(parents=True)
    (app / "knowledge" / "vectors" / "v.lance").write_text("vec", encoding="utf-8")
    make_catalog(app / "knowledge" / "catalog.db")
    return user_dirs


def names(path: str) -> set[str]:
    return set(zipfile.ZipFile(path).namelist())


def test_create_holds_owner_files_and_scrubbed_catalog(state, tmp_path):
    result = backup.create(now=T0)
    assert Path(result["path"]).name == "lfmap-backup-20261110T030000Z.zip"
    assert names(result["path"]) == {
        "manifest.json", "config.toml", "grants.json", "audit.jsonl", "approvals/pending/p1.json",
        "flows/runs/r1.json", "knowledge/catalog.db",
    }  # fmt: skip
    extracted = tmp_path / "out"
    zipfile.ZipFile(result["path"]).extract("knowledge/catalog.db", extracted)
    conn = sqlite3.connect(extracted / "knowledge" / "catalog.db")
    assert conn.execute("SELECT count(*) FROM chunks").fetchone() == (0,)
    assert conn.execute("SELECT status FROM files").fetchone() == ("pending",)
    assert b"secret contract text" not in (extracted / "knowledge" / "catalog.db").read_bytes()
    manifest = json.loads(zipfile.ZipFile(result["path"]).read("manifest.json"))
    assert all(len(e["sha256"]) == 64 for e in manifest["files"])


def test_live_database_is_snapshotted(state):
    (app_dir() / "events.db").write_bytes(b"")
    conn = sqlite3.connect(app_dir() / "events.db")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("CREATE TABLE t (x)")
    conn.execute("INSERT INTO t VALUES (7)")
    conn.commit()  # stays open: data may still sit in the WAL
    path = backup.create(now=T0)["path"]
    zipfile.ZipFile(path).extract("events.db", state / "check")
    assert sqlite3.connect(state / "check" / "events.db").execute("SELECT x FROM t").fetchone() == (7,)
    conn.close()


def test_never_overwrites(state):
    backup.create(now=T0)
    with pytest.raises(ToolError) as error:
        backup.create(now=T0)
    assert error.value.code == "conflict"
    assert not list((state / "backups").glob(".*part"))


def test_keeps_last_n(state):
    for i in range(4):
        backup.create(now=T0 + timedelta(days=i))
    assert [p.name for p in backup.list_backups(str(state / "backups"))] == [
        "lfmap-backup-20261112T030000Z.zip",
        "lfmap-backup-20261113T030000Z.zip",
    ]


def test_target_must_be_inside_declared_folder(state, tmp_path):
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    with pytest.raises(ToolError) as error:
        backup.create(str(outside), now=T0)
    assert error.value.code == "permission_denied"
    inside = state / "backups" / "sub"
    inside.mkdir()
    assert Path(backup.create(str(inside), now=T0)["path"]).parent == inside.resolve()


@pytest.mark.parametrize("section", ["", "[backup]\nkeep = 3\n", "[backup]\nfolder = '\\\\\\\\host\\\\share'\n"])
def test_folder_must_be_declared_local(user_dirs, section):
    (user_dirs / "config.toml").write_text(section, encoding="utf-8")
    with pytest.raises(ToolError) as error:
        backup.create(now=T0)
    assert error.value.code == "invalid_input"


def test_restore_round_trip_moves_old_files_aside(state):
    path = backup.create(now=T0)["path"]
    (app_dir() / "grants.json").write_text('["changed"]', encoding="utf-8")
    (app_dir() / "flows" / "runs" / "r1.json").unlink()
    result = backup.restore(Path(path), now=T0)
    assert (app_dir() / "grants.json").read_text(encoding="utf-8") == "[]"
    assert (app_dir() / "flows" / "runs" / "r1.json").exists()
    assert result["reindex"] is True
    assert (Path(result["previous"]) / "grants.json").read_text(encoding="utf-8") == '["changed"]'
    assert not list(app_dir().rglob("*.restoring"))


def rewrite(path: str, edit) -> Path:
    out = Path(path).with_name("edited.zip")
    with zipfile.ZipFile(path) as src, zipfile.ZipFile(out, "w") as dst:
        for info in src.infolist():
            edit(dst, info.filename, src.read(info.filename))
    return out


def test_restore_refuses_tampered_member_and_changes_nothing(state):
    path = backup.create(now=T0)["path"]
    (app_dir() / "grants.json").write_text('["keep"]', encoding="utf-8")
    bad = rewrite(path, lambda z, n, d: z.writestr(n, b"[evil]" if n == "grants.json" else d))
    with pytest.raises(ToolError, match="checksum"):
        backup.restore(bad)
    assert (app_dir() / "grants.json").read_text(encoding="utf-8") == '["keep"]'
    assert not list(app_dir().rglob("*.restoring"))


@pytest.mark.parametrize("name", ["../evil.txt", "/abs.txt", "approvals/../../x", "C:/x", "approvals\\x", "other.txt"])
def test_restore_refuses_unknown_or_escaping_names(state, name):
    path = backup.create(now=T0)["path"]

    def edit(z, n, d):
        if n == "manifest.json":
            manifest = json.loads(d)
            manifest["files"].append({"name": name, "sha256": "0" * 64, "size": 1})
            d = json.dumps(manifest)
        z.writestr(n, d)

    bad = rewrite(path, edit)
    with zipfile.ZipFile(bad, "a") as z:
        z.writestr(name, "x")
    with pytest.raises(ToolError):
        backup.restore(bad)
    assert not (state / "evil.txt").exists()


def test_restore_refuses_a_zip_without_manifest(state, tmp_path):
    other = tmp_path / "x.zip"
    with zipfile.ZipFile(other, "w") as z:
        z.writestr("a.txt", "a")
    with pytest.raises(ToolError, match="not an LFMAP backup"):
        backup.restore(other)


def test_task_commands_only_when_daily_is_set(state):
    args = (Path("D:/rt"), Path("uv.exe"), Path("D:/rt/scripts/Invoke-LfmapJob.ps1"))
    assert backup.task_commands({"backup": {"folder": "x"}}, *args) == {}
    command = backup.task_commands({"backup": {"folder": "x", "daily": "03:30"}}, *args)["backup"]
    assert "\\LFMAP\\backup" in command and "-Backup" in command[command.index("/TR") + 1] and "03:30" in command


def test_cli_create_and_list(state, registry):
    runner = CliRunner()
    result = runner.invoke(build_app(registry), ["backup", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["files"] >= 5
    listed = runner.invoke(build_app(registry), ["backup", "list", "--json"])
    assert len(json.loads(listed.output)) == 1


def test_cli_restore_needs_a_terminal(state, registry):
    path = backup.create(now=T0)["path"]
    result = CliRunner().invoke(build_app(registry), ["backup", "restore", path])
    assert result.exception.code == "permission_denied"


def test_cli_restore_needs_the_code(state, registry, monkeypatch):
    path = backup.create(now=T0)["path"]
    (app_dir() / "grants.json").write_text('["keep"]', encoding="utf-8")
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    monkeypatch.setattr(cli, "_confirm_code", lambda: "ABC234")
    wrong = CliRunner().invoke(build_app(registry), ["backup", "restore", path], input="WRONG\n")
    assert wrong.exception.code == "permission_denied"
    assert (app_dir() / "grants.json").read_text(encoding="utf-8") == '["keep"]'
    right = CliRunner().invoke(build_app(registry), ["backup", "restore", path], input="ABC234\n")
    assert right.exit_code == 0, right.output
    assert (app_dir() / "grants.json").read_text(encoding="utf-8") == "[]"
