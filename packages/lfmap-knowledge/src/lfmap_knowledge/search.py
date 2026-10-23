"""Hybrid chunk search and get_context; secret roots never leave on mcp/rest, and what does leave is logged."""

import json
import math
import os
import sqlite3
from collections.abc import Collection
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from lfmap_core import ToolError
from lfmap_knowledge import catalog, fts
from lfmap_knowledge.schemas import (
    ChunkHit,
    Citation,
    ContextChunk,
    GetContextInput,
    GetContextOutput,
    SearchInput,
    SearchOutput,
)

RRF_K = 60
CONTEXT_LIMIT = 20
SNIPPET_CHARS = 300
EGRESS_CHANNELS = ("mcp", "rest")
POOL_FACTOR = 4


class VectorStore(Protocol):
    def search(self, vector: list[float], limit: int) -> list[tuple[int, float]]: ...


class Embedder(Protocol):
    model: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


@dataclass
class _Hit:
    chunk: sqlite3.Row
    file_id: int
    path: str
    duplicates: list[str]
    score: float
    mode: str


def _key(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


def hidden_root_ids(conn: sqlite3.Connection, channel: str, shown_roots: Collection[str] | None = None) -> set[int]:
    """Roots that must not be returned on this channel: the secret roots on mcp and rest, nothing elsewhere.

    With shown_roots (the configured roots that are not secret), mcp and rest also hide every catalog root outside
    it, so a root made secret or dropped from the config is hidden before the next reindex records that.
    """
    if channel not in EGRESS_CHANNELS:
        return set()
    shown = None if shown_roots is None else {_key(path) for path in shown_roots}
    return {
        row["root_id"]
        for row in conn.execute("SELECT root_id, path, sensitivity FROM roots")
        if row["sensitivity"] == "secret" or (shown is not None and _key(row["path"]) not in shown)
    }


def _vector_side(
    store: VectorStore | None, embedder: Embedder | None, query: str, pool: int
) -> list[tuple[int, float]]:
    if embedder is None or store is None:
        detail = {"reason": "no_embedder"}
        raise ToolError("backend_unavailable", "Vector search needs Ollama and a vector store", detail)
    return store.search(embedder.embed([query])[0], pool)


def _rrf(*ranked: list[tuple[int, float]]) -> list[tuple[int, float]]:
    scores: dict[int, float] = {}
    for results in ranked:
        for rank, (chunk_id, _) in enumerate(results, 1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1 / (RRF_K + rank)
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))


def _ranked(
    conn: sqlite3.Connection,
    store: VectorStore | None,
    embedder: Embedder | None,
    query: str,
    mode: str,
    pool: int,
) -> tuple[list[tuple[int, float]], str]:
    if mode == "keyword":
        return fts.keyword_search(conn, query, pool), "keyword"
    if mode == "vector":
        return _vector_side(store, embedder, query, pool), "vector"
    keyword = fts.keyword_search(conn, query, pool)
    try:
        vector = _vector_side(store, embedder, query, pool)
    except ToolError:
        return keyword, "keyword"
    return _rrf(keyword, vector), "hybrid"


def _rows_by_id(conn: sqlite3.Connection, sql: str, ids: list[int], key: str) -> dict:
    if not ids:
        return {}
    rows = conn.execute(sql.format(marks=",".join("?" * len(ids))), ids)
    return {row[key]: row for row in rows}


def _files_by_hash(
    conn: sqlite3.Connection, hashes: list[str], hidden: set[int], root_id: int | None, after_ns: int | None
) -> dict[str, list[tuple[str, str, int]]]:
    """Indexed, visible files per content hash, sorted by (rel_path, root path), as (rel_path, abs path, file_id)."""
    if not hashes:
        return {}
    where = [f"f.content_hash IN ({','.join('?' * len(hashes))})", "f.status = 'indexed'"]
    params: list[object] = list(hashes)
    if root_id is not None:
        where.append("f.root_id = ?")
        params.append(root_id)
    if after_ns is not None:
        where.append("f.mtime_ns > ?")
        params.append(after_ns)
    rows = conn.execute(
        "SELECT f.file_id, f.root_id, f.rel_path, f.content_hash, r.path AS root_path"
        f" FROM files f JOIN roots r USING (root_id) WHERE {' AND '.join(where)}",
        params,
    ).fetchall()
    found: dict[str, list[tuple[str, str, str, int]]] = {}
    for row in rows:
        if row["root_id"] in hidden:
            continue
        entry = (row["rel_path"], row["root_path"], catalog.abs_path(row["root_path"], row["rel_path"]), row["file_id"])
        found.setdefault(row["content_hash"], []).append(entry)
    return {h: [(rel, path, fid) for rel, _, path, fid in sorted(files)] for h, files in found.items()}


def _hits(
    conn: sqlite3.Connection,
    store: VectorStore | None,
    embedder: Embedder | None,
    query: str,
    mode: str,
    limit: int,
    channel: str,
    root: str = "",
    modified_after: str = "",
    shown_roots: Collection[str] | None = None,
) -> list[_Hit]:
    """Best chunks first, each mapped to its visible files; stale chunks and chunks without a file are dropped."""
    hidden = hidden_root_ids(conn, channel, shown_roots)
    root_id = catalog.root_id(conn, root, hidden) if root else None
    after_ns = catalog.after_ns(modified_after) if modified_after else None
    ranked, mode_used = _ranked(conn, store, embedder, query, mode, POOL_FACTOR * limit)
    chunks = _rows_by_id(
        conn,
        "SELECT chunk_id, content_hash, heading_path, char_start, char_end, text FROM chunks"
        " WHERE chunk_id IN ({marks})",
        [int(chunk_id) for chunk_id, _ in ranked],
        "chunk_id",
    )
    files = _files_by_hash(conn, sorted({c["content_hash"] for c in chunks.values()}), hidden, root_id, after_ns)
    hits: list[_Hit] = []
    for chunk_id, score in ranked:
        chunk = chunks.get(int(chunk_id))
        visible = files.get(chunk["content_hash"], []) if chunk is not None else []
        if not visible:
            continue
        (_, path, file_id), *rest = visible
        hits.append(_Hit(chunk, file_id, path, [p for _, p, _ in rest], float(score), mode_used))
        if len(hits) == limit:
            break
    return hits


def _log_egress(conn: sqlite3.Connection, channel: str, operation: str, hits: list[_Hit], texts: list[str]) -> None:
    if channel not in EGRESS_CHANNELS or not hits:
        return
    conn.execute(
        "INSERT INTO egress_log (ts, channel, operation, file_ids, chunk_ids, bytes) VALUES (?, ?, ?, ?, ?, ?)",
        (
            datetime.now(UTC).isoformat(timespec="seconds"),
            channel,
            operation,
            json.dumps([hit.file_id for hit in hits]),
            json.dumps([hit.chunk["chunk_id"] for hit in hits]),
            sum(len(text.encode("utf-8")) for text in texts),
        ),
    )
    conn.commit()


def search(
    conn: sqlite3.Connection,
    store: VectorStore | None,
    embedder: Embedder | None,
    inp: SearchInput,
    channel: str,
    shown_roots: Collection[str] | None = None,
) -> SearchOutput:
    """Ranked chunk hits; hybrid falls back to keyword without Ollama, vector mode does not."""
    hits = _hits(
        conn, store, embedder, inp.query, inp.mode, inp.limit, channel, inp.root, inp.modified_after, shown_roots
    )
    out = [
        ChunkHit(
            path=hit.path,
            heading_path=hit.chunk["heading_path"],
            snippet=hit.chunk["text"][:SNIPPET_CHARS],
            score=hit.score,
            chunk_id=hit.chunk["chunk_id"],
            char_start=hit.chunk["char_start"],
            char_end=hit.chunk["char_end"],
            mode_used=hit.mode,
            duplicates=hit.duplicates,
        )
        for hit in hits
    ]
    _log_egress(conn, channel, "search", hits, [h.snippet for h in out])
    return SearchOutput(query=inp.query, hits=out)


def _tokens(text: str) -> int:
    return math.ceil(len(text) / 3)


def get_context(
    conn: sqlite3.Connection,
    store: VectorStore | None,
    embedder: Embedder | None,
    inp: GetContextInput,
    channel: str,
    shown_roots: Collection[str] | None = None,
) -> GetContextOutput:
    """Hybrid hits packed into token_budget (about 3 characters per token); only the first chunk is ever cut.

    Hits scoring below min_relative_score times the best score are dropped first, so a narrow
    question does not fill the budget with weak matches.
    """
    hits = _hits(conn, store, embedder, inp.question, "hybrid", CONTEXT_LIMIT, channel, inp.root, "", shown_roots)
    if hits and hits[0].score > 0:
        floor = hits[0].score * inp.min_relative_score
        hits = [hit for hit in hits if hit.score >= floor]
    taken: list[_Hit] = []
    chunks: list[ContextChunk] = []
    used = 0
    for i, hit in enumerate(hits):
        text = hit.chunk["text"]
        if used + _tokens(text) > inp.token_budget:
            if i > 0:
                continue
            text = text[: inp.token_budget * 3]
        start = hit.chunk["char_start"]
        citation = Citation(
            path=hit.path, heading_path=hit.chunk["heading_path"], char_start=start, char_end=start + len(text)
        )
        chunks.append(ContextChunk(text=text, citation=citation, score=hit.score))
        taken.append(hit)
        used += _tokens(text)
    _log_egress(conn, channel, "get_context", taken, [c.text for c in chunks])
    return GetContextOutput(question=inp.question, chunks=chunks, estimated_tokens=used)
