"""Catalog storage: SQLite connections, schema migrations and the single-writer lock."""

import os
import sqlite3
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import IO

from lfmap_core import ToolError

SCHEMA_VERSION = 1

MIGRATIONS: dict[int, str] = {
    1: """
    CREATE TABLE roots (
      root_id INTEGER PRIMARY KEY, path TEXT NOT NULL UNIQUE,
      sensitivity TEXT NOT NULL DEFAULT 'normal' CHECK (sensitivity IN ('normal','private','secret')),
      last_scan TEXT);
    CREATE TABLE files (
      file_id INTEGER PRIMARY KEY, root_id INTEGER NOT NULL REFERENCES roots,
      rel_path TEXT NOT NULL, name_folded TEXT NOT NULL, ext TEXT NOT NULL,
      size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL, content_hash TEXT,
      status TEXT NOT NULL CHECK (status IN ('pending','indexed','skipped','error','deleted')),
      reason_code TEXT NOT NULL DEFAULT '', attempts INTEGER NOT NULL DEFAULT 0,
      first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, deleted_at TEXT,
      UNIQUE (root_id, rel_path));
    CREATE INDEX files_hash ON files(content_hash);
    CREATE TABLE contents (
      content_hash TEXT PRIMARY KEY, extractor_version TEXT NOT NULL, chars INTEGER NOT NULL,
      text_quality REAL, chunk_count INTEGER NOT NULL, indexed_at TEXT NOT NULL,
      embed_model TEXT, embedded_at TEXT);
    CREATE TABLE chunks (
      chunk_id INTEGER PRIMARY KEY, content_hash TEXT NOT NULL REFERENCES contents ON DELETE CASCADE,
      ordinal INTEGER NOT NULL, heading_path TEXT NOT NULL, char_start INTEGER NOT NULL,
      char_end INTEGER NOT NULL, text TEXT NOT NULL, UNIQUE (content_hash, ordinal));
    CREATE VIRTUAL TABLE chunks_fts USING fts5(folded, content='', tokenize='unicode61 remove_diacritics 2');
    CREATE TABLE edges (
      src_file_id INTEGER NOT NULL, rel TEXT NOT NULL CHECK (rel IN ('GENERATED_FROM','REFERENCES')),
      dst_file_id INTEGER NOT NULL, detail TEXT NOT NULL DEFAULT '',
      PRIMARY KEY (src_file_id, rel, dst_file_id));
    CREATE TABLE egress_log (
      ts TEXT NOT NULL, channel TEXT NOT NULL, operation TEXT NOT NULL,
      file_ids TEXT NOT NULL, chunk_ids TEXT NOT NULL, bytes INTEGER NOT NULL);
    PRAGMA user_version = 1;
    """
}


def connect(db_path: str | os.PathLike[str], readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        uri = Path(db_path).as_uri() + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
    else:
        conn = sqlite3.connect(str(db_path))

    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA foreign_keys = ON")
    if not readonly:
        conn.execute("PRAGMA journal_mode = WAL")

    return conn


def migrate(conn: sqlite3.Connection) -> None:
    current_version = conn.execute("PRAGMA user_version").fetchone()[0]

    if current_version > SCHEMA_VERSION:
        raise ToolError("internal", "Catalog is newer than this plugin", {"user_version": current_version})

    for version in range(current_version + 1, SCHEMA_VERSION + 1):
        conn.executescript(f"BEGIN;\n{MIGRATIONS[version]}\nCOMMIT;")


def _lock(f: IO[bytes]) -> None:
    if sys.platform == "win32":
        import msvcrt

        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(f: IO[bytes]) -> None:
    if sys.platform == "win32":
        import msvcrt

        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(f.fileno(), fcntl.LOCK_UN)


@contextmanager
def writer_lock(data_dir: str | os.PathLike[str]) -> Iterator[None]:
    """Hold indexer.lock for one writer process; a second writer gets indexer_busy instead of waiting."""
    f = open(Path(data_dir) / "indexer.lock", "a+b")
    try:
        try:
            _lock(f)
        except OSError as error:
            raise ToolError("backend_unavailable", "Another process is indexing", {"reason": "indexer_busy"}) from error
        try:
            yield
        finally:
            _unlock(f)
    finally:
        f.close()
