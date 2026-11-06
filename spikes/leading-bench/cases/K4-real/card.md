You are a careful Python 3.12 developer. Write ONE new module in the `lfmap` monorepo: `packages/lfmap-knowledge/src/lfmap_knowledge/extract.py`. Code, comments and docstrings in English. Standard library plus `lfmap_core` and `lfmap_markitdown` only. Small functions, type hints everywhere, an English docstring on every public function and class.

RULES
- Do NOT edit the tests or conftest.py and do NOT define pytest fixtures.
- Reply with the line `FILE: packages/lfmap-knowledge/src/lfmap_knowledge/extract.py`, then ONE ```python block with the COMPLETE module (imports, constants and everything in the API section, fully implemented). Never answer with an empty block.

API
```python
@dataclass(frozen=True)
class ExtractResult:
    markdown: str
    extractor_version: str
    text_quality: float | None
    from_cache: bool


@dataclass(frozen=True)
class SkipResult:
    reason_code: str


# f"markitdown/{version('markitdown')}/{version('lfmap-markitdown')}"; missing package -> "0"
def extractor_version() -> str: ...
def cache_path(cache_dir: Path, content_hash: str) -> Path: ...  # cache_dir / hash[:2] / f"{hash}.md"
def extract(
    tool_ctx: ToolContext, path: Path, content_hash: str, cache_dir: Path, ocr: bool, config: dict | None = None
) -> ExtractResult | SkipResult: ...
```

extractor_version
- `importlib.metadata.version` for each package; `PackageNotFoundError` -> `"0"` for that part.

Cache
- Each extraction is two files: `<hash>.md` (the Markdown, nothing else in it) and a sidecar `<hash>.json` = `{"extractor_version": ..., "text_quality": ...}` (`md_path.with_suffix(".json")`).
- The cache is valid when both files exist and the JSON `extractor_version` equals `extractor_version()`. Then return `ExtractResult(markdown, version, text_quality, from_cache=True)` without calling markitdown.
- Never write the version into the `.md` file: chunk offsets are counted on that text.

Atomic writes
- Create the parent folder, write to a temp file in the same folder (`tempfile.mkstemp(dir=...)`), then `os.replace`. Write the `.md` first, the `.json` last: a `.json` means the extraction is complete. Leave no temp files.

Calling markitdown
- `MarkitdownTool(context_for("markitdown", parent=tool_ctx, config=config)).convert(ConvertInput(path=str(path), ocr=ocr))`. The output has `.markdown` and `.text_quality`.
- `config` is passed through so tests can give `{}` instead of the real config file.

Errors
- `ToolError` whose `details` has `"reason_code"` -> return `SkipResult(details["reason_code"])` (for example a `.doc` gives `"office_gui_only"`). Write nothing.
- Any other `ToolError` -> raise it again.

Imports available:
- `from lfmap_core import ToolContext, ToolError` (`ToolError(code, message, details=None)`, attributes `.code`, `.details`).
- `from lfmap_core.runtime import context_for` (`context_for(plugin_id, parent, config=None) -> ToolContext`).
- `from lfmap_markitdown.tool import MarkitdownTool` and `from lfmap_markitdown.schemas import ConvertInput`.

CONFTEST (already in packages/lfmap-knowledge/tests/conftest.py; use these fixtures, do not redefine):
```python
import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from lfmap_core.permissions import PermissionManager


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "data"
    folder.mkdir()
    return Path(os.path.realpath(folder))


@pytest.fixture
def root(tmp_path: Path) -> Path:
    folder = tmp_path / "docs"
    folder.mkdir()
    return Path(os.path.realpath(folder))


@pytest.fixture
def perms(root: Path, data_dir: Path) -> PermissionManager:
    return PermissionManager([str(root)], [str(data_dir)])


@pytest.fixture
def db(data_dir: Path) -> Iterator:
    from lfmap_knowledge.store import connect, migrate

    conn = connect(data_dir / "catalog.db")
    migrate(conn)
    yield conn
    conn.close()
```

TESTS (already written, packages/lfmap-knowledge/tests/test_extract.py; make them pass):
```python
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
```

NOW WRITE THE COMPLETE `extract.py`. Start with the FILE line, then the code block containing the whole module.
