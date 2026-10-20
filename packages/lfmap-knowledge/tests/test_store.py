import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from lfmap_knowledge.store import SCHEMA_VERSION, connect, migrate, writer_lock

TABLES = {"roots", "files", "contents", "chunks", "chunks_fts", "edges", "egress_log"}


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def test_migrate_creates_schema(db):
    assert TABLES <= _tables(db)
    assert db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION == 1


def test_migrate_twice_is_harmless(db):
    migrate(db)
    assert db.execute("PRAGMA user_version").fetchone()[0] == 1


def test_connection_pragmas(db):
    assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert db.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    assert db.row_factory is sqlite3.Row


def test_constraints(db):
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO roots(path, sensitivity) VALUES ('D:/x', 'top')")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO files(root_id, rel_path, name_folded, ext, size, mtime_ns, status, first_seen, last_seen)"
            " VALUES (99, 'a.md', 'a.md', '.md', 1, 1, 'pending', 't', 't')"
        )


def test_readonly_connection_cannot_write(db, data_dir: Path):
    readonly = connect(data_dir / "catalog.db", readonly=True)
    try:
        assert readonly.execute("SELECT count(*) FROM roots").fetchone()[0] == 0
        with pytest.raises(sqlite3.OperationalError):
            readonly.execute("INSERT INTO roots(path) VALUES ('D:/x')")
    finally:
        readonly.close()


def _lock_from_child(data_dir: Path) -> str:
    code = (
        "import sys\n"
        "from lfmap_core import ToolError\n"
        "from lfmap_knowledge.store import writer_lock\n"
        "try:\n"
        "    with writer_lock(sys.argv[1]):\n"
        "        print('locked')\n"
        "except ToolError as e:\n"
        "    print(e.details.get('reason'))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code, str(data_dir)], capture_output=True, text=True, timeout=60, check=True
    )
    return result.stdout.strip()


def test_second_process_gets_indexer_busy(data_dir: Path):
    with writer_lock(data_dir):
        assert (data_dir / "indexer.lock").exists()
        assert _lock_from_child(data_dir) == "indexer_busy"
    assert _lock_from_child(data_dir) == "locked"


def test_lock_released_after_error(data_dir: Path):
    with pytest.raises(RuntimeError):
        with writer_lock(data_dir):
            raise RuntimeError("boom")
    with writer_lock(data_dir):
        pass


def test_busy_error_shape(data_dir: Path):
    with writer_lock(data_dir):
        code = "import sys\nfrom lfmap_knowledge.store import writer_lock\nwith writer_lock(sys.argv[1]): pass\n"
        result = subprocess.run([sys.executable, "-c", code, str(data_dir)], capture_output=True, text=True, timeout=60)
    assert result.returncode != 0
    assert "backend_unavailable" in result.stderr
