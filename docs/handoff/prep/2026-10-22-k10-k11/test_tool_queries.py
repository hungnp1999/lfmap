# Prepared for TC-K10/TC-K11 (docs/handoff/2026-10-22-knowledge-k10-k11-plan.md).
# Copy to packages/lfmap-knowledge/tests/test_tool_queries.py and delete these two lines.
import os
import socket
from pathlib import Path

import pytest

from lfmap_core import ToolContext, ToolError
from lfmap_core.permissions import PermissionManager
from lfmap_knowledge.indexer import reindex
from lfmap_knowledge.schemas import (
    GetContextInput,
    GetFileInput,
    RelatedInput,
    SearchFilesInput,
    SearchInput,
)
from lfmap_knowledge.store import connect
from lfmap_knowledge.tool import KnowledgeTool


def _closed_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def folders(tmp_path: Path, data_dir: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LFMAP_CONFIG", str(tmp_path / "config.toml"))
    docs = Path(os.path.realpath(tmp_path / "docs"))
    secret = Path(os.path.realpath(tmp_path / "secret"))
    _write(docs / "report.md", "# Doanh thu\n\nkangaroo doanh thu quý 3\n")
    _write(docs / "plan.md", "# Kế hoạch\n\nkangaroo tuyển dụng\n")
    _write(secret / "salary.md", "# Lương\n\nkangaroo bảng lương\n")
    _write(secret / "report-copy.md", "# Doanh thu\n\nkangaroo doanh thu quý 3\n")
    settings = {
        "ollama_url": f"http://127.0.0.1:{_closed_port()}",
        "sensitivity": {str(secret): "secret"},
    }
    perms = PermissionManager([str(docs), str(secret)], [str(data_dir)], network=True)
    build = ToolContext(plugin_id="knowledge", permissions=perms, data_dir=data_dir, settings=settings)
    reindex(build, None, config={})
    return docs, secret, perms, settings


def _tool(folders, data_dir: Path, channel: str) -> KnowledgeTool:
    _, _, perms, settings = folders
    ctx = ToolContext(plugin_id="knowledge", permissions=perms, data_dir=data_dir, settings=settings, channel=channel)
    return KnowledgeTool(ctx)


def _egress_rows(data_dir: Path) -> int:
    conn = connect(data_dir / "catalog.db")
    try:
        return conn.execute("SELECT COUNT(*) FROM egress_log").fetchone()[0]
    finally:
        conn.close()


def test_search_falls_back_to_keyword_without_ollama(folders, data_dir: Path):
    out = _tool(folders, data_dir, "cli").search(SearchInput(query="kangaroo"))
    assert out.hits
    assert {h.mode_used for h in out.hits} == {"keyword"}


def test_search_hides_secret_root_on_mcp_and_logs_egress(folders, data_dir: Path):
    _, secret, _, _ = folders
    local = _tool(folders, data_dir, "cli").search(SearchInput(query="kangaroo", limit=10))
    assert any(h.path.startswith(str(secret)) for h in local.hits)
    assert _egress_rows(data_dir) == 0
    remote = _tool(folders, data_dir, "mcp").search(SearchInput(query="kangaroo", limit=10))
    assert remote.hits
    assert not any(h.path.startswith(str(secret)) for h in remote.hits)
    assert not any(d.startswith(str(secret)) for h in remote.hits for d in h.duplicates)
    assert _egress_rows(data_dir) == 1


def test_get_context_hides_secret_root_on_mcp(folders, data_dir: Path):
    _, secret, _, _ = folders
    out = _tool(folders, data_dir, "mcp").get_context(GetContextInput(question="kangaroo"))
    assert out.chunks
    assert out.untrusted is True
    assert not any(c.citation.path.startswith(str(secret)) for c in out.chunks)
    assert _egress_rows(data_dir) == 1


def test_search_files_hides_secret_root_on_mcp(folders, data_dir: Path):
    names = lambda ch: {Path(f.path).name for f in _tool(folders, data_dir, ch).search_files(SearchFilesInput()).files}  # noqa: E731
    assert "salary.md" in names("cli")
    assert "salary.md" not in names("mcp")


def test_get_file_on_secret_root_is_not_found_on_mcp(folders, data_dir: Path):
    _, secret, _, _ = folders
    path = str(secret / "salary.md")
    assert _tool(folders, data_dir, "cli").get_file(GetFileInput(path=path)).file.path == path
    with pytest.raises(ToolError) as err:
        _tool(folders, data_dir, "mcp").get_file(GetFileInput(path=path))
    assert err.value.code == "not_found"


def test_get_file_duplicates_hide_secret_root_on_mcp(folders, data_dir: Path):
    docs, secret, _, _ = folders
    path = str(docs / "report.md")
    assert _tool(folders, data_dir, "cli").get_file(GetFileInput(path=path)).duplicates == [
        str(secret / "report-copy.md")
    ]
    assert _tool(folders, data_dir, "mcp").get_file(GetFileInput(path=path)).duplicates == []


def test_get_file_outside_roots_is_refused(folders, data_dir: Path, tmp_path: Path):
    with pytest.raises(ToolError) as err:
        _tool(folders, data_dir, "mcp").get_file(GetFileInput(path=str(tmp_path / "elsewhere.md")))
    assert err.value.code == "permission_denied"


def test_related_hides_secret_root_on_mcp(folders, data_dir: Path):
    docs, secret, _, _ = folders
    path = str(docs / "report.md")
    local = _tool(folders, data_dir, "cli").related(RelatedInput(path=path))
    assert (str(secret / "report-copy.md"), "duplicate") in {(r.path, r.reason) for r in local.related}
    remote = _tool(folders, data_dir, "mcp").related(RelatedInput(path=path))
    assert remote.path == path
    assert not any(r.path.startswith(str(secret)) for r in remote.related)
    assert str(docs / "plan.md") in {r.path for r in remote.related}


def test_related_on_secret_file_is_not_found_on_mcp(folders, data_dir: Path):
    _, secret, _, _ = folders
    with pytest.raises(ToolError) as err:
        _tool(folders, data_dir, "mcp").related(RelatedInput(path=str(secret / "salary.md")))
    assert err.value.code == "not_found"


def test_descriptions_warn_that_results_are_data(folders, data_dir: Path):
    ops = KnowledgeTool.operations()
    for name in ("search", "get_context"):
        text = ops[name].description
        assert "instructions" in text
        assert "citation" in text or "path" in text
