"""File edges (GENERATED_FROM, REFERENCES) and related files; link paths are strings only, never opened."""

import posixpath
import re
import sqlite3
from collections.abc import Collection, Iterable
from typing import Protocol
from urllib.parse import unquote

from lfmap_core import ToolError
from lfmap_knowledge.catalog import abs_path
from lfmap_knowledge.schemas import RelatedFile

LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")

REASONS = ("duplicate", "generated_from", "references", "referenced_by", "similar_content", "same_folder")
FIXED_SCORES = {"duplicate": 1.0, "generated_from": 0.9, "references": 0.8, "referenced_by": 0.7, "same_folder": 0.1}
BATCH = 500


class VectorStore(Protocol):
    """The part of the vector store (spec 5.4) that `related` needs."""

    def vector_of(self, chunk_ids: list[int]) -> list[list[float]]: ...

    def search(self, vector: list[float], limit: int) -> list[tuple[int, float]]: ...


def _unsafe(target: str) -> bool:
    return target.startswith(("\\", "/")) or SCHEME_RE.match(target) is not None


def link_targets(markdown: str) -> list[str]:
    """Relative link targets in order; UNC, absolute and scheme links (including drive letters) are dropped."""
    targets = []
    for match in LINK_RE.finditer(markdown):
        target = match.group(1)
        if _unsafe(target):
            continue
        target = unquote(re.split(r"[#?]", target, maxsplit=1)[0]).replace("\\", "/")
        if target and not _unsafe(target):
            targets.append(target)
    return targets


def _file(conn: sqlite3.Connection, file_id: int) -> sqlite3.Row:
    row = conn.execute(
        "SELECT f.*, r.path AS root_path FROM files f JOIN roots r USING (root_id) WHERE f.file_id = ?", (file_id,)
    ).fetchone()
    if row is None:
        raise ToolError("not_found", "File is not in the catalog", {"file_id": file_id})
    return row


def _live_id(conn: sqlite3.Connection, root_id: int, rel_path: str) -> int | None:
    row = conn.execute(
        "SELECT file_id FROM files WHERE root_id = ? AND rel_path = ? AND status != 'deleted'", (root_id, rel_path)
    ).fetchone()
    return None if row is None else row["file_id"]


def _insert(conn: sqlite3.Connection, src: int, rel: str, dst: int, detail: str = "") -> int:
    return conn.execute(
        "INSERT OR IGNORE INTO edges (src_file_id, rel, dst_file_id, detail) VALUES (?, ?, ?, ?)",
        (src, rel, dst, detail),
    ).rowcount


def link_generated_from(conn: sqlite3.Connection, file_id: int) -> int:
    """Link `X.md` to `X` or `X.<ext>` in the same folder, from either side; returns edges newly written."""
    me = _file(conn, file_id)
    folder, name = posixpath.split(me["rel_path"])
    written = 0
    if me["ext"] == ".md":
        stem = name[: -len(".md")]
        prefix = posixpath.join(folder, stem)
        rows = conn.execute(
            "SELECT file_id, rel_path, ext FROM files WHERE root_id = ? AND status != 'deleted' AND file_id != ?"
            " AND (rel_path = ? OR substr(rel_path, 1, ?) = ?)",
            (me["root_id"], file_id, prefix, len(prefix) + 1, prefix + "."),
        )
        for row in rows:
            rest = row["rel_path"][len(prefix) :]
            if rest == "" or (row["ext"] != ".md" and "/" not in rest and "." not in rest[1:]):
                written += _insert(conn, file_id, "GENERATED_FROM", row["file_id"])
    twins = [name + ".md"]
    if me["ext"] != ".md":
        twins.append(posixpath.splitext(name)[0] + ".md")
    for twin in twins:
        twin_id = _live_id(conn, me["root_id"], posixpath.join(folder, twin))
        if twin_id is not None and twin_id != file_id:
            written += _insert(conn, twin_id, "GENERATED_FROM", file_id)
    return written


def link_references(conn: sqlite3.Connection, file_id: int, markdown: str) -> int:
    """Replace the REFERENCES edges of a file with its relative links that resolve inside its root."""
    me = _file(conn, file_id)
    conn.execute("DELETE FROM edges WHERE src_file_id = ? AND rel = 'REFERENCES'", (file_id,))
    folder = posixpath.dirname(me["rel_path"])
    written = 0
    for target in link_targets(markdown):
        rel_path = posixpath.normpath(posixpath.join(folder, target))
        if rel_path in (".", "..") or rel_path.startswith(("../", "/")):
            continue
        dst = _live_id(conn, me["root_id"], rel_path)
        if dst is not None and dst != file_id:
            written += _insert(conn, file_id, "REFERENCES", dst, target)
    return written


def _ids(conn: sqlite3.Connection, sql: str, params: Iterable[object]) -> list[int]:
    return [row[0] for row in conn.execute(sql, tuple(params))]


def _similar(conn: sqlite3.Connection, me: sqlite3.Row, store: VectorStore | None, limit: int) -> dict[int, float]:
    content_hash = me["content_hash"]
    if store is None or not content_hash:
        return {}
    chunk_ids = _ids(conn, "SELECT chunk_id FROM chunks WHERE content_hash = ? ORDER BY ordinal", [content_hash])
    if not chunk_ids:
        return {}
    try:
        vectors = store.vector_of(chunk_ids)
    except ToolError:
        return {}
    if not vectors:
        return {}
    mean = [sum(column) / len(vectors) for column in zip(*vectors, strict=True)]
    best_by_hash: dict[str, float] = {}
    for chunk_id, score in store.search(mean, limit * 3):
        row = conn.execute("SELECT content_hash FROM chunks WHERE chunk_id = ?", (chunk_id,)).fetchone()
        if row is None or row["content_hash"] == content_hash:
            continue
        best_by_hash[row["content_hash"]] = max(score, best_by_hash.get(row["content_hash"], score))
    scores: dict[int, float] = {}
    for other_hash, score in best_by_hash.items():
        for other_id in _ids(conn, "SELECT file_id FROM files WHERE content_hash = ?", [other_hash]):
            scores[other_id] = max(score, scores.get(other_id, score))
    return scores


def _same_folder(conn: sqlite3.Connection, me: sqlite3.Row) -> list[int]:
    folder = posixpath.dirname(me["rel_path"])
    prefix = folder + "/" if folder else ""
    return _ids(
        conn,
        "SELECT file_id FROM files WHERE root_id = ? AND substr(rel_path, 1, ?) = ?"
        " AND instr(substr(rel_path, ?), '/') = 0",
        [me["root_id"], len(prefix), prefix, len(prefix) + 1],
    )


def related(
    conn: sqlite3.Connection,
    file_id: int,
    store: VectorStore | None = None,
    limit: int = 10,
    exclude_root_ids: Collection[int] = frozenset(),
) -> list[RelatedFile]:
    """Related files, each with its strongest reason, sorted by reason, score and path."""
    me = _file(conn, file_id)
    if me["root_id"] in exclude_root_ids:
        raise ToolError("not_found", "File is not in the catalog", {"file_id": file_id})
    sources: dict[str, list[int]] = {
        "duplicate": (
            _ids(conn, "SELECT file_id FROM files WHERE content_hash = ?", [me["content_hash"]])
            if me["content_hash"]
            else []
        ),
        "generated_from": _ids(
            conn,
            "SELECT dst_file_id FROM edges WHERE src_file_id = ? AND rel = 'GENERATED_FROM'"
            " UNION SELECT src_file_id FROM edges WHERE dst_file_id = ? AND rel = 'GENERATED_FROM'",
            [file_id, file_id],
        ),
        "references": _ids(
            conn, "SELECT dst_file_id FROM edges WHERE src_file_id = ? AND rel = 'REFERENCES'", [file_id]
        ),
        "referenced_by": _ids(
            conn, "SELECT src_file_id FROM edges WHERE dst_file_id = ? AND rel = 'REFERENCES'", [file_id]
        ),
        "same_folder": _same_folder(conn, me),
    }
    similar = _similar(conn, me, store, limit)
    best: dict[int, tuple[int, float]] = {}
    for rank, reason in enumerate(REASONS):
        candidates = similar if reason == "similar_content" else dict.fromkeys(sources[reason], FIXED_SCORES[reason])
        for other_id, score in candidates.items():
            if other_id != file_id and other_id not in best:
                best[other_id] = (rank, score)
    results = []
    ids = list(best)
    for start in range(0, len(ids), BATCH):
        batch = ids[start : start + BATCH]
        rows = conn.execute(
            "SELECT f.file_id, f.rel_path, f.root_id, r.path AS root_path FROM files f JOIN roots r USING (root_id)"
            f" WHERE f.status != 'deleted' AND f.file_id IN ({','.join('?' * len(batch))})",
            batch,
        )
        for row in rows:
            if row["root_id"] in exclude_root_ids:
                continue
            rank, score = best[row["file_id"]]
            results.append((rank, -score, row["rel_path"], abs_path(row["root_path"], row["rel_path"])))
    results.sort()
    return [
        RelatedFile(path=path, reason=REASONS[rank], score=-neg_score) for rank, neg_score, _, path in results[:limit]
    ]
