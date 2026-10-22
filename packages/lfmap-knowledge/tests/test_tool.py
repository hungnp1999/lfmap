import socket
from pathlib import Path

import pytest

from lfmap_core import ToolContext
from lfmap_core.permissions import PermissionManager
from lfmap_knowledge.schemas import ReindexInput, StatusInput
from lfmap_knowledge.tool import KnowledgeTool


def _closed_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def tool(root: Path, data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    monkeypatch.setenv("LFMAP_CONFIG", str(tmp_path / "config.toml"))
    (root / "a.md").write_text("# Alpha\n\nkangaroo\n", encoding="utf-8")
    ctx = ToolContext(
        plugin_id="knowledge",
        permissions=PermissionManager([str(root)], [str(data_dir)], network=True),
        data_dir=data_dir,
        settings={"ollama_url": f"http://127.0.0.1:{_closed_port()}"},
    )
    return KnowledgeTool(ctx)


def test_status_with_ollama_down(tool):
    out = tool.status(StatusInput())
    assert out.ollama_available is False
    assert out.embed_model == "bge-m3"


def test_reindex_with_ollama_down_is_keyword_only(tool):
    out = tool.reindex(ReindexInput())
    assert out.embed_skipped_reason == "ollama_unreachable"
    assert (out.extracted, out.embedded, out.errors) == (1, 0, 0)
    assert tool.status(StatusInput()).files_by_status == {"indexed": 1}


def test_reindex_progress_goes_to_stderr_on_cli(tool, capsys):
    tool.ctx.channel = "cli"
    tool.reindex(ReindexInput())
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "extract 1/1" in captured.err.splitlines()
