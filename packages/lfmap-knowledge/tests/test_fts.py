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
