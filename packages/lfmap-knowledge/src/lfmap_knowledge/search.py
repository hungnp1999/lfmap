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
    relevance: float


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


def _normalized(results: list[tuple[int, float]]) -> dict[int, float]:
    """Min-max scaled scores of one result list: 1 for the best candidate, 0 for the weakest in the pool."""
    if not results:
        return {}
    top = max(score for _, score in results)
    span = top - min(score for _, score in results)
    return {chunk_id: (score - top) / span + 1 if span > 0 else 1.0 for chunk_id, score in results}


def _relevance(*ranked: list[tuple[int, float]]) -> dict[int, float]:
    """Best min-max scaled score per chunk across the lists; RRF scores are too flat to cut on (L23)."""
    best: dict[int, float] = {}
    for results in ranked:
        for chunk_id, value in _normalized(results).items():
            best[chunk_id] = max(best.get(chunk_id, 0.0), value)
    return best


def _ranked(
    conn: sqlite3.Connection,
    store: VectorStore | None,
    embedder: Embedder | None,
    query: str,
    mode: str,
    pool: int,
) -> tuple[list[tuple[int, float]], str, list[list[tuple[int, float]]]]:
    """The merged ranking, the mode used and the lists it was merged from."""
    if mode == "keyword":
        keyword = fts.keyword_search(conn, query, pool)
        return keyword, "keyword", [keyword]
    if mode == "vector":
        vector = _vector_side(store, embedder, query, pool)
        return vector, "vector", [vector]
    keyword = fts.keyword_search(conn, query, pool)
    try:
        vector = _vector_side(store, embedder, query, pool)
    except ToolError:
        return keyword, "keyword", [keyword]
    return _rrf(keyword, vector), "hybrid", [keyword, vector]


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
    """Best chunks first, each mapped to its visible files; stale chunks and chunks without a file are dropped.

    Relevance is scaled over the visible candidates only, so hidden chunks cannot change what is kept.
    """
    hidden = hidden_root_ids(conn, channel, shown_roots)
    root_id = catalog.root_id(conn, root, hidden) if root else None
    after_ns = catalog.after_ns(modified_after) if modified_after else None
    ranked, mode_used, sides = _ranked(conn, store, embedder, query, mode, POOL_FACTOR * limit)
    chunks = _rows_by_id(
        conn,
        "SELECT chunk_id, content_hash, heading_path, char_start, char_end, text FROM chunks"
        " WHERE chunk_id IN ({marks})",
        [int(chunk_id) for chunk_id, _ in ranked],
        "chunk_id",
    )
    files = _files_by_hash(conn, sorted({c["content_hash"] for c in chunks.values()}), hidden, root_id, after_ns)
    visible = {
        chunk_id: files[chunk["content_hash"]] for chunk_id, chunk in chunks.items() if chunk["content_hash"] in files
    }
    relevance = _relevance(*([(int(c), s) for c, s in side if int(c) in visible] for side in sides))
    hits: list[_Hit] = []
    for chunk_id, score in ranked:
        chunk_id = int(chunk_id)
        if chunk_id not in visible:
            continue
        (_, path, file_id), *rest = visible[chunk_id]
        duplicates = [p for _, p, _ in rest]
        hits.append(_Hit(chunks[chunk_id], file_id, path, duplicates, float(score), mode_used, relevance[chunk_id]))
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

    A hit is kept only if, in its keyword or vector list, it scores at least min_relative_score of the way from
    the weakest candidate in the pool to the best, so a narrow question does not fill the budget with weak matches.
    """
    hits = _hits(conn, store, embedder, inp.question, "hybrid", CONTEXT_LIMIT, channel, inp.root, "", shown_roots)
    hits = [hit for hit in hits if hit.relevance >= inp.min_relative_score]
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
