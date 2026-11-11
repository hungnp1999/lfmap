"""Backup and restore of the owner's state (#196, docs/specs/backup.md).

`create` writes one dated zip of the files that cannot be rebuilt: the owner's TOML files, grants, audit log,
approval queue, flow runs and consistent snapshots of `events.db` and the knowledge `catalog.db`. The catalog copy
has its chunk text and FTS rows removed (document content); `lfmap knowledge reindex` rebuilds them. Vectors and
the Markdown cache are rebuildable and never included. `restore` verifies every file against the manifest first and
moves what it replaces aside, so a bad restore can be undone by hand.
"""

import hashlib
import json
import os
import re
import sqlite3
import tempfile
import zipfile
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lfmap_core import approvals, flows, flows_run, grants, jobs
from lfmap_core.approval import audit_path
from lfmap_core.config import app_dir, config_path, load_config
from lfmap_core.errors import ToolError
from lfmap_core.events_adapter import bus_path
from lfmap_core.jobs import Schedule
from lfmap_core.permissions import PermissionManager, _is_remote

MANIFEST = "manifest.json"
FORMAT = 1
NAME = re.compile(r"^lfmap-backup-\d{8}T\d{6}Z\.zip$")
DEFAULT_KEEP = 7
MAX_FILE_BYTES = 2 * 1024**3
CATALOG = "knowledge/catalog.db"
EXCLUDED = ["knowledge/vectors/", "knowledge/cache/md/", "chunk text and FTS rows of catalog.db"]
_CHUNK = 1024 * 1024


def _singles() -> dict[str, Callable[[], Path]]:
    return {
        "config.toml": config_path,
        "jobs.toml": jobs.jobs_path,
        "flows.toml": flows.flows_path,
        "grants.json": grants.grants_path,
        "audit.jsonl": audit_path,
    }


def _databases() -> dict[str, Callable[[], Path]]:
    return {"events.db": bus_path, CATALOG: lambda: app_dir() / "knowledge" / "catalog.db"}


def _trees() -> dict[str, Callable[[], Path]]:
    return {"approvals": approvals.approvals_dir, "flows/runs": flows_run.runs_dir}


def target_for(name: str) -> Path:
    """Where archive member `name` belongs. Only known names and plain relative subpaths of the two trees pass."""
    if name in _singles():
        return _singles()[name]()
    if name in _databases():
        return _databases()[name]()
    for prefix, base in _trees().items():
        rest = name.removeprefix(prefix + "/")
        parts = rest.split("/")
        if name.startswith(prefix + "/") and all(
            p and p not in (".", "..") and not re.search(r"[:\\]", p) for p in parts
        ):
            return base().joinpath(*parts)
    raise ToolError("invalid_input", "Backup holds a file that LFMAP does not restore", {"name": name})


def _hash(path: Path) -> tuple[str, int]:
    digest, size = hashlib.sha256(), 0
    with path.open("rb") as file:
        while chunk := file.read(_CHUNK):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _walk(base: Path, prefix: str) -> Iterator[tuple[str, Path]]:
    for root, _dirs, files in os.walk(base, followlinks=False):
        for file in sorted(files):
            path = Path(root, file)
            if path.is_file() and not path.is_symlink():
                yield f"{prefix}/{path.relative_to(base).as_posix()}", path


def _scrub_catalog(conn: sqlite3.Connection) -> None:
    """Drop document content from the copy: chunk text, FTS rows and the 'indexed' marks that depended on them."""
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "chunks_fts" in tables:
        conn.execute("INSERT INTO chunks_fts(chunks_fts) VALUES ('delete-all')")
    for table in ("chunks", "contents"):
        if table in tables:
            conn.execute(f"DELETE FROM {table}")  # noqa: S608 - fixed names
    if "files" in tables:
        conn.execute("UPDATE files SET status = 'pending', reason_code = '' WHERE status = 'indexed'")
    conn.commit()


def snapshot(source: Path, dest: Path, scrub: Callable[[sqlite3.Connection], None] | None = None) -> None:
    """Consistent copy of a live SQLite database through `Connection.backup`; the source is opened read-only."""
    reader = sqlite3.connect(f"{source.as_uri()}?mode=ro", uri=True)
    writer = sqlite3.connect(str(dest))
    try:
        reader.backup(writer)
        if scrub:
            scrub(writer)
        writer.execute("VACUUM")
    finally:
        writer.close()
        reader.close()


def settings(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """`[backup]` from config.toml: `folder` (required), `keep` (default 7), `daily` ("03:00", optional)."""
    section = (load_config() if config is None else config).get("backup", {})
    folder, keep, daily = section.get("folder"), section.get("keep", DEFAULT_KEEP), section.get("daily")
    if not isinstance(folder, str) or not folder:
        raise ToolError("invalid_input", "Declare the backup folder in config.toml: [backup] folder = 'D:\\Backups'")
    if _is_remote(folder) or not os.path.isabs(folder):
        raise ToolError("invalid_input", "[backup] folder must be an absolute local path", {"folder": folder})
    if isinstance(keep, bool) or not isinstance(keep, int) or not 1 <= keep <= 365:
        raise ToolError("invalid_input", "[backup] keep must be a number from 1 to 365")
    if daily is not None:
        Schedule(daily=daily)
    root = os.path.realpath(folder)
    if _is_remote(root) or not os.path.isdir(root):
        raise ToolError("invalid_input", "[backup] folder does not exist or is a network path", {"folder": folder})
    return {"folder": root, "keep": keep, "daily": daily}


def task_commands(config: dict[str, Any], repo: Path, uv: Path, script: Path, pwsh: Path | None = None):
    """`schtasks /Create` for the daily backup task `\\LFMAP\\backup`, only when `[backup] daily` is set."""
    daily = config.get("backup", {}).get("daily")
    if daily is None:
        return {}
    return {"backup": jobs.schedule_command("backup", "-Backup", Schedule(daily=daily), repo, uv, script, pwsh)}


def list_backups(folder: str) -> list[Path]:
    return sorted(p for p in Path(folder).iterdir() if NAME.match(p.name) and p.is_file() and not p.is_symlink())


def create(to: str | None = None, config: dict[str, Any] | None = None, now: datetime | None = None) -> dict[str, Any]:
    cfg = settings(config)
    guard = PermissionManager([], [cfg["folder"]])
    now = (now or datetime.now(UTC)).replace(microsecond=0)
    final = guard.require_write(Path(to or cfg["folder"]) / f"lfmap-backup-{now.strftime('%Y%m%dT%H%M%SZ')}.zip")
    if not guard.require_write(final.parent).is_dir():
        raise ToolError("not_found", "Backup folder does not exist", {"folder": str(final.parent)})
    if final.exists():
        raise ToolError("conflict", "A backup with this name already exists; nothing was overwritten")
    part = final.with_name("." + final.name + ".part")
    files: list[dict[str, Any]] = []
    try:
        with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(part, "x", zipfile.ZIP_DEFLATED) as archive:

            def add(name: str, path: Path) -> None:
                digest, size = _hash(path)
                archive.write(path, name)
                files.append({"name": name, "sha256": digest, "size": size})

            for name, where in _singles().items():
                if where().is_file():
                    add(name, where())
            for prefix, where in _trees().items():
                for name, path in _walk(where(), prefix):
                    add(name, path)
            for name, where in _databases().items():
                if where().is_file():
                    copy = Path(tmp, name.replace("/", "_"))
                    snapshot(where(), copy, _scrub_catalog if name == CATALOG else None)
                    add(name, copy)
            manifest = {"format": FORMAT, "created": now.isoformat(), "files": files, "excluded": EXCLUDED}
            archive.writestr(MANIFEST, json.dumps(manifest, indent=2))
        os.replace(part, final)
    finally:
        part.unlink(missing_ok=True)
    removed = prune(cfg["folder"], cfg["keep"])
    return {"path": str(final), "files": len(files), "bytes": final.stat().st_size, "pruned": removed}


def prune(folder: str, keep: int) -> list[str]:
    old = list_backups(folder)[:-keep]
    for path in old:
        path.unlink()
    return [p.name for p in old]


def _verified_manifest(archive: zipfile.ZipFile) -> list[dict[str, Any]]:
    try:
        manifest = json.loads(archive.read(MANIFEST))
        entries = manifest["files"]
        assert manifest["format"] == FORMAT and isinstance(entries, list)
        assert all(isinstance(e["name"], str) and isinstance(e["sha256"], str) for e in entries)
    except (KeyError, ValueError, AssertionError, TypeError) as error:
        raise ToolError("invalid_input", "This is not an LFMAP backup (manifest missing or unreadable)") from error
    names = [e["name"] for e in entries]
    if len(set(names)) != len(names) or set(archive.namelist()) != {*names, MANIFEST}:
        raise ToolError("invalid_input", "Backup file list does not match its manifest")
    for entry in entries:
        target_for(entry["name"])
        if archive.getinfo(entry["name"]).file_size > MAX_FILE_BYTES:
            raise ToolError("invalid_input", "Backup holds a file that is too large", {"name": entry["name"]})
    return entries


def restore(archive_path: Path, now: datetime | None = None) -> dict[str, Any]:
    """Verify `archive_path` completely, then replace the owner's files. The caller has checked for a person."""
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    # The app folder, plus the folder of a TOML file the owner moved with LFMAP_CONFIG / LFMAP_JOBS / LFMAP_FLOWS.
    homes = {app_dir(), *(where().parent for where in (config_path, jobs.jobs_path, flows.flows_path))}
    guard = PermissionManager([], [os.path.realpath(home) for home in homes])
    staged: list[tuple[str, Path, Path]] = []
    try:
        with zipfile.ZipFile(archive_path) as archive:
            for entry in _verified_manifest(archive):
                dest = guard.require_write(target_for(entry["name"]))
                dest.parent.mkdir(parents=True, exist_ok=True)
                tmp = dest.with_name(dest.name + ".restoring")
                digest = hashlib.sha256()
                with archive.open(entry["name"]) as source, tmp.open("wb") as out:
                    staged.append((entry["name"], tmp, dest))
                    while chunk := source.read(_CHUNK):
                        digest.update(chunk)
                        out.write(chunk)
                if digest.hexdigest() != entry["sha256"]:
                    raise ToolError("invalid_input", "Backup is damaged: checksum mismatch", {"name": entry["name"]})
        previous = guard.require_write(app_dir() / "restore-previous" / stamp)
        for name, tmp, dest in staged:
            for suffix in ("", "-wal", "-shm", "-journal"):
                old = dest.with_name(dest.name + suffix)
                if old.exists():
                    moved = previous / (name + suffix)
                    moved.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(old, moved)
            os.replace(tmp, dest)
        names = [name for name, _tmp, _dest in staged]
        staged.clear()
    finally:
        for _name, tmp, _dest in staged:
            tmp.unlink(missing_ok=True)
    return {"restored": len(names), "previous": str(previous), "reindex": CATALOG in names}
