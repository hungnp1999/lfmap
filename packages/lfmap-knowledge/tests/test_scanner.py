import hashlib
import os
from pathlib import Path

import pytest

from lfmap_knowledge.scanner import ScanStats, hash_file, reconcile


def _root_id(db, root: Path) -> int:
    return db.execute("INSERT INTO roots(path) VALUES (?)", (str(root),)).lastrowid


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _touch_later(path: Path, text: str) -> None:
    before = path.stat()
    path.write_text(text, encoding="utf-8")
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + 2_000_000_000))


def _rows(db) -> dict[str, dict]:
    return {row["rel_path"]: dict(row) for row in db.execute("SELECT * FROM files")}


@pytest.fixture
def three(root: Path) -> Path:
    _write(root / "a.docx", "aaa")
    _write(root / "b.pdf", "bbb")
    _write(root / "sub" / "c.md", "# c")
    return root


def test_hash_file_is_blake2b_256(tmp_path: Path):
    path = tmp_path / "big.bin"
    data = os.urandom(2_500_000)
    path.write_bytes(data)
    assert hash_file(path) == hashlib.blake2b(data, digest_size=32).hexdigest()


def test_first_scan_finds_new_files(db, three, perms):
    stats = reconcile(db, _root_id(db, three), three, perms, {})
    assert isinstance(stats, ScanStats)
    assert (stats.new, stats.hashed, stats.deleted) == (3, 3, 0)
    rows = _rows(db)
    assert set(rows) == {"a.docx", "b.pdf", "sub/c.md"}
    assert {row["status"] for row in rows.values()} == {"pending"}
    assert rows["b.pdf"]["ext"] == ".pdf" and rows["b.pdf"]["size"] == 3


def test_changed_unchanged_deleted(db, three, perms):
    root_id = _root_id(db, three)
    reconcile(db, root_id, three, perms, {})
    _touch_later(three / "a.docx", "changed")
    stats = reconcile(db, root_id, three, perms, {})
    assert (stats.changed, stats.unchanged, stats.hashed) == (1, 2, 1)
    stats = reconcile(db, root_id, three, perms, {})
    assert (stats.changed, stats.unchanged, stats.hashed) == (0, 3, 0)
    (three / "b.pdf").unlink()
    stats = reconcile(db, root_id, three, perms, {})
    assert stats.deleted == 1
    row = _rows(db)["b.pdf"]
    assert row["status"] == "deleted" and row["deleted_at"]


def test_unsupported_format_is_cataloged(db, root, perms):
    _write(root / "data.xyz", "?")
    reconcile(db, _root_id(db, root), root, perms, {})
    row = _rows(db)["data.xyz"]
    assert (row["status"], row["reason_code"]) == ("skipped", "unsupported_format")
    assert row["content_hash"]


def test_excluded_hidden_and_lock_files(db, root, perms):
    _write(root / ".git" / "notes.md", "x")
    _write(root / "node_modules" / "readme.md", "x")
    _write(root / "vault.kdbx", "x")
    _write(root / "~$draft.docx", "x")
    _write(root / ".hidden.md", "x")
    _write(root / "keep.md", "x")
    reconcile(db, _root_id(db, root), root, perms, {})
    assert set(_rows(db)) == {"keep.md"}


def test_custom_exclude_setting(db, root, perms):
    _write(root / "a.md", "x")
    _write(root / "b.log", "x")
    reconcile(db, _root_id(db, root), root, perms, {"exclude": ["*.log"]})
    assert set(_rows(db)) == {"a.md"}


def test_too_large_is_not_hashed(db, root, perms):
    _write(root / "big.md", "x" * 20)
    stats = reconcile(db, _root_id(db, root), root, perms, {"max_file_bytes": 10})
    row = _rows(db)["big.md"]
    assert (row["status"], row["reason_code"], row["content_hash"]) == ("skipped", "too_large", None)
    assert (stats.skipped, stats.hashed) == (1, 0)


def test_known_content_is_indexed(db, root, perms):
    path = _write(root / "a.md", "same")
    db.execute(
        "INSERT INTO contents(content_hash, extractor_version, chars, chunk_count, indexed_at)"
        " VALUES (?, 'v1', 4, 1, 't')",
        (hash_file(path),),
    )
    reconcile(db, _root_id(db, root), root, perms, {}, extractor_version="v1")
    assert _rows(db)["a.md"]["status"] == "indexed"


def test_name_is_folded(db, root, perms):
    _write(root / "Đường Phố.md", "x")
    reconcile(db, _root_id(db, root), root, perms, {})
    assert _rows(db)["Đường Phố.md"]["name_folded"] == "dường phố.md"


def test_linked_folder_is_not_entered(db, root, perms, tmp_path: Path):
    outside = tmp_path / "outside"
    _write(outside / "x.md", "x")
    try:
        os.symlink(outside, root / "link", target_is_directory=True)
    except OSError:
        pytest.skip("symlinks need extra rights on this machine")
    _write(root / "a.md", "x")
    reconcile(db, _root_id(db, root), root, perms, {})
    assert set(_rows(db)) == {"a.md"}
