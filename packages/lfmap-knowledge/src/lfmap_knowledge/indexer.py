"""Incremental reindex (spec section 4) and read-only status of the knowledge catalog."""

import os
import sqlite3
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import lancedb

from lfmap_core import ToolContext, ToolError
from lfmap_knowledge import edges, fts
from lfmap_knowledge.chunker import chunk_markdown
from lfmap_knowledge.extract import SkipResult, extract, extractor_version
from lfmap_knowledge.scanner import reconcile
from lfmap_knowledge.schemas import ReindexOutput, RootStatus, StatusOutput
from lfmap_knowledge.store import connect, migrate, writer_lock
from lfmap_knowledge.vectors import LanceVectorStore, model_slug

DEFAULT_EMBED_MODEL = "bge-m3"
MAX_ATTEMPTS = 3
SENSITIVITIES = ("normal", "private", "secret")
Progress = Callable[[str, int, int], None]  # stage ("scan" | "extract" | "embed"), done, total


class Embedder(Protocol):
    model: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


def _key(path: str | os.PathLike[str]) -> str:
    return os.path.normcase(os.path.realpath(path))


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def knowledge_roots(ctx: ToolContext) -> list[Path]:
    """Read roots without data_dir and anything below it, in config order, without duplicates."""
    data = _key(ctx.data_dir) if ctx.data_dir is not None else None
    roots: list[Path] = []
    seen: set[str] = set()
    for root in ctx.permissions.read_roots:
        key = _key(root)
        if key in seen or (data is not None and (key == data or key.startswith(data.rstrip(os.sep) + os.sep))):
            continue
        seen.add(key)
        roots.append(Path(os.path.realpath(root)))
    return roots


def _data_dir(ctx: ToolContext) -> Path:
    if ctx.data_dir is None:
        raise ToolError("internal", "The knowledge plugin needs a data_dir")
    return ctx.data_dir


def _store(data_dir: Path, model: str) -> LanceVectorStore:
    return LanceVectorStore(data_dir / "vectors", f"chunks_{model_slug(model)}")


def _sensitivity(settings: dict[str, Any], root: Path) -> str:
    levels = {os.path.normcase(os.path.normpath(k)): v for k, v in settings.get("sensitivity", {}).items()}
    level = levels.get(os.path.normcase(os.path.normpath(root)), "normal")
    if level not in SENSITIVITIES:
        raise ToolError("invalid_input", "Unknown root sensitivity", {"root": str(root), "sensitivity": level})
    return level


def _sync_roots(conn: sqlite3.Connection, roots: list[Path], settings: dict[str, Any]) -> tuple[dict[str, int], int]:
    """Root ids of the configured roots; files of roots dropped from the config become deleted."""
    ids: dict[str, int] = {}
    for root in roots:
        conn.execute("INSERT OR IGNORE INTO roots (path) VALUES (?)", (str(root),))
        conn.execute("UPDATE roots SET sensitivity = ? WHERE path = ?", (_sensitivity(settings, root), str(root)))
        ids[str(root)] = conn.execute("SELECT root_id FROM roots WHERE path = ?", (str(root),)).fetchone()[0]
    configured = set(ids.values())
    dropped = [row["root_id"] for row in conn.execute("SELECT root_id FROM roots") if row["root_id"] not in configured]
    deleted = 0
    for root_id in dropped:
        deleted += conn.execute(
            "UPDATE files SET status = 'deleted', deleted_at = ? WHERE root_id = ? AND status != 'deleted'",
            (_now(), root_id),
        ).rowcount
    conn.commit()
    return ids, deleted


def _drop_content(conn: sqlite3.Connection, content_hash: str, store: LanceVectorStore | None) -> None:
    fts.delete_content(conn, content_hash)
    conn.execute("DELETE FROM chunks WHERE content_hash = ?", (content_hash,))
    conn.execute("DELETE FROM contents WHERE content_hash = ?", (content_hash,))
    if store is not None:
        store.delete_content(content_hash)


def _reset_all(conn: sqlite3.Connection, vectors_dir: Path) -> None:
    """full=True: drop chunks, FTS, contents and every vector table; the Markdown cache stays."""
    conn.execute("INSERT INTO chunks_fts(chunks_fts) VALUES ('delete-all')")
    conn.execute("DELETE FROM chunks")
    conn.execute("DELETE FROM contents")
    conn.execute("UPDATE files SET status = 'pending', reason_code = '' WHERE status = 'indexed'")
    conn.commit()
    if os.path.isdir(vectors_dir):
        lancedb.connect(vectors_dir).drop_all_tables()


def _store_content(conn: sqlite3.Connection, content_hash: str, result: Any) -> None:
    chunks = chunk_markdown(result.markdown)
    conn.execute(
        "INSERT INTO contents (content_hash, extractor_version, chars, text_quality, chunk_count, indexed_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (content_hash, result.extractor_version, len(result.markdown), result.text_quality, len(chunks), _now()),
    )
    rows = []
    for chunk in chunks:
        cursor = conn.execute(
            "INSERT INTO chunks (content_hash, ordinal, heading_path, char_start, char_end, text)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (content_hash, chunk.ordinal, chunk.heading_path, chunk.char_start, chunk.char_end, chunk.text),
        )
        rows.append((cursor.lastrowid, chunk.text))
    fts.index_chunks(conn, rows)


def _extract_pending(
    ctx: ToolContext, conn: sqlite3.Connection, store: LanceVectorStore | None, config: dict | None, out: dict, progress
) -> list[int]:
    """Extract every pending file; returns the ids of files that became indexed."""
    version = extractor_version()
    cache_dir = ctx.data_dir / "cache" / "md"
    ocr = bool(ctx.settings.get("ocr", False))
    pending = conn.execute(
        "SELECT f.file_id, f.rel_path, f.content_hash, f.attempts, r.path AS root FROM files f"
        " JOIN roots r USING (root_id) WHERE f.status = 'pending' ORDER BY f.file_id"
    ).fetchall()
    indexed: list[int] = []
    for i, row in enumerate(pending, 1):
        file_id, content_hash = row["file_id"], row["content_hash"]
        known = conn.execute(
            "SELECT extractor_version FROM contents WHERE content_hash = ?", (content_hash,)
        ).fetchone()
        try:
            if known is not None and known["extractor_version"] == version:
                result = None
            else:
                path = ctx.permissions.require_read(os.path.join(row["root"], row["rel_path"]))
                result = extract(ctx, path, content_hash, cache_dir, ocr, config)
        except Exception:
            attempts = row["attempts"] + 1
            status = "error" if attempts >= MAX_ATTEMPTS else "pending"
            conn.execute(
                "UPDATE files SET attempts = ?, status = ?, reason_code = ? WHERE file_id = ?",
                (attempts, status, "extract_failed" if status == "error" else "", file_id),
            )
            out["errors"] += 1
        else:
            if isinstance(result, SkipResult):
                conn.execute(
                    "UPDATE files SET status = 'skipped', reason_code = ? WHERE file_id = ?",
                    (result.reason_code, file_id),
                )
                out["skipped"] += 1
            else:
                if result is not None:
                    if known is not None:
                        _drop_content(conn, content_hash, store)
                    _store_content(conn, content_hash, result)
                    edges.link_references(conn, file_id, result.markdown)
                    out["extracted"] += 1
                conn.execute("UPDATE files SET status = 'indexed', reason_code = '' WHERE file_id = ?", (file_id,))
                indexed.append(file_id)
        conn.commit()
        if progress:
            progress("extract", i, len(pending))
    return indexed


def _collect_garbage(conn: sqlite3.Connection, store: LanceVectorStore) -> None:
    conn.execute(
        "DELETE FROM edges WHERE src_file_id IN (SELECT file_id FROM files WHERE status = 'deleted')"
        " OR dst_file_id IN (SELECT file_id FROM files WHERE status = 'deleted')"
    )
    orphans = conn.execute(
        "SELECT content_hash FROM contents c WHERE NOT EXISTS"
        " (SELECT 1 FROM files f WHERE f.content_hash = c.content_hash AND f.status != 'deleted')"
    ).fetchall()
    for row in orphans:
        _drop_content(conn, row["content_hash"], store if store.exists() else None)
    conn.commit()


def _embed(conn: sqlite3.Connection, embedder: Embedder, store: LanceVectorStore, out: dict, progress) -> None:
    if store.exists():
        todo = conn.execute(
            "SELECT content_hash FROM contents WHERE embedded_at IS NULL OR embed_model IS NOT ? ORDER BY content_hash",
            (embedder.model,),
        ).fetchall()
    else:
        todo = conn.execute("SELECT content_hash FROM contents ORDER BY content_hash").fetchall()
    for i, row in enumerate(todo, 1):
        content_hash = row["content_hash"]
        chunks = conn.execute(
            "SELECT chunk_id, text FROM chunks WHERE content_hash = ? ORDER BY ordinal", (content_hash,)
        ).fetchall()
        try:
            vectors = embedder.embed([chunk["text"] for chunk in chunks])
            store.upsert([chunk["chunk_id"] for chunk in chunks], [content_hash] * len(chunks), vectors)
        except ToolError as error:
            out["embed_skipped_reason"] = error.details.get("reason", error.code)
            break
        conn.execute(
            "UPDATE contents SET embed_model = ?, embedded_at = ? WHERE content_hash = ?",
            (embedder.model, _now(), content_hash),
        )
        conn.commit()
        out["embedded"] += 1
        if progress:
            progress("embed", i, len(todo))
    store.optimize()


def reindex(
    ctx: ToolContext,
    embedder: Embedder | None,
    root: str = "",
    full: bool = False,
    progress: Progress | None = None,
    config: dict | None = None,
) -> ReindexOutput:
    """Bring catalog, chunks, FTS and vectors in line with the knowledge roots; writes only under data_dir."""
    started = time.monotonic()
    roots = knowledge_roots(ctx)
    targets = roots
    if root:
        wanted = _key(ctx.permissions.require_read(root))
        targets = [r for r in roots if _key(r) == wanted]
        if not targets:
            raise ToolError("invalid_input", "root is not a knowledge root", {"root": root})

    data_dir = _data_dir(ctx)
    data_dir.mkdir(parents=True, exist_ok=True)
    out: dict[str, Any] = dict.fromkeys(
        ("scanned", "new", "changed", "unchanged", "deleted", "skipped", "extracted", "embedded", "errors"), 0
    )
    out["embed_skipped_reason"] = ""
    with writer_lock(data_dir):
        conn = connect(data_dir / "catalog.db")
        try:
            migrate(conn)
            root_ids, out["deleted"] = _sync_roots(conn, roots, ctx.settings)
            model = embedder.model if embedder is not None else ctx.settings.get("embed_model", DEFAULT_EMBED_MODEL)
            store = _store(data_dir, model)
            if full:
                _reset_all(conn, data_dir / "vectors")
            version = extractor_version()
            conn.execute(
                "UPDATE files SET status = 'pending' WHERE status = 'indexed' AND content_hash IN"
                " (SELECT content_hash FROM contents WHERE extractor_version != ?)",
                (version,),
            )
            conn.commit()
            before = {r["file_id"]: (r["status"], r["content_hash"]) for r in conn.execute("SELECT * FROM files")}

            for i, target in enumerate(targets, 1):
                if os.path.isdir(target):
                    stats = reconcile(conn, root_ids[str(target)], target, ctx.permissions, ctx.settings, version)
                    out["scanned"] += stats.seen
                    for name in ("new", "changed", "unchanged", "deleted", "skipped"):
                        out[name] += getattr(stats, name)
                else:
                    out["errors"] += 1
                if progress:
                    progress("scan", i, len(targets))

            linked = set(_extract_pending(ctx, conn, store, config, out, progress))
            for r in conn.execute("SELECT file_id, status, content_hash FROM files WHERE status = 'indexed'"):
                if before.get(r["file_id"]) != ("indexed", r["content_hash"]):
                    linked.add(r["file_id"])
            for file_id in sorted(linked):
                edges.link_generated_from(conn, file_id)
            conn.commit()
            _collect_garbage(conn, store)

            if embedder is None:
                out["embed_skipped_reason"] = "no_embedder"
            else:
                _embed(conn, embedder, store, out, progress)
        finally:
            conn.close()
    return ReindexOutput(**out, duration_s=round(time.monotonic() - started, 3))


def _indexer_busy(data_dir: Path) -> bool:
    if not os.path.isdir(data_dir):
        return False
    try:
        with writer_lock(data_dir):
            return False
    except ToolError:
        return True


def status(ctx: ToolContext, ollama_available: bool) -> StatusOutput:
    """Counts from a read-only catalog connection; never takes the writer lock for longer than a probe."""
    data_dir = _data_dir(ctx)
    roots: list[RootStatus] = []
    by_status: dict[str, int] = {}
    chunks = 0
    db_path = data_dir / "catalog.db"
    if os.path.isfile(db_path):
        conn = connect(db_path, readonly=True)
        try:
            rows = conn.execute(
                "SELECT r.path, r.sensitivity, r.last_scan, COUNT(f.file_id) AS files FROM roots r"
                " LEFT JOIN files f ON f.root_id = r.root_id AND f.status != 'deleted'"
                " GROUP BY r.root_id ORDER BY r.path"
            )
            roots = [
                RootStatus(
                    path=r["path"], sensitivity=r["sensitivity"], last_scan=r["last_scan"] or "", files=r["files"]
                )
                for r in rows
            ]
            by_status = dict(conn.execute("SELECT status, COUNT(*) FROM files GROUP BY status").fetchall())
            chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        finally:
            conn.close()
    return StatusOutput(
        roots=roots,
        files_by_status=by_status,
        chunks=chunks,
        embed_model=ctx.settings.get("embed_model", DEFAULT_EMBED_MODEL),
        ollama_available=ollama_available,
        indexer_busy=_indexer_busy(data_dir),
    )
