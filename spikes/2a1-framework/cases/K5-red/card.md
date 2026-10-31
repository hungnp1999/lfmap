You are a careful Python 3.12 developer. Write ONE new module in the `lfmap` monorepo: `packages/lfmap-knowledge/src/lfmap_knowledge/chunker.py`. Code, comments and docstrings in English. Standard library only (`re`, `dataclasses`), a pure function with no I/O. Small functions, type hints everywhere, an English docstring on every public function and class.

RULES
- Do NOT edit the tests or conftest.py and do NOT define pytest fixtures.
- Reply with the line `FILE: packages/lfmap-knowledge/src/lfmap_knowledge/chunker.py`, then ONE ```python block with the COMPLETE module (imports, constants and everything in the API section, fully implemented). Never answer with an empty block.

API
```python
@dataclass(frozen=True)
class Chunk:
    ordinal: int
    heading_path: str
    char_start: int
    char_end: int
    text: str


def chunk_markdown(text: str, target_chars: int = 1500, max_chars: int = 3000) -> list[Chunk]: ...
```

Sections
- Split on ATX headings `#` to `######` (`^(#{1,6})[ \t]+(.*)$`, multiline). Keep a heading stack: a heading of level n drops every stacked heading of level >= n, then pushes itself.
- `heading_path` joins the stack titles with `" > "`, e.g. `"A > B"`; after `# A`, `## B`, `## C` the path under C is `"A > C"`. Text before the first heading has `heading_path = ""`.
- A section starts at its heading line, so the heading line is in the first chunk of that section. Chunks never span two sections.

Blocks and merging
- Inside a section, blocks are runs of non-blank lines separated by blank lines.
- Merge consecutive blocks into one chunk while the merged span (from the first block start to the last block end) stays <= `target_chars`.
- A plain chunk's text is exactly `text[char_start:char_end]` (offsets point into the original text, for citations). No overlap. Drop chunks that are only whitespace; `""` gives `[]`.

Long blocks (> `max_chars`)
- Paragraph: cut at the last sentence boundary (`". "`, `"? "`, `"! "` or a newline) that keeps the piece <= `max_chars`; if there is none, hard cut at `max_chars`. Skip whitespace at the start of the next piece.
- Table (every line starts with `|`): a table <= `max_chars` is never cut. A longer table is cut by rows; every piece starts with the header line and the `|---|` separator line, then whole data rows, and stays <= `max_chars`. Each data row appears in exactly one piece. These pieces are not merged with other blocks.
- A repeated-header table chunk is the one exception to the slicing rule: its `text` is header + separator + rows, while `char_start`/`char_end` cover only its data rows in the original text. Say so in the docstring.

Ordinals
- `ordinal` counts from 0 with no gaps, in text order.

Imports available:
- Nothing outside the standard library.

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

TESTS (already written, packages/lfmap-knowledge/tests/test_chunker.py; make them pass):
```python
from lfmap_knowledge.chunker import Chunk, chunk_markdown

MAX = 3000


def _sentences(count: int) -> str:
    return " ".join(f"Câu số {i} nói về hợp đồng thuê nhà ở Hà Nội." for i in range(count))


def _table(rows: int) -> tuple[str, str, list[str]]:
    header = "| Mã | Giá trị |"
    data = [f"| r{i:03} | giá {i:03} đồng |" for i in range(rows)]
    return header, "\n".join([header, "|---|---|", *data]), data


def _assert_slices(text: str, chunks: list[Chunk]) -> None:
    for chunk in chunks:
        assert text[chunk.char_start : chunk.char_end] == chunk.text


def _with(chunks: list[Chunk], needle: str) -> Chunk:
    return next(c for c in chunks if needle in c.text)


def test_offsets_point_into_text():
    _, table, _ = _table(3)
    text = (
        f"Lời mở đầu.\n\n# Báo cáo\n\nDoanh thu tăng mạnh.\n\n## Chi tiết\n\n{table}\n\n"
        "Ghi chú cuối: đường Đê La Thành.\n"
    )
    chunks = chunk_markdown(text)
    assert chunks
    _assert_slices(text, chunks)
    assert _with(chunks, "Lời mở đầu").heading_path == ""
    assert "đường Đê La Thành" in _with(chunks, "Ghi chú").text


def test_nested_heading_path():
    chunks = chunk_markdown("# A\n\n## B\n\nNội dung đoạn.\n")
    assert _with(chunks, "Nội dung").heading_path == "A > B"


def test_sibling_heading_replaces_previous():
    chunks = chunk_markdown("# A\n\n## B\n\nPhần B.\n\n## C\n\nPhần C.\n")
    assert _with(chunks, "Phần B").heading_path == "A > B"
    assert _with(chunks, "Phần C").heading_path == "A > C"


def test_heading_line_is_in_first_chunk_of_section():
    chunks = chunk_markdown("# A\n\nPhần A.\n")
    assert _with(chunks, "Phần A").text.startswith("# A")


def test_long_paragraph_is_split():
    text = _sentences(250)
    assert len(text) > 10_000
    chunks = chunk_markdown(text)
    assert len(chunks) > 1
    assert all(len(c.text) <= MAX for c in chunks)
    _assert_slices(text, chunks)
    assert "".join(c.text for c in chunks).replace(" ", "") == text.replace(" ", "")


def test_sentence_without_punctuation_is_hard_cut():
    text = "a" * 10_000
    chunks = chunk_markdown(text)
    assert all(len(c.text) <= MAX for c in chunks)
    assert "".join(c.text for c in chunks) == text


def test_small_table_is_kept_whole():
    _, table, _ = _table(5)
    text = f"{_sentences(30)}\n\n{table}\n\n{_sentences(30)}\n"
    chunks = chunk_markdown(text)
    assert any(table in c.text for c in chunks)
    _assert_slices(text, chunks)


def test_long_table_repeats_header():
    header, table, data = _table(200)
    assert len(table) > MAX
    chunks = chunk_markdown(f"{table}\n")
    assert all(len(c.text) <= MAX for c in chunks)
    table_chunks = [c for c in chunks if any(line in data for line in c.text.splitlines())]
    assert len(table_chunks) > 1
    assert all(c.text.startswith(header) for c in table_chunks)
    lines = [line for c in chunks for line in c.text.splitlines()]
    assert all(lines.count(row) == 1 for row in data)


def test_empty_text():
    assert chunk_markdown("") == []
    assert chunk_markdown("   \n\n") == []


def test_short_paragraphs_are_merged():
    paragraphs = [f"Đoạn ngắn số {i}." for i in range(20)]
    chunks = chunk_markdown("\n\n".join(paragraphs))
    assert len(chunks) < len(paragraphs)
    assert all(len(c.text) <= MAX for c in chunks)


def test_ordinals_are_consecutive():
    text = f"# A\n\n{_sentences(100)}\n\n# B\n\n{_sentences(100)}\n"
    chunks = chunk_markdown(text)
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))
```

NOW WRITE THE COMPLETE `chunker.py`. Start with the FILE line, then the code block containing the whole module.
