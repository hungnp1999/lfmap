"""Reconcile the file catalog with one root folder: new, changed, unchanged and deleted files."""

import fnmatch
import hashlib
import os
import sqlite3
import stat
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lfmap_core import ToolError
from lfmap_core.permissions import PermissionManager
from lfmap_markitdown.formats import DOCUMENT_EXTENSIONS, IMAGE_EXTENSIONS, OFFICE_GUI_ONLY

KNOWN_EXTENSIONS = DOCUMENT_EXTENSIONS | IMAGE_EXTENSIONS | OFFICE_GUI_ONLY
DEFAULT_EXCLUDE = [".git", "node_modules", ".venv", "AppData", ".ssh", "*.kdbx", ".env"]
DEFAULT_MAX_FILE_BYTES = 209_715_200
CLOUD_ONLY = 0x00400000 | 0x00040000  # FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS | RECALL_ON_OPEN
_HIDDEN_OR_SYSTEM = stat.FILE_ATTRIBUTE_HIDDEN | stat.FILE_ATTRIBUTE_SYSTEM


@dataclass
class ScanStats:
    seen: int = 0
    new: int = 0
    changed: int = 0
    unchanged: int = 0
    deleted: int = 0
    skipped: int = 0
    hashed: int = 0


def hash_file(path: Path) -> str:
    """BLAKE2b-256 of the file, read in 1 MB blocks."""
    hasher = hashlib.blake2b(digest_size=32)
    with open(path, "rb") as f:
        while block := f.read(1_048_576):
            hasher.update(block)
    return hasher.hexdigest()


def _skip(entry: os.DirEntry, exclude: list[str]) -> bool:
    if entry.is_symlink() or entry.is_junction() or entry.name.startswith((".", "~$")):
        return True
    if getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0) & _HIDDEN_OR_SYSTEM:
        return True
    name = entry.name.casefold()
    return any(fnmatch.fnmatch(name, pattern.casefold()) for pattern in exclude)


def _walk(folder: str | os.PathLike[str], exclude: list[str]) -> Iterator[os.DirEntry]:
    """Visible regular files under folder; linked folders (symlinks, junctions) are never entered."""
    with os.scandir(folder) as entries:
        for entry in entries:
            if _skip(entry, exclude):
                continue
            if entry.is_dir(follow_symlinks=False):
                yield from _walk(entry.path, exclude)
            elif entry.is_file(follow_symlinks=False):
                yield entry


def _classify(
    conn: sqlite3.Connection, path: Path, st: os.stat_result, settings: dict[str, Any], extractor_version: str
) -> tuple[str, str, str | None]:
    """(status, reason_code, content_hash) for a new or changed file."""
    cloud = getattr(st, "st_file_attributes", 0) & CLOUD_ONLY
    if cloud and not settings.get("include_cloud_files", False):
        return "skipped", "cloud_only", None
    if st.st_size > settings.get("max_file_bytes", DEFAULT_MAX_FILE_BYTES):
        return "skipped", "too_large", None
    content_hash = hash_file(path)
    if path.suffix.lower() not in KNOWN_EXTENSIONS:
        return "skipped", "unsupported_format", content_hash
    known = conn.execute(
        "SELECT 1 FROM contents WHERE content_hash = ? AND extractor_version = ?", (content_hash, extractor_version)
    ).fetchone()
    return ("indexed" if known else "pending"), "", content_hash


def reconcile(
    conn: sqlite3.Connection,
    root_id: int,
    root_path: Path,
    perms: PermissionManager,
    settings: dict[str, Any],
    extractor_version: str = "",
    pdf_extractor_version: str | None = None,
) -> ScanStats:
    """Bring the files rows of one root in line with the disk; only new or changed files are hashed."""
    now = datetime.now(UTC).isoformat(timespec="seconds")
    stats = ScanStats()
    seen: set[str] = set()
    for entry in _walk(root_path, settings.get("exclude", DEFAULT_EXCLUDE)):
        try:
            path = perms.require_read(entry.path)
        except ToolError:
            stats.skipped += 1
            continue
        st = os.stat(path)
        rel = path.relative_to(root_path).as_posix()
        seen.add(rel)
        stats.seen += 1
        row = conn.execute("SELECT * FROM files WHERE root_id = ? AND rel_path = ?", (root_id, rel)).fetchone()
        if row and row["status"] != "deleted" and (row["size"], row["mtime_ns"]) == (st.st_size, st.st_mtime_ns):
            stats.unchanged += 1
            conn.execute("UPDATE files SET last_seen = ? WHERE file_id = ?", (now, row["file_id"]))
            continue
        version = (
            pdf_extractor_version if pdf_extractor_version and path.suffix.lower() == ".pdf" else extractor_version
        )
        status, reason, content_hash = _classify(conn, path, st, settings, version)
        stats.hashed += content_hash is not None
        stats.skipped += status == "skipped"
        name_folded = unicodedata.normalize("NFC", path.name).casefold().replace("đ", "d")
        values = (name_folded, path.suffix.lower(), st.st_size, st.st_mtime_ns, content_hash, status, reason, now)
        if row:
            stats.changed += 1
            conn.execute(
                "UPDATE files SET name_folded = ?, ext = ?, size = ?, mtime_ns = ?, content_hash = ?, status = ?,"
                " reason_code = ?, last_seen = ?, attempts = 0, deleted_at = NULL WHERE file_id = ?",
                (*values, row["file_id"]),
            )
        else:
            stats.new += 1
            conn.execute(
                "INSERT INTO files (name_folded, ext, size, mtime_ns, content_hash, status, reason_code, last_seen,"
                " root_id, rel_path, first_seen) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (*values, root_id, rel, now),
            )
    rows = conn.execute("SELECT file_id, rel_path FROM files WHERE root_id = ? AND status != 'deleted'", (root_id,))
    for row in rows.fetchall():
        if row["rel_path"] not in seen:
            stats.deleted += 1
            conn.execute("UPDATE files SET status = 'deleted', deleted_at = ? WHERE file_id = ?", (now, row["file_id"]))
    conn.execute("UPDATE roots SET last_scan = ? WHERE root_id = ?", (now, root_id))
    conn.commit()
    return stats
