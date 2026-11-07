You are a careful Python 3.12 developer. Write ONE new module in the `lfmap` monorepo: `packages/lfmap-knowledge/src/lfmap_knowledge/fts.py`. Code, comments and docstrings in English. Standard library plus `lfmap_core` only. Small functions, type hints everywhere, an English docstring on every public function and class.

RULES
- Do NOT edit the tests or conftest.py and do NOT define pytest fixtures.
- Reply with the line `FILE: packages/lfmap-knowledge/src/lfmap_knowledge/fts.py`, then ONE ```python block with the COMPLETE module (imports, constants and everything in the API section, fully implemented). Never answer with an empty block.

API
```python
def fold(s: str) -> str: ...  # s.casefold().replace("đ", "d")
def fts_query(user_text: str) -> str: ...  # '"hop" "dong"'; empty -> ToolError("invalid_input", ...)
def index_chunks(conn: sqlite3.Connection, rows: Iterable[tuple[int, str]]) -> None: ...  # (chunk_id, text)
def delete_content(conn: sqlite3.Connection, content_hash: str) -> None: ...
def keyword_search(conn: sqlite3.Connection, query: str, limit: int) -> list[tuple[int, float]]: ...
```

Schema (already created by the catalog migration):
- `chunks(chunk_id INTEGER PRIMARY KEY, content_hash, ordinal, heading_path, char_start, char_end, text)`.
- `CREATE VIRTUAL TABLE chunks_fts USING fts5(folded, content='', tokenize='unicode61 remove_diacritics 2')` (contentless; rowid = chunk_id).
- Connections use `row_factory = sqlite3.Row`.

fold
- `s.casefold().replace("đ", "d")`. The tokenizer removes the other diacritics.

fts_query
- fold, split on whitespace, remove every `"` inside each word, drop empty words, wrap each word in double quotes and join with one space (implicit AND). This neutralises FTS5 syntax (`NEAR`, `OR`, `-`, `*`, quotes).
- Order matters: remove the quotes first, then drop the words that became empty. Example: `'""'` splits into the one word `""`, which is empty once its quotes are removed, so no word is left -> `ToolError`.
- No word left -> `ToolError("invalid_input", "Query is empty")`.

index_chunks
- For each `(chunk_id, text)`: `INSERT INTO chunks_fts(rowid, folded) VALUES (?, ?)` with `fold(text)`.

delete_content
- Read `chunk_id, text` from `chunks` where `content_hash = ?`; for each row run `INSERT INTO chunks_fts(chunks_fts, rowid, folded) VALUES('delete', ?, ?)` with `fold(text)`. Do not delete rows from `chunks` (the caller does).

keyword_search
- `SELECT rowid, bm25(chunks_fts) AS score FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY score LIMIT ?` with `fts_query(query)`.
- Return plain tuples `(int(chunk_id), -float(bm25))`: higher score = better match.

No function calls `commit`; the caller owns the transaction.

Imports available:
- `from lfmap_core import ToolError` (`ToolError(code, message, details=None)`, attributes `.code`, `.details`).

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

TESTS (already written, packages/lfmap-knowledge/tests/test_fts.py; make them pass):
```python
import pytest

from lfmap_core import ToolError
from lfmap_knowledge.fts import delete_content, fold, fts_query, index_chunks, keyword_search


def _ids(db, query: str, limit: int = 10) -> list[int]:
    return [chunk_id for chunk_id, _ in keyword_search(db, query, limit)]


def _add_content(db, content_hash: str, texts: list[str]) -> list[int]:
    db.execute(
        "INSERT INTO contents(content_hash, extractor_version, chars, chunk_count, indexed_at)"
        " VALUES (?, 'v', 1, ?, 't')",
        (content_hash, len(texts)),
    )
    ids = []
    for ordinal, text in enumerate(texts):
        cursor = db.execute(
            "INSERT INTO chunks(content_hash, ordinal, heading_path, char_start, char_end, text)"
            " VALUES (?, ?, '', 0, ?, ?)",
            (content_hash, ordinal, len(text), text),
        )
        ids.append(cursor.lastrowid)
    index_chunks(db, list(zip(ids, texts, strict=True)))
    return ids


def test_fold():
    assert fold("Đường ĐI") == "dường di"


def test_fts_query_quotes_each_word():
    assert fts_query("Hợp  Đồng") == '"hợp" "dồng"'
    assert fts_query('a"b NEAR') == '"ab" "near"'


def test_search_without_diacritics(db):
    index_chunks(db, [(1, "Đường Nguyễn Trãi")])
    assert _ids(db, "duong") == [1]


def test_all_words_must_match(db):
    index_chunks(db, [(1, "Hợp đồng thuê nhà")])
    assert _ids(db, "hop dong") == [1]
    assert _ids(db, "hop xe") == []


@pytest.mark.parametrize("query", ["NEAR(a b)", '"', "a OR b -c*", 'hợp "đồng'])
def test_fts_syntax_is_neutralised(db, query: str):
    index_chunks(db, [(1, "a b c hợp đồng")])
    try:
        keyword_search(db, query, 5)
    except ToolError as error:
        assert error.code == "invalid_input"


@pytest.mark.parametrize("query", ["   ", '""'])
def test_empty_query_is_invalid(query: str):
    with pytest.raises(ToolError) as caught:
        fts_query(query)
    assert caught.value.code == "invalid_input"


def test_delete_content(db):
    gone = _add_content(db, "h1", ["hợp đồng cũ"])
    kept = _add_content(db, "h2", ["hợp đồng mới"])
    delete_content(db, "h1")
    assert _ids(db, "hop dong") == kept
    assert gone[0] not in _ids(db, "cu")
    assert db.execute("SELECT count(*) FROM chunks WHERE content_hash = 'h1'").fetchone()[0] == 1


def test_limit_and_order(db):
    index_chunks(db, [(1, "hợp đồng"), (2, "hợp đồng hợp đồng hợp đồng"), (3, "hợp đồng và nhiều chữ khác nữa ở đây")])
    results = keyword_search(db, "hop dong", 2)
    assert len(results) == 2
    scores = [score for _, score in results]
    assert scores == sorted(scores, reverse=True)
    assert all(isinstance(chunk_id, int) and isinstance(score, float) for chunk_id, score in results)
```

NOW WRITE THE COMPLETE `fts.py`. Start with the FILE line, then the code block containing the whole module.
