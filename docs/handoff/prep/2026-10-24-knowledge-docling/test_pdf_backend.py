# Prepared for task D3 (docs/handoff/2026-10-24-knowledge-docling-pdf.md).
# Copy to packages/lfmap-knowledge/tests/test_pdf_backend.py and delete these two lines.
import json
from pathlib import Path

import pytest

from lfmap_core import ToolContext, ToolError
from lfmap_core.permissions import PermissionManager
from lfmap_knowledge import catalog
from lfmap_knowledge.extract import ExtractResult, backend_for, cache_path, extract, extractor_version, pdf_backend
from lfmap_knowledge.indexer import reindex, status
from lfmap_knowledge.store import connect
from lfmap_markitdown.backends import docling as docling_backend
from lfmap_markitdown.schemas import ConvertOutput
from lfmap_markitdown.tool import MarkitdownTool

HASH = "ab" + "0" * 62
PLAIN = "Quality Manual\n\n1. Scope\n\n1.1 Responsibilities\n\nkangaroo duty roster.\n"
NESTED = "## Quality Manual\n\n## 1. Scope\n\n### 1.1 Responsibilities\n\nkangaroo duty roster.\n"


class FakeEmbedder:
    model = "fake-model"

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] * 8 for _ in texts]


@pytest.fixture
def converts(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """Replace markitdown.convert: PDFs get headings only from docling; records (file name, backend)."""
    seen: list[tuple[str, str]] = []

    def fake(self, inp):
        name = Path(inp.path).name
        seen.append((name, inp.backend))
        if name.endswith(".pdf"):
            markdown = NESTED if inp.backend == "docling" else PLAIN
        else:
            markdown = Path(inp.path).read_text(encoding="utf-8")
        return ConvertOutput(
            path=inp.path,
            markdown=markdown,
            chars=len(markdown),
            truncated=False,
            stage="markdown",
            text_quality=None,
            sha256="",
            backend=inp.backend if name.endswith(".pdf") else "markitdown",
            backend_version="test",
        )

    monkeypatch.setattr(MarkitdownTool, "convert", fake)
    return seen


@pytest.fixture
def docling_ready(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict:
    """Config whose markitdown settings make the Docling backend look available, without the extra or models."""
    monkeypatch.setattr(docling_backend, "docling_installed", lambda: True)
    monkeypatch.setattr(docling_backend, "missing_models", lambda artifacts_path: [])
    return {"plugins": {"markitdown": {"settings": {"docling_artifacts_path": str(tmp_path / "models")}}}}


@pytest.fixture
def docs(root: Path) -> Path:
    (root / "manual.pdf").write_bytes(b"%PDF-1.7 not parsed by the fake converter")
    (root / "note.md").write_text("# Note\n\nwombat minutes\n", encoding="utf-8")
    return root


def _ctx(perms: PermissionManager, data_dir: Path, **settings) -> ToolContext:
    return ToolContext(plugin_id="knowledge", permissions=perms, data_dir=data_dir, settings=settings)


def _heading_paths(data_dir: Path) -> list[str]:
    conn = connect(data_dir / "catalog.db")
    try:
        rows = conn.execute(
            "SELECT c.heading_path FROM chunks c JOIN files f USING (content_hash)"
            " WHERE f.rel_path = 'manual.pdf' ORDER BY c.ordinal"
        )
        return [r["heading_path"] for r in rows]
    finally:
        conn.close()


def _version_of(data_dir: Path, rel_path: str) -> str:
    conn = connect(data_dir / "catalog.db")
    try:
        row = conn.execute(
            "SELECT c.extractor_version FROM contents c JOIN files f USING (content_hash) WHERE f.rel_path = ?",
            (rel_path,),
        ).fetchone()
        return row["extractor_version"]
    finally:
        conn.close()


def test_pdf_backend_setting():
    assert pdf_backend({}) == "markitdown"
    assert pdf_backend({"pdf_backend": "markitdown"}) == "markitdown"
    assert pdf_backend({"pdf_backend": "docling"}) == "docling"
    with pytest.raises(ToolError) as info:
        pdf_backend({"pdf_backend": "Docling "})
    assert info.value.code == "invalid_input"


def test_backend_for_only_pdfs():
    assert backend_for(".pdf", "docling") == "docling"
    assert backend_for(".PDF", "docling") == "docling"
    assert backend_for(".docx", "docling") == "markitdown"
    assert backend_for(".pdf", "markitdown") == "markitdown"


def test_markitdown_version_and_cache_path_unchanged(tmp_path: Path):
    assert extractor_version() == extractor_version("markitdown")
    assert extractor_version().startswith("markitdown/")
    assert extractor_version("docling").startswith("docling/")
    assert cache_path(tmp_path, HASH) == cache_path(tmp_path, HASH, "markitdown") == tmp_path / "ab" / f"{HASH}.md"
    assert cache_path(tmp_path, HASH, "docling") == tmp_path / "ab" / f"{HASH}.docling.md"


def test_extract_with_docling_caches_separately(perms, docs: Path, data_dir: Path, converts):
    ctx = ToolContext(plugin_id="knowledge", permissions=perms)
    cache_dir = data_dir / "cache" / "md"
    pdf = docs / "manual.pdf"
    plain = extract(ctx, pdf, HASH, cache_dir, False, config={})
    nested = extract(ctx, pdf, HASH, cache_dir, False, config={}, backend="docling")
    assert converts == [("manual.pdf", "markitdown"), ("manual.pdf", "docling")]
    assert isinstance(nested, ExtractResult)
    assert nested.markdown == NESTED and plain.markdown == PLAIN
    assert nested.extractor_version == extractor_version("docling")
    docling_md = cache_path(cache_dir, HASH, "docling")
    assert docling_md.read_text(encoding="utf-8") == NESTED
    assert json.loads(docling_md.with_suffix(".json").read_text(encoding="utf-8"))["extractor_version"] == (
        extractor_version("docling")
    )
    assert cache_path(cache_dir, HASH).read_text(encoding="utf-8") == PLAIN

    again = extract(ctx, pdf, HASH, cache_dir, False, config={}, backend="docling")
    assert again.from_cache is True
    assert len(converts) == 2


def test_extract_raises_docling_unavailable(perms, docs: Path, data_dir: Path, monkeypatch: pytest.MonkeyPatch):
    """A missing backend is a configuration problem, not a property of the file: never cache it as skipped."""

    def unavailable(self, inp):
        raise ToolError("backend_unavailable", "no docling", {"reason_code": "docling_unavailable"})

    monkeypatch.setattr(MarkitdownTool, "convert", unavailable)
    ctx = ToolContext(plugin_id="knowledge", permissions=perms)
    with pytest.raises(ToolError) as info:
        extract(ctx, docs / "manual.pdf", HASH, data_dir / "cache" / "md", False, config={}, backend="docling")
    assert info.value.details["reason_code"] == "docling_unavailable"


def test_reindex_fails_fast_when_docling_unavailable(perms, docs: Path, data_dir: Path, converts):
    ctx = _ctx(perms, data_dir, pdf_backend="docling")
    with pytest.raises(ToolError) as info:
        reindex(ctx, FakeEmbedder(), config={})
    assert info.value.code == "backend_unavailable"
    assert info.value.details["reason_code"] == "docling_unavailable"
    assert converts == []
    assert not (data_dir / "catalog.db").exists()


def test_invalid_pdf_backend_fails_before_indexing(perms, docs: Path, data_dir: Path, converts):
    with pytest.raises(ToolError) as info:
        reindex(_ctx(perms, data_dir, pdf_backend="pymupdf"), FakeEmbedder(), config={})
    assert info.value.code == "invalid_input"
    assert converts == []


def test_reindex_with_docling_gives_pdf_heading_path(perms, docs: Path, data_dir: Path, converts, docling_ready):
    out = reindex(_ctx(perms, data_dir, pdf_backend="docling"), FakeEmbedder(), config=docling_ready)
    assert out.errors == 0 and out.extracted == 2
    assert sorted(converts) == [("manual.pdf", "docling"), ("note.md", "markitdown")]
    assert "1. Scope > 1.1 Responsibilities" in _heading_paths(data_dir)
    assert _version_of(data_dir, "manual.pdf") == extractor_version("docling")
    assert _version_of(data_dir, "note.md") == extractor_version()


def test_switching_backend_reextracts_only_pdfs(perms, docs: Path, data_dir: Path, converts, docling_ready):
    reindex(_ctx(perms, data_dir), FakeEmbedder(), config=docling_ready)
    assert sorted(converts) == [("manual.pdf", "markitdown"), ("note.md", "markitdown")]
    assert _heading_paths(data_dir) == [""]

    converts.clear()
    out = reindex(_ctx(perms, data_dir, pdf_backend="docling"), FakeEmbedder(), config=docling_ready)
    assert converts == [("manual.pdf", "docling")]
    assert out.extracted == 1 and out.errors == 0
    assert "1. Scope > 1.1 Responsibilities" in _heading_paths(data_dir)

    converts.clear()
    out = reindex(_ctx(perms, data_dir), FakeEmbedder(), config=docling_ready)
    assert converts == []  # the markitdown Markdown is still cached
    assert out.extracted == 1
    assert _heading_paths(data_dir) == [""]
    assert _version_of(data_dir, "manual.pdf") == extractor_version()


def test_status_and_get_file_report_docling(perms, docs: Path, data_dir: Path, converts, docling_ready):
    ctx = _ctx(perms, data_dir, pdf_backend="docling")
    reindex(ctx, FakeEmbedder(), config=docling_ready)
    assert status(ctx, ollama_available=False).pdf_backend == "docling"
    assert status(_ctx(perms, data_dir), ollama_available=False).pdf_backend == "markitdown"
    conn = connect(data_dir / "catalog.db")
    try:
        entry = catalog.get_file(conn, docs / "manual.pdf", data_dir / "cache" / "md")
    finally:
        conn.close()
    assert entry.markdown_cached is True
