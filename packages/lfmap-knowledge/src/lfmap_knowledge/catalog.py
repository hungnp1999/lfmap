"""File catalog queries: find files by name, glob, root, type, status and date (search_files, get_file)."""

import fnmatch
import os
import sqlite3
import unicodedata
from collections.abc import Collection
from datetime import UTC, datetime
from pathlib import Path

from lfmap_core import ToolError

from .extract import PDF_BACKENDS, cache_path
from .schemas import FileInfo, GetFileOutput, SearchFilesOutput

STATUSES = ("pending", "indexed", "skipped", "error", "deleted")
GLOB_CHARS = frozenset("*?[")

_FILE_COLUMNS = "f.*, r.path AS root_path"


def strip_accents(s: str) -> str:
    """Casefold, map đ to d and drop every combining mark: "Báo Cáo ĐỀ" -> "bao cao de"."""
    decomposed = unicodedata.normalize("NFD", s.casefold().replace("đ", "d"))
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def abs_path(root_path: str, rel_path: str) -> str:
    return os.path.normpath(os.path.join(root_path, *rel_path.split("/")))


def _same_path(a: str, b: str) -> bool:
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


def root_id(conn: sqlite3.Connection, root: str, exclude_root_ids: Collection[int] = frozenset()) -> int:
    """Catalog id of a root path; a root that is unknown or excluded is not_found alike."""
    for row in conn.execute("SELECT root_id, path FROM roots"):
        if _same_path(row["path"], root) and row["root_id"] not in exclude_root_ids:
            return row["root_id"]
    raise ToolError("not_found", "Root is not in the catalog", {"root": root})


def _ext(ext: str) -> str:
    return "." + ext.lstrip(".").lower()


def after_ns(modified_after: str) -> int:
    try:
        moment = datetime.fromisoformat(modified_after)
    except ValueError as error:
        detail = {"modified_after": modified_after}
        raise ToolError("invalid_input", "modified_after is not an ISO date", detail) from error
    if moment.tzinfo is None:
        moment = moment.astimezone()
    return int(moment.timestamp() * 1_000_000) * 1000


def _matches(row: sqlite3.Row, query: str) -> bool:
    if not query:
        return True
    if GLOB_CHARS & set(query):
        return fnmatch.fnmatchcase(strip_accents(row["rel_path"]), strip_accents(query))
    name = strip_accents(row["name_folded"])
    return all(word in name for word in strip_accents(query).split())


def _file_info(row: sqlite3.Row) -> FileInfo:
    return FileInfo(
        path=abs_path(row["root_path"], row["rel_path"]),
        root=row["root_path"],
        ext=row["ext"],
        size=row["size"],
        mtime=datetime.fromtimestamp(row["mtime_ns"] // 1_000_000_000, UTC).isoformat(),
        status=row["status"],
        reason_code=row["reason_code"],
        content_hash=row["content_hash"] or "",
    )


def search_files(
    conn: sqlite3.Connection,
    query: str = "",
    root: str = "",
    ext: str = "",
    status: str = "",
    modified_after: str = "",
    limit: int = 10,
    exclude_root_ids: Collection[int] = frozenset(),
) -> SearchFilesOutput:
    """Newest first; total counts every match before limit. The caller checks read permission on root."""
    where: list[str] = []
    params: list[object] = []
    if status:
        if status not in STATUSES:
            raise ToolError("invalid_input", "Unknown file status", {"status": status, "allowed": list(STATUSES)})
        where.append("f.status = ?")
        params.append(status)
    else:
        where.append("f.status != 'deleted'")
    if root:
        where.append("f.root_id = ?")
        params.append(root_id(conn, root, exclude_root_ids))
    if ext:
        where.append("f.ext = ?")
        params.append(_ext(ext))
    if modified_after:
        where.append("f.mtime_ns > ?")
        params.append(after_ns(modified_after))
    if exclude_root_ids:
        where.append(f"f.root_id NOT IN ({','.join('?' * len(exclude_root_ids))})")
        params.extend(exclude_root_ids)

    rows = conn.execute(
        f"SELECT {_FILE_COLUMNS} FROM files f JOIN roots r USING (root_id)"
        f" WHERE {' AND '.join(where)} ORDER BY f.mtime_ns DESC, f.file_id",
        params,
    ).fetchall()
    matches = [row for row in rows if _matches(row, query)]
    return SearchFilesOutput(files=[_file_info(row) for row in matches[:limit]], total=len(matches))


def find_file(conn: sqlite3.Connection, path: Path) -> sqlite3.Row:
    """The live files row of a resolved path, in the longest root that contains it, with root_path."""
    best: tuple[int, str] | None = None
    best_len = -1
    for row in conn.execute("SELECT root_id, path FROM roots"):
        try:
            relative = path.relative_to(row["path"])
        except ValueError:
            continue
        if len(row["path"]) > best_len:
            best, best_len = (row["root_id"], relative.as_posix()), len(row["path"])
    if best is not None:
        found = conn.execute(
            f"SELECT {_FILE_COLUMNS} FROM files f JOIN roots r USING (root_id)"
            " WHERE f.root_id = ? AND f.rel_path = ? AND f.status != 'deleted'",
            best,
        ).fetchone()
        if found is not None:
            return found
    raise ToolError("not_found", "File is not in the catalog", {"path": str(path)})


def get_file(
    conn: sqlite3.Connection,
    path: Path,
    cache_dir: Path,
    exclude_root_ids: Collection[int] = frozenset(),
) -> GetFileOutput:
    """Catalog entry of one file with its chunk count, live duplicates and whether its Markdown is cached."""
    row = find_file(conn, path)
    if row["root_id"] in exclude_root_ids:
        raise ToolError("not_found", "File is not in the catalog", {"path": str(path)})
    content_hash = row["content_hash"]
    if not content_hash:
        return GetFileOutput(file=_file_info(row), chunk_count=0, duplicates=[], markdown_cached=False)

    content = conn.execute("SELECT chunk_count FROM contents WHERE content_hash = ?", (content_hash,)).fetchone()
    duplicates = sorted(
        abs_path(dup["path"], dup["rel_path"])
        for dup in conn.execute(
            "SELECT r.path, f.rel_path, f.root_id FROM files f JOIN roots r USING (root_id)"
            " WHERE f.content_hash = ? AND f.file_id != ? AND f.status != 'deleted'",
            (content_hash, row["file_id"]),
        )
        if dup["root_id"] not in exclude_root_ids
    )
    return GetFileOutput(
        file=_file_info(row),
        chunk_count=content["chunk_count"] if content else 0,
        duplicates=duplicates,
        markdown_cached=any(cache_path(cache_dir, content_hash, b).exists() for b in PDF_BACKENDS),
    )
