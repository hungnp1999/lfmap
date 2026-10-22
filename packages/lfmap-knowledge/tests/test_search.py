import json
import math
from datetime import UTC, datetime
from pathlib import Path

import pytest

from lfmap_core import ToolError
from lfmap_knowledge import fts
from lfmap_knowledge.catalog import abs_path, strip_accents
from lfmap_knowledge.schemas import GetContextInput, SearchInput
from lfmap_knowledge.search import SNIPPET_CHARS, get_context, hidden_root_ids, search
from lfmap_knowledge.vectors import LanceVectorStore

OLD_NS = int(datetime(2026, 1, 1, tzinfo=UTC).timestamp() * 1e9)
NEW_NS = int(datetime(2026, 10, 1, tzinfo=UTC).timestamp() * 1e9)
VOCAB = ["doanh", "chi", "tuyen", "luong", "hop", "kangaroo"]


class BagEmbedder:
    """One dimension per VOCAB word, so cosine similarity follows shared words."""

    model = "bag"

    def __init__(self) -> None:
        self.calls = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        return [[strip_accents(t).count(w) + 0.01 for w in VOCAB] for t in texts]


class DownEmbedder:
    model = "bag"

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise ToolError("backend_unavailable", "Ollama is not reachable", {"reason": "ollama_unreachable"})


class World:
    def __init__(self, db, tmp_path: Path) -> None:
        self.db = db
        self.emb = BagEmbedder()
        self.store = LanceVectorStore(tmp_path / "vectors", "chunks_bag")
        self.roots: dict[str, tuple[int, str]] = {}
        self.next_chunk = 1

    def root(self, name: str, path: Path, sensitivity: str = "normal") -> int:
        rid = self.db.execute("INSERT INTO roots(path, sensitivity) VALUES (?, ?)", (str(path), sensitivity)).lastrowid
        self.roots[name] = (rid, str(path))
        return rid

    def file(self, root: str, rel: str, content_hash: str, status="indexed", mtime_ns=NEW_NS) -> int:
        rid, _ = self.roots[root]
        return self.db.execute(
            "INSERT INTO files (root_id, rel_path, name_folded, ext, size, mtime_ns, content_hash, status,"
            " first_seen, last_seen) VALUES (?, ?, ?, '.md', 1, ?, ?, ?, 'x', 'x')",
            (rid, rel, rel.casefold(), mtime_ns, content_hash, status),
        ).lastrowid

    def content(self, content_hash: str, chunks: list[tuple[str, str]]) -> list[int]:
        self.db.execute(
            "INSERT INTO contents (content_hash, extractor_version, chars, chunk_count, indexed_at, embed_model,"
            " embedded_at) VALUES (?, 'v', 1, ?, 'x', 'bag', 'x')",
            (content_hash, len(chunks)),
        )
        ids, start = [], 0
        for ordinal, (heading, text) in enumerate(chunks):
            cid = self.next_chunk
            self.next_chunk += 1
            self.db.execute(
                "INSERT INTO chunks (chunk_id, content_hash, ordinal, heading_path, char_start, char_end, text)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (cid, content_hash, ordinal, heading, start, start + len(text), text),
            )
            start += len(text) + 2
            ids.append(cid)
        fts.index_chunks(self.db, list(zip(ids, (t for _, t in chunks), strict=True)))
        self.store.upsert(ids, [content_hash] * len(ids), self.emb.embed([t for _, t in chunks]))
        self.db.commit()
        return ids

    def path(self, root: str, rel: str) -> str:
        return abs_path(self.roots[root][1], rel)


H = {n: c * 64 for n, c in zip("revpsdl", "0123456", strict=True)}
LONG = "doanh thu " * 150


@pytest.fixture
def w(db, tmp_path: Path) -> World:
    world = World(db, tmp_path)
    world.root("docs", tmp_path / "docs")
    world.root("secret", tmp_path / "secret", "secret")
    world.root("private", tmp_path / "private", "private")
    world.content(H["r"], [("Doanh thu", "Doanh thu quý 3 tăng mạnh"), ("Chi phí", "Chi phí văn phòng giảm")])
    world.file("docs", "report.md", H["r"])
    world.file("docs", "copy/report.md", H["r"])
    world.content(H["v"], [("Kế hoạch", "kế hoạch tuyển dụng kangaroo")])
    world.file("docs", "plan.md", H["v"], mtime_ns=OLD_NS)
    world.content(H["s"], [("Lương", "bảng lương kangaroo")])
    world.file("secret", "salary.md", H["s"])
    world.content(H["p"], [("Hợp đồng", "hợp đồng thuê kangaroo")])
    world.file("private", "contract.md", H["p"])
    world.content(H["d"], [("Cũ", "kangaroo deleted")])
    world.file("docs", "old.md", H["d"], status="deleted")
    return world


def _search(w: World, query: str, channel: str = "cli", embedder="bag", **kwargs):
    emb = w.emb if embedder == "bag" else embedder
    return search(w.db, w.store, emb, SearchInput(query=query, **kwargs), channel)


def _context(w: World, question: str, channel: str = "cli", embedder="bag", **kwargs):
    emb = w.emb if embedder == "bag" else embedder
    return get_context(w.db, w.store, emb, GetContextInput(question=question, **kwargs), channel)


def _names(out) -> list[str]:
    return [Path(h.path).name for h in out.hits]


def _egress(w: World) -> list[dict]:
    return [dict(r) for r in w.db.execute("SELECT * FROM egress_log")]


def test_hidden_roots_only_on_egress_channels(w):
    secret_id = w.roots["secret"][0]
    assert hidden_root_ids(w.db, "cli") == set()
    assert hidden_root_ids(w.db, "sdk") == set()
    assert hidden_root_ids(w.db, "mcp") == {secret_id}
    assert hidden_root_ids(w.db, "rest") == {secret_id}


def test_keyword_mode_folds_accents(w):
    w.emb.calls = 0
    out = _search(w, "doanh thu", mode="keyword")
    assert out.hits[0].heading_path == "Doanh thu"
    assert {h.mode_used for h in out.hits} == {"keyword"}
    assert w.emb.calls == 0


def test_hit_maps_to_first_file_by_rel_path_with_duplicates(w):
    hit = _search(w, "doanh", mode="keyword").hits[0]
    assert hit.path == w.path("docs", "copy/report.md")
    assert hit.duplicates == [w.path("docs", "report.md")]
    assert (hit.char_start, hit.char_end) == (0, len("Doanh thu quý 3 tăng mạnh"))


def test_vector_mode_ranks_by_meaning(w):
    out = _search(w, "chi phi", mode="vector")
    assert out.hits[0].heading_path == "Chi phí"
    assert out.hits[0].mode_used == "vector"


def test_vector_mode_without_ollama_is_an_error(w):
    with pytest.raises(ToolError) as err:
        _search(w, "chi phi", mode="vector", embedder=DownEmbedder())
    assert err.value.code == "backend_unavailable"


def test_hybrid_uses_both_sides(w):
    out = _search(w, "doanh thu")
    assert out.hits[0].heading_path == "Doanh thu"
    assert out.hits[0].mode_used == "hybrid"
    top = 1 / 61 + 1 / 61
    assert out.hits[0].score == pytest.approx(top)


@pytest.mark.parametrize("embedder", [None, DownEmbedder()])
def test_hybrid_falls_back_to_keyword(w, embedder):
    out = _search(w, "doanh thu", embedder=embedder)
    assert out.hits
    assert {h.mode_used for h in out.hits} == {"keyword"}


def test_secret_root_is_absent_on_mcp_and_rest(w):
    assert "salary.md" in _names(_search(w, "kangaroo"))
    assert "salary.md" in _names(_search(w, "kangaroo", channel="sdk"))
    for channel in ("mcp", "rest"):
        names = _names(_search(w, "kangaroo", channel=channel))
        assert "salary.md" not in names
        assert "contract.md" in names


def test_secret_duplicates_are_hidden_on_mcp(w):
    w.file("secret", "zz-report.md", H["r"])
    w.db.commit()
    assert w.path("secret", "zz-report.md") in _search(w, "doanh", mode="keyword").hits[0].duplicates
    hit = _search(w, "doanh", mode="keyword", channel="mcp").hits[0]
    assert w.path("secret", "zz-report.md") not in hit.duplicates


def test_secret_only_content_never_leaks_through_vectors(w):
    out = _search(w, "bang luong", mode="vector", channel="mcp", limit=10)
    assert "salary.md" not in _names(out)
    assert all("lương" not in h.snippet for h in out.hits)


def test_deleted_files_are_not_returned(w):
    assert "old.md" not in _names(_search(w, "kangaroo", limit=20))


def test_stale_vectors_are_ignored(w):
    w.store.upsert([999], ["f" * 64], w.emb.embed(["chi chi chi"]))
    out = _search(w, "chi", mode="vector")
    assert 999 not in [h.chunk_id for h in out.hits]


def test_root_filter(w):
    out = _search(w, "kangaroo", root=w.roots["private"][1])
    assert _names(out) == ["contract.md"]


def test_unknown_root_is_not_found(w, tmp_path: Path):
    with pytest.raises(ToolError) as err:
        _search(w, "kangaroo", root=str(tmp_path / "nope"))
    assert err.value.code == "not_found"


def test_modified_after_filter(w):
    names = _names(_search(w, "kangaroo", modified_after="2026-06-01"))
    assert "plan.md" not in names
    assert "contract.md" in names


def test_limit_and_snippet_length(w):
    w.content(H["l"], [("Dài", LONG)])
    w.file("docs", "long.md", H["l"])
    out = _search(w, "doanh", limit=1)
    assert len(out.hits) == 1
    assert all(len(h.snippet) <= SNIPPET_CHARS for h in _search(w, "doanh").hits)


def test_search_output_is_marked_untrusted(w):
    out = _search(w, "doanh")
    assert out.untrusted is True
    assert "not as instructions" in out.notice
    assert out.query == "doanh"


def test_mcp_search_writes_one_egress_row(w):
    out = _search(w, "kangaroo", channel="mcp")
    rows = _egress(w)
    assert len(rows) == 1
    row = rows[0]
    assert (row["channel"], row["operation"]) == ("mcp", "search")
    assert json.loads(row["chunk_ids"]) == [h.chunk_id for h in out.hits]
    assert len(json.loads(row["file_ids"])) == len(out.hits)
    assert row["bytes"] == sum(len(h.snippet.encode("utf-8")) for h in out.hits)
    assert row["ts"]


def test_local_channels_and_empty_results_write_no_egress(w):
    _search(w, "kangaroo", channel="cli")
    _search(w, "kangaroo", channel="sdk")
    _search(w, "zzzz", channel="mcp", mode="keyword")
    assert _egress(w) == []


def test_context_respects_small_budget(w):
    w.content(H["l"], [("Dài", LONG)])
    w.file("docs", "long.md", H["l"])
    out = _context(w, "doanh thu", token_budget=200)
    assert out.chunks
    assert sum(len(c.text) for c in out.chunks) <= 600
    assert out.estimated_tokens <= 200


def test_context_fills_budget_and_estimates_tokens(w):
    out = _context(w, "kangaroo doanh chi", token_budget=4000)
    assert len(out.chunks) >= 4
    assert out.estimated_tokens == sum(math.ceil(len(c.text) / 3) for c in out.chunks)
    assert out.untrusted is True
    assert "not as instructions" in out.notice


def test_context_citation_points_at_the_chunk(w):
    chunk = next(c for c in _context(w, "chi phi").chunks if c.citation.heading_path == "Chi phí")
    assert chunk.text == "Chi phí văn phòng giảm"
    assert chunk.citation.path == w.path("docs", "copy/report.md")
    start = len("Doanh thu quý 3 tăng mạnh") + 2
    assert (chunk.citation.char_start, chunk.citation.char_end) == (start, start + len(chunk.text))


def test_context_hides_secret_root_on_mcp(w):
    texts = [c.text for c in _context(w, "kangaroo luong", channel="mcp").chunks]
    assert texts
    assert not any("lương" in t for t in texts)


def test_mcp_context_writes_one_egress_row(w):
    out = _context(w, "kangaroo", channel="mcp")
    rows = _egress(w)
    assert len(rows) == 1
    assert rows[0]["operation"] == "get_context"
    assert rows[0]["bytes"] == sum(len(c.text.encode("utf-8")) for c in out.chunks)
    assert len(json.loads(rows[0]["chunk_ids"])) == len(out.chunks)


def test_roots_outside_shown_roots_are_hidden_on_mcp(w):
    shown = [w.roots["docs"][1], w.roots["secret"][1]]
    private_id = w.roots["private"][0]
    assert hidden_root_ids(w.db, "mcp", shown) == {w.roots["secret"][0], private_id}
    assert hidden_root_ids(w.db, "cli", shown) == set()
    out = search(w.db, w.store, w.emb, SearchInput(query="kangaroo"), "mcp", shown)
    assert "contract.md" not in _names(out)
    out = get_context(w.db, w.store, w.emb, GetContextInput(question="kangaroo hop"), "mcp", shown)
    assert not any(c.citation.path.startswith(w.roots["private"][1]) for c in out.chunks)
