import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from lfmap_core import ToolError
from lfmap_knowledge.catalog import abs_path, find_file, get_file, search_files, strip_accents
from lfmap_knowledge.extract import cache_path

HASH_A = "a" * 64
HASH_B = "b" * 64
OLD_NS = int(datetime(2026, 1, 1, tzinfo=UTC).timestamp() * 1e9)
NEW_NS = int(datetime(2026, 10, 1, tzinfo=UTC).timestamp() * 1e9)


def _root(db, path: Path, sensitivity: str = "normal") -> int:
    return db.execute("INSERT INTO roots(path, sensitivity) VALUES (?, ?)", (str(path), sensitivity)).lastrowid


def _file(db, root_id: int, rel: str, *, status="indexed", content_hash=None, mtime_ns=NEW_NS, size=10) -> int:
    name = rel.rsplit("/", 1)[-1]
    ext = os.path.splitext(name)[1].lower()
    return db.execute(
        "INSERT INTO files (root_id, rel_path, name_folded, ext, size, mtime_ns, content_hash, status,"
        " first_seen, last_seen) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'x', 'x')",
        (root_id, rel, name.casefold().replace("đ", "d"), ext, size, mtime_ns, content_hash, status),
    ).lastrowid


def _content(db, content_hash: str, chunk_count: int) -> None:
    db.execute(
        "INSERT INTO contents (content_hash, extractor_version, chars, chunk_count, indexed_at)"
        " VALUES (?, 'v', 100, ?, 'x')",
        (content_hash, chunk_count),
    )


@pytest.fixture
def catalog(db, root: Path):
    rid = _root(db, root)
    _file(db, rid, "Báo cáo Q3.docx", content_hash=HASH_A, mtime_ns=OLD_NS)
    _file(db, rid, "sub/Đề xuất.pdf", content_hash=HASH_B)
    _file(db, rid, "sub/deep/plan.pdf", content_hash=HASH_A)
    _file(db, rid, "notes.md", status="pending")
    _file(db, rid, "gone.pdf", status="deleted")
    _content(db, HASH_A, 7)
    db.commit()
    return db


def _names(out) -> list[str]:
    return sorted(Path(f.path).name for f in out.files)


def test_strip_accents_folds_vietnamese():
    assert strip_accents("Báo Cáo ĐỀ XUẤT") == "bao cao de xuat"


def test_abs_path_joins_posix_rel_path(root: Path):
    assert abs_path(str(root), "sub/deep/plan.pdf") == os.path.normpath(
        os.path.join(str(root), "sub", "deep", "plan.pdf")
    )


def test_name_query_ignores_accents_and_case(catalog):
    assert _names(search_files(catalog, query="bao cao")) == ["Báo cáo Q3.docx"]
    assert _names(search_files(catalog, query="DE XUAT")) == ["Đề xuất.pdf"]


def test_every_query_word_must_match(catalog):
    assert _names(search_files(catalog, query="q3 bao")) == ["Báo cáo Q3.docx"]
    assert search_files(catalog, query="bao xuat").total == 0


def test_like_wildcards_in_query_are_literal(catalog):
    assert search_files(catalog, query="%").total == 0
    assert search_files(catalog, query="_").total == 0


def test_glob_query_matches_rel_path(catalog):
    assert _names(search_files(catalog, query="**/*.pdf")) == ["plan.pdf", "Đề xuất.pdf"]
    assert _names(search_files(catalog, query="sub/deep/*")) == ["plan.pdf"]
    assert _names(search_files(catalog, query="*.docx")) == ["Báo cáo Q3.docx"]


def test_deleted_files_are_hidden_by_default(catalog):
    assert "gone.pdf" not in _names(search_files(catalog))
    assert _names(search_files(catalog, status="deleted")) == ["gone.pdf"]


def test_unknown_status_is_invalid(catalog):
    with pytest.raises(ToolError) as err:
        search_files(catalog, status="done")
    assert err.value.code == "invalid_input"


def test_ext_filter_accepts_any_spelling(catalog):
    for ext in ("pdf", ".pdf", ".PDF"):
        assert _names(search_files(catalog, ext=ext)) == ["plan.pdf", "Đề xuất.pdf"]


def test_status_filter(catalog):
    assert _names(search_files(catalog, status="pending")) == ["notes.md"]


def test_modified_after(catalog):
    out = search_files(catalog, modified_after="2026-06-01")
    assert "Báo cáo Q3.docx" not in _names(out)
    assert out.total == 3


def test_bad_modified_after_is_invalid(catalog):
    with pytest.raises(ToolError) as err:
        search_files(catalog, modified_after="last week")
    assert err.value.code == "invalid_input"


def test_root_filter(catalog, tmp_path: Path):
    other = tmp_path / "other"
    rid = _root(catalog, other)
    _file(catalog, rid, "x.pdf")
    assert _names(search_files(catalog, root=str(other))) == ["x.pdf"]
    assert search_files(catalog).total == 5


def test_unknown_root_is_not_found(catalog, tmp_path: Path):
    with pytest.raises(ToolError) as err:
        search_files(catalog, root=str(tmp_path / "nope"))
    assert err.value.code == "not_found"


def test_exclude_root_ids_hides_secret_roots(catalog, tmp_path: Path):
    rid = _root(catalog, tmp_path / "secret", "secret")
    _file(catalog, rid, "salary.xlsx")
    assert "salary.xlsx" in _names(search_files(catalog))
    assert "salary.xlsx" not in _names(search_files(catalog, exclude_root_ids={rid}))


def test_limit_and_total_newest_first(catalog):
    out = search_files(catalog, limit=2)
    assert out.total == 4
    assert len(out.files) == 2
    assert "Báo cáo Q3.docx" not in _names(out)


def test_file_info_fields(catalog, root: Path):
    info = search_files(catalog, query="bao cao").files[0]
    assert info.path == abs_path(str(root), "Báo cáo Q3.docx")
    assert info.root == str(root)
    assert info.ext == ".docx"
    assert info.size == 10
    assert info.status == "indexed"
    assert info.content_hash == HASH_A
    assert info.mtime == "2026-01-01T00:00:00+00:00"


def test_find_file_picks_longest_root(catalog, root: Path):
    inner = _root(catalog, root / "sub")
    fid = _file(catalog, inner, "Đề xuất.pdf")
    assert find_file(catalog, root / "sub" / "Đề xuất.pdf")["file_id"] == fid


def test_get_file_counts_chunks_and_duplicates(catalog, root: Path, data_dir: Path):
    out = get_file(catalog, root / "Báo cáo Q3.docx", data_dir / "cache" / "md")
    assert out.file.path == abs_path(str(root), "Báo cáo Q3.docx")
    assert out.chunk_count == 7
    assert out.duplicates == [abs_path(str(root), "sub/deep/plan.pdf")]
    assert out.markdown_cached is False


def test_get_file_sees_markdown_cache(catalog, root: Path, data_dir: Path):
    cache_dir = data_dir / "cache" / "md"
    md = cache_path(cache_dir, HASH_A)
    md.parent.mkdir(parents=True)
    md.write_text("# x", encoding="utf-8")
    assert get_file(catalog, root / "Báo cáo Q3.docx", cache_dir).markdown_cached is True


def test_get_file_without_content_row(catalog, root: Path, data_dir: Path):
    out = get_file(catalog, root / "notes.md", data_dir / "cache" / "md")
    assert out.chunk_count == 0
    assert out.duplicates == []
    assert out.file.content_hash == ""


@pytest.mark.parametrize("rel", ["missing.pdf", "gone.pdf"])
def test_get_file_outside_catalog_is_not_found(catalog, root: Path, data_dir: Path, rel: str):
    with pytest.raises(ToolError) as err:
        get_file(catalog, root / rel, data_dir)
    assert err.value.code == "not_found"


def test_get_file_outside_every_root_is_not_found(catalog, tmp_path: Path, data_dir: Path):
    with pytest.raises(ToolError) as err:
        get_file(catalog, tmp_path / "elsewhere.pdf", data_dir)
    assert err.value.code == "not_found"


def test_get_file_hides_duplicates_in_excluded_roots(catalog, root: Path, tmp_path: Path, data_dir: Path):
    rid = _root(catalog, tmp_path / "secret", "secret")
    _file(catalog, rid, "copy.docx", content_hash=HASH_A)
    out = get_file(catalog, root / "Báo cáo Q3.docx", data_dir, exclude_root_ids={rid})
    assert out.duplicates == [abs_path(str(root), "sub/deep/plan.pdf")]
