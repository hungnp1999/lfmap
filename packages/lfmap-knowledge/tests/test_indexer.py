import hashlib
import os
import shutil
from pathlib import Path

import pytest

from lfmap_core import ToolContext, ToolError
from lfmap_core.permissions import PermissionManager
from lfmap_knowledge import indexer
from lfmap_knowledge.fts import keyword_search
from lfmap_knowledge.indexer import knowledge_roots, reindex, status
from lfmap_knowledge.store import connect, writer_lock
from lfmap_knowledge.vectors import LanceVectorStore, model_slug
from lfmap_markitdown.tool import MarkitdownTool


class FakeEmbedder:
    """Deterministic 8-dim vectors; counts every text it embeds."""

    def __init__(self, model: str = "fake-model") -> None:
        self.model = model
        self.texts: list[str] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.texts.extend(texts)
        return [[b / 255 + 0.01 for b in hashlib.blake2b(t.encode(), digest_size=8).digest()] for t in texts]


class DownEmbedder:
    model = "fake-model"

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise ToolError("backend_unavailable", "Ollama is not reachable", {"reason": "ollama_unreachable"})


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _later(path: Path, text: str) -> None:
    before = path.stat()
    path.write_text(text, encoding="utf-8")
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + 2_000_000_000))


@pytest.fixture
def docs(root: Path) -> Path:
    _write(root / "a.md", "# Alpha\n\nkangaroo report.\n\nSee [b](b.txt).\n")
    _write(root / "b.txt", "platypus notes\n")
    _write(root / "sub" / "c.md", "# Gamma\n\nwombat minutes\n")
    _write(root / "x.zzz", "not a document")
    return root


@pytest.fixture
def ctx(perms: PermissionManager, data_dir: Path) -> ToolContext:
    return ToolContext(plugin_id="knowledge", permissions=perms, data_dir=data_dir, settings={})


@pytest.fixture
def emb() -> FakeEmbedder:
    return FakeEmbedder()


@pytest.fixture
def converts(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []
    original = MarkitdownTool.convert

    def counting(self, inp):
        seen.append(Path(inp.path).name)
        return original(self, inp)

    monkeypatch.setattr(MarkitdownTool, "convert", counting)
    return seen


def _run(ctx: ToolContext, embedder=None, **kwargs):
    return reindex(ctx, embedder, config={}, **kwargs)


def _db(data_dir: Path):
    return connect(data_dir / "catalog.db")


def _store(data_dir: Path, model: str = "fake-model") -> LanceVectorStore:
    return LanceVectorStore(data_dir / "vectors", f"chunks_{model_slug(model)}")


def _count(data_dir: Path, sql: str) -> int:
    conn = _db(data_dir)
    try:
        return conn.execute(sql).fetchone()[0]
    finally:
        conn.close()


def _files(data_dir: Path) -> dict[str, dict]:
    conn = _db(data_dir)
    try:
        return {r["rel_path"]: dict(r) for r in conn.execute("SELECT * FROM files")}
    finally:
        conn.close()


def _finds(data_dir: Path, word: str) -> bool:
    conn = _db(data_dir)
    try:
        return bool(keyword_search(conn, word, 5))
    finally:
        conn.close()


def test_knowledge_roots_leave_out_data_dir(ctx, root: Path):
    assert knowledge_roots(ctx) == [root]


def test_first_run_extracts_chunks_and_embeds(ctx, docs, data_dir: Path, emb):
    out = _run(ctx, emb)
    assert (out.scanned, out.new, out.skipped, out.extracted, out.embedded, out.errors) == (4, 4, 1, 3, 3, 0)
    assert out.embed_skipped_reason == ""
    assert _count(data_dir, "SELECT COUNT(*) FROM contents") == 3
    chunks = _count(data_dir, "SELECT COUNT(*) FROM chunks")
    assert chunks >= 3
    assert _store(data_dir).count() == chunks
    assert {k: v["status"] for k, v in _files(data_dir).items()} == {
        "a.md": "indexed",
        "b.txt": "indexed",
        "sub/c.md": "indexed",
        "x.zzz": "skipped",
    }
    assert _finds(data_dir, "wombat")


def test_second_run_extracts_and_embeds_nothing(ctx, docs, emb, converts):
    _run(ctx, emb)
    converts.clear()
    emb.texts.clear()
    out = _run(ctx, emb)
    assert (out.new, out.changed, out.unchanged, out.extracted, out.embedded) == (0, 0, 4, 0, 0)
    assert converts == []
    assert emb.texts == []


def test_deleting_vectors_folder_reembeds_without_extracting(ctx, docs, data_dir: Path, emb, converts):
    _run(ctx, emb)
    chunks = _count(data_dir, "SELECT COUNT(*) FROM chunks")
    shutil.rmtree(data_dir / "vectors")
    converts.clear()
    out = _run(ctx, emb)
    assert (out.extracted, out.embedded) == (0, 3)
    assert converts == []
    assert _store(data_dir).count() == chunks


def test_identical_files_share_one_content(ctx, root: Path, data_dir: Path, emb):
    _write(root / "one.md", "# Same\n\nidentical text\n")
    _write(root / "copy" / "one.md", "# Same\n\nidentical text\n")
    out = _run(ctx, emb)
    assert (out.extracted, out.embedded) == (1, 1)
    assert _count(data_dir, "SELECT COUNT(*) FROM contents") == 1
    assert {v["status"] for v in _files(data_dir).values()} == {"indexed"}


def test_without_embedder_index_is_keyword_only(ctx, docs, data_dir: Path, emb):
    out = _run(ctx, None)
    assert (out.extracted, out.embedded, out.embed_skipped_reason) == (3, 0, "no_embedder")
    assert _finds(data_dir, "platypus")
    assert _run(ctx, emb).embedded == 3


def test_ollama_down_is_not_an_error(ctx, docs, data_dir: Path, emb):
    out = _run(ctx, DownEmbedder())
    assert (out.extracted, out.embedded, out.errors) == (3, 0, 0)
    assert out.embed_skipped_reason == "ollama_unreachable"
    assert _count(data_dir, "SELECT COUNT(*) FROM contents WHERE embedded_at IS NOT NULL") == 0
    assert _run(ctx, emb).embedded == 3


def test_new_embed_model_reembeds_into_its_own_table(ctx, docs, data_dir: Path, emb):
    _run(ctx, emb)
    other = FakeEmbedder("other/model:v2")
    assert _run(ctx, other).embedded == 3
    assert _store(data_dir, "other/model:v2").count() == _count(data_dir, "SELECT COUNT(*) FROM chunks")


def test_changed_file_replaces_its_old_content(ctx, docs, data_dir: Path, emb):
    _run(ctx, emb)
    _later(docs / "b.txt", "echidna notes\n")
    out = _run(ctx, emb)
    assert (out.changed, out.extracted, out.embedded) == (1, 1, 1)
    assert _count(data_dir, "SELECT COUNT(*) FROM contents") == 3
    assert _store(data_dir).count() == _count(data_dir, "SELECT COUNT(*) FROM chunks")
    assert _finds(data_dir, "echidna")
    assert not _finds(data_dir, "platypus")


def test_deleted_file_is_garbage_collected(ctx, docs, data_dir: Path, emb):
    _run(ctx, emb)
    (docs / "sub" / "c.md").unlink()
    out = _run(ctx, emb)
    assert out.deleted == 1
    assert _files(data_dir)["sub/c.md"]["status"] == "deleted"
    assert _count(data_dir, "SELECT COUNT(*) FROM contents") == 2
    assert _store(data_dir).count() == _count(data_dir, "SELECT COUNT(*) FROM chunks")
    assert not _finds(data_dir, "wombat")


def test_root_dropped_from_config_marks_its_files_deleted(ctx, docs, data_dir: Path, tmp_path: Path, emb):
    _run(ctx, emb)
    other = tmp_path / "other"
    _write(other / "d.md", "dingo\n")
    narrow = ToolContext(
        plugin_id="knowledge",
        permissions=PermissionManager([str(other)], [str(data_dir)]),
        data_dir=data_dir,
        settings={},
    )
    out = _run(narrow, emb)
    assert out.deleted == 4
    assert _count(data_dir, "SELECT COUNT(*) FROM contents") == 1
    assert _finds(data_dir, "dingo")
    assert not _finds(data_dir, "kangaroo")


def test_missing_root_folder_deletes_nothing(ctx, docs, data_dir: Path, emb):
    _run(ctx, emb)
    shutil.rmtree(docs)
    out = _run(ctx, emb)
    assert out.errors == 1
    assert out.deleted == 0
    assert _files(data_dir)["a.md"]["status"] == "indexed"


def test_root_argument_limits_the_scan(ctx, docs, data_dir: Path, tmp_path: Path, emb):
    other = tmp_path / "other"
    _write(other / "d.md", "dingo\n")
    wide = ToolContext(
        plugin_id="knowledge",
        permissions=PermissionManager([str(docs), str(other)], [str(data_dir)]),
        data_dir=data_dir,
        settings={},
    )
    out = _run(wide, emb, root=str(other))
    assert (out.scanned, out.extracted) == (1, 1)


def test_root_argument_must_be_a_knowledge_root(ctx, docs, emb):
    with pytest.raises(ToolError) as err:
        _run(ctx, emb, root=str(docs / "sub"))
    assert err.value.code == "invalid_input"


def test_second_writer_gets_indexer_busy(ctx, docs, data_dir: Path, emb):
    with writer_lock(data_dir):
        with pytest.raises(ToolError) as err:
            _run(ctx, emb)
    assert err.value.code == "backend_unavailable"
    assert err.value.details["reason"] == "indexer_busy"


def test_markitdown_refusal_becomes_skip_reason(ctx, root: Path, data_dir: Path, emb):
    _write(root / "old.rtf", "{\\rtf1 hello}")
    out = _run(ctx, emb)
    assert out.skipped == 1
    row = _files(data_dir)["old.rtf"]
    assert (row["status"], row["reason_code"]) == ("skipped", "office_gui_only")


def test_extract_failure_is_retried_then_marked_error(ctx, docs, data_dir: Path, emb, monkeypatch):
    real = indexer.extract

    def flaky(tool_ctx, path, *args, **kwargs):
        if path.name == "b.txt":
            raise RuntimeError("boom")
        return real(tool_ctx, path, *args, **kwargs)

    monkeypatch.setattr(indexer, "extract", flaky)
    assert _run(ctx, emb).errors == 1
    assert _files(data_dir)["b.txt"]["status"] == "pending"
    _run(ctx, emb)
    _run(ctx, emb)
    row = _files(data_dir)["b.txt"]
    assert (row["status"], row["attempts"]) == ("error", 3)
    assert _run(ctx, emb).errors == 0


def test_full_rebuilds_from_markdown_cache(ctx, docs, data_dir: Path, emb, converts):
    _run(ctx, emb)
    chunks = _count(data_dir, "SELECT COUNT(*) FROM chunks")
    converts.clear()
    out = _run(ctx, emb, full=True)
    assert (out.extracted, out.embedded) == (3, 3)
    assert converts == []
    assert _count(data_dir, "SELECT COUNT(*) FROM chunks") == chunks
    assert _store(data_dir).count() == chunks
    assert _finds(data_dir, "kangaroo")


def test_progress_reports_each_stage(ctx, docs, emb):
    events: list[tuple[str, int, int]] = []
    _run(ctx, emb, progress=lambda stage, done, total: events.append((stage, done, total)))
    assert ("extract", 3, 3) in events
    assert ("embed", 3, 3) in events
    assert {stage for stage, _, _ in events} >= {"scan", "extract", "embed"}


def test_edges_are_written_for_indexed_files(ctx, root: Path, data_dir: Path, emb):
    _write(root / "a.md", "See [b](b.txt).\n")
    _write(root / "b.txt", "bee\n")
    _write(root / "b.txt.md", "bee as markdown\n")
    _run(ctx, emb)
    ids = {k: v["file_id"] for k, v in _files(data_dir).items()}
    conn = _db(data_dir)
    edges = {(r[0], r[1], r[2]) for r in conn.execute("SELECT src_file_id, rel, dst_file_id FROM edges")}
    conn.close()
    assert (ids["a.md"], "REFERENCES", ids["b.txt"]) in edges
    assert (ids["b.txt.md"], "GENERATED_FROM", ids["b.txt"]) in edges


def test_root_sensitivity_comes_from_settings(ctx, docs, data_dir: Path, emb):
    ctx.settings["sensitivity"] = {str(docs): "secret"}
    _run(ctx, emb)
    assert _count(data_dir, "SELECT COUNT(*) FROM roots WHERE sensitivity = 'secret'") == 1


def test_status_before_first_reindex(ctx):
    out = status(ctx, ollama_available=False)
    assert (out.roots, out.files_by_status, out.chunks) == ([], {}, 0)
    assert out.embed_model == "bge-m3"
    assert out.indexer_busy is False


def test_status_after_reindex(ctx, docs, data_dir: Path, emb):
    _run(ctx, emb)
    out = status(ctx, ollama_available=True)
    assert [(r.path, r.files, r.sensitivity) for r in out.roots] == [(str(docs), 4, "normal")]
    assert out.roots[0].last_scan
    assert out.files_by_status == {"indexed": 3, "skipped": 1}
    assert out.chunks == _count(data_dir, "SELECT COUNT(*) FROM chunks")
    assert out.ollama_available is True
    with writer_lock(data_dir):
        assert status(ctx, ollama_available=True).indexer_busy is True
