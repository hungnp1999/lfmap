import json
from pathlib import Path

import pytest

from lfmap_core import ToolContext, ToolError
from lfmap_knowledge.extract import ExtractResult, SkipResult, cache_path, extract, extractor_version
from lfmap_markitdown.tool import MarkitdownTool

HASH = "ab" + "0" * 62


@pytest.fixture
def ctx(perms) -> ToolContext:
    return ToolContext(plugin_id="knowledge", permissions=perms)


@pytest.fixture
def cache_dir(data_dir: Path) -> Path:
    return data_dir / "cache" / "md"


@pytest.fixture
def note(root: Path) -> Path:
    path = root / "note.md"
    path.write_text("# Báo cáo\n\nDoanh thu tăng.\n", encoding="utf-8")
    return path


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []
    original = MarkitdownTool.convert

    def counting(self, inp):
        seen.append(inp.path)
        return original(self, inp)

    monkeypatch.setattr(MarkitdownTool, "convert", counting)
    return seen


def _extract(ctx: ToolContext, path: Path, cache_dir: Path, content_hash: str = HASH):
    return extract(ctx, path, content_hash, cache_dir, False, config={})


def test_first_call_writes_cache(ctx, note: Path, cache_dir: Path):
    result = _extract(ctx, note, cache_dir)
    assert isinstance(result, ExtractResult)
    assert result.from_cache is False
    assert "Doanh thu" in result.markdown
    assert result.extractor_version == extractor_version()
    md = cache_path(cache_dir, HASH)
    assert md.read_text(encoding="utf-8") == result.markdown
    meta = json.loads(md.with_suffix(".json").read_text(encoding="utf-8"))
    assert meta == {"extractor_version": result.extractor_version, "text_quality": result.text_quality}


def test_second_call_uses_cache(ctx, note: Path, cache_dir: Path, calls: list[str]):
    first = _extract(ctx, note, cache_dir)
    second = _extract(ctx, note, cache_dir)
    assert len(calls) == 1
    assert isinstance(second, ExtractResult)
    assert second.from_cache is True
    assert second.markdown == first.markdown
    assert second.extractor_version == first.extractor_version


def test_other_extractor_version_extracts_again(ctx, note: Path, cache_dir: Path, calls: list[str]):
    _extract(ctx, note, cache_dir)
    meta_path = cache_path(cache_dir, HASH).with_suffix(".json")
    meta_path.write_text(json.dumps({"extractor_version": "old", "text_quality": None}), encoding="utf-8")
    result = _extract(ctx, note, cache_dir)
    assert len(calls) == 2
    assert result.from_cache is False
    assert json.loads(meta_path.read_text(encoding="utf-8"))["extractor_version"] == extractor_version()


def test_doc_is_skipped(ctx, root: Path, cache_dir: Path):
    old = root / "old.doc"
    old.write_bytes(b"\xd0\xcf\x11\xe0data")
    assert _extract(ctx, old, cache_dir) == SkipResult("office_gui_only")
    assert not cache_path(cache_dir, HASH).exists()


def test_other_tool_error_is_raised(ctx, note: Path, cache_dir: Path, monkeypatch: pytest.MonkeyPatch):
    def broken(self, inp):
        raise ToolError("internal", "x")

    monkeypatch.setattr(MarkitdownTool, "convert", broken)
    with pytest.raises(ToolError) as caught:
        _extract(ctx, note, cache_dir)
    assert caught.value.code == "internal"


def test_no_temp_files_left(ctx, note: Path, cache_dir: Path):
    _extract(ctx, note, cache_dir)
    files = sorted(p.name for p in cache_dir.rglob("*") if p.is_file())
    assert files == [f"{HASH}.json", f"{HASH}.md"]


def test_cache_path():
    assert cache_path(Path("c"), "abcdef") == Path("c/ab/abcdef.md")
