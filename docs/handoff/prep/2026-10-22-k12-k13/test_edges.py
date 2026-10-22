# Prepared for TC-K13 (docs/handoff/2026-10-22-knowledge-k12-k13-plan.md).
# Copy to packages/lfmap-knowledge/tests/test_edges.py and delete these two lines.
import os
from pathlib import Path

import pytest

from lfmap_core import ToolError
from lfmap_knowledge.edges import link_generated_from, link_references, link_targets, related

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64


def _root(db, path: Path, sensitivity: str = "normal") -> int:
    return db.execute("INSERT INTO roots(path, sensitivity) VALUES (?, ?)", (str(path), sensitivity)).lastrowid


def _file(db, root_id: int, rel: str, *, status="indexed", content_hash=None) -> int:
    name = rel.rsplit("/", 1)[-1]
    return db.execute(
        "INSERT INTO files (root_id, rel_path, name_folded, ext, size, mtime_ns, content_hash, status,"
        " first_seen, last_seen) VALUES (?, ?, ?, ?, 1, 1, ?, ?, 'x', 'x')",
        (root_id, rel, name.casefold(), os.path.splitext(name)[1].lower(), content_hash, status),
    ).lastrowid


def _chunk(db, content_hash: str, chunk_id: int) -> None:
    db.execute(
        "INSERT OR IGNORE INTO contents (content_hash, extractor_version, chars, chunk_count, indexed_at)"
        " VALUES (?, 'v', 1, 1, 'x')",
        (content_hash,),
    )
    db.execute(
        "INSERT INTO chunks (chunk_id, content_hash, ordinal, heading_path, char_start, char_end, text)"
        " VALUES (?, ?, ?, '', 0, 1, 'x')",
        (chunk_id, content_hash, chunk_id),
    )


def _edges(db) -> set[tuple[int, str, int]]:
    return {(r["src_file_id"], r["rel"], r["dst_file_id"]) for r in db.execute("SELECT * FROM edges")}


def _path(root: Path, rel: str) -> str:
    return os.path.normpath(os.path.join(str(root), *rel.split("/")))


class FakeStore:
    """Chunk 1 belongs to the file under test; search returns fixed hits."""

    def __init__(self, hits: list[tuple[int, float]], known: set[int]) -> None:
        self.hits = hits
        self.known = known
        self.asked: list[int] = []

    def vector_of(self, chunk_ids: list[int]) -> list[list[float]]:
        self.asked = list(chunk_ids)
        if not set(chunk_ids) <= self.known:
            raise ToolError("not_found", "no vector")
        return [[1.0, 0.0] for _ in chunk_ids]

    def search(self, vector: list[float], limit: int) -> list[tuple[int, float]]:
        return self.hits[:limit]


@pytest.fixture
def rid(db, root: Path) -> int:
    return _root(db, root)


@pytest.mark.parametrize(
    ("source", "markdown_twin"),
    [("a.pdf", "a.pdf.md"), ("sub/a.docx", "sub/a.md")],
)
def test_generated_from_links_markdown_to_source(db, rid, source, markdown_twin):
    src = _file(db, rid, source)
    md = _file(db, rid, markdown_twin)
    assert link_generated_from(db, md) == 1
    assert _edges(db) == {(md, "GENERATED_FROM", src)}


def test_generated_from_works_from_the_source_side_and_is_idempotent(db, rid):
    src = _file(db, rid, "a.pdf")
    md = _file(db, rid, "a.pdf.md")
    link_generated_from(db, src)
    link_generated_from(db, src)
    link_generated_from(db, md)
    assert _edges(db) == {(md, "GENERATED_FROM", src)}


def test_generated_from_ignores_other_folders_roots_and_deleted(db, rid, tmp_path: Path):
    _file(db, rid, "sub/a.pdf")
    _file(db, rid, "a.docx", status="deleted")
    other = _root(db, tmp_path / "other")
    _file(db, other, "a.xlsx")
    md = _file(db, rid, "a.md")
    assert link_generated_from(db, md) == 0
    assert _edges(db) == set()


def test_plain_files_get_no_generated_from(db, rid):
    _file(db, rid, "a.pdf")
    other = _file(db, rid, "a.docx")
    assert link_generated_from(db, other) == 0


def test_link_targets_drops_unsafe_and_external_links():
    markdown = (
        "[ok](../x/b.docx) [frag](c.pdf#page=2) [space](d%20e.pdf) [win](..\\x\\f.pdf)"
        " [unc](\\\\server\\share\\x.pdf) [web](http://example.com/a.pdf) [tls](https://e.com)"
        " [file](file:///C:/x.pdf) [drive](C:/x.pdf) [abs](/etc/passwd) [mail](mailto:a@b.c)"
        " [proto](//server/x.pdf) [anchor](#top)"
    )
    assert link_targets(markdown) == ["../x/b.docx", "c.pdf", "d e.pdf", "../x/f.pdf"]


def test_references_resolve_relative_to_the_source_folder(db, rid):
    src = _file(db, rid, "docs/report.md")
    dst = _file(db, rid, "x/b.docx")
    assert link_references(db, src, "See [b](../x/b.docx).") == 1
    assert _edges(db) == {(src, "REFERENCES", dst)}
    assert db.execute("SELECT detail FROM edges").fetchone()[0] == "../x/b.docx"


def test_references_never_leave_the_root(db, rid, tmp_path: Path):
    other = _root(db, tmp_path / "other")
    _file(db, other, "b.docx")
    src = _file(db, rid, "report.md")
    assert link_references(db, src, "[b](../other/b.docx) [c](../../b.docx)") == 0


def test_references_skip_missing_deleted_and_self(db, rid):
    src = _file(db, rid, "report.md")
    _file(db, rid, "old.pdf", status="deleted")
    assert link_references(db, src, "[a](missing.pdf) [b](old.pdf) [c](report.md)") == 0
    assert _edges(db) == set()


def test_references_are_replaced_on_reindex(db, rid):
    src = _file(db, rid, "report.md")
    a = _file(db, rid, "a.pdf")
    b = _file(db, rid, "b.pdf")
    link_references(db, src, "[a](a.pdf)")
    link_references(db, src, "[b](b.pdf) [b again](./b.pdf)")
    assert _edges(db) == {(src, "REFERENCES", b)}
    assert a not in {dst for _, _, dst in _edges(db)}


def test_related_reasons(db, rid, root: Path):
    me = _file(db, rid, "dir/a.pdf", content_hash=HASH_A)
    _file(db, rid, "copy/a.pdf", content_hash=HASH_A)
    md = _file(db, rid, "dir/a.pdf.md", content_hash=HASH_B)
    ref = _file(db, rid, "dir/ref.docx")
    back = _file(db, rid, "other/back.md")
    _file(db, rid, "dir/neighbour.xlsx")
    db.executemany(
        "INSERT INTO edges (src_file_id, rel, dst_file_id) VALUES (?, ?, ?)",
        [(md, "GENERATED_FROM", me), (me, "REFERENCES", ref), (back, "REFERENCES", me)],
    )
    reasons = {Path(r.path).name: r.reason for r in related(db, me)}
    assert reasons == {
        "a.pdf": "duplicate",
        "a.pdf.md": "generated_from",
        "ref.docx": "references",
        "back.md": "referenced_by",
        "neighbour.xlsx": "same_folder",
    }
    assert related(db, me)[0].path == _path(root, "copy/a.pdf")


def test_related_never_returns_itself_or_deleted(db, rid):
    me = _file(db, rid, "a.pdf", content_hash=HASH_A)
    _file(db, rid, "b.pdf", content_hash=HASH_A, status="deleted")
    _file(db, rid, "c.pdf", status="deleted")
    assert related(db, me) == []


def test_related_strongest_reason_wins(db, rid):
    me = _file(db, rid, "a.pdf", content_hash=HASH_A)
    twin = _file(db, rid, "b.pdf", content_hash=HASH_A)
    db.execute("INSERT INTO edges VALUES (?, 'REFERENCES', ?, '')", (me, twin))
    out = related(db, me)
    assert [r.reason for r in out] == ["duplicate"]


def test_related_similar_content_from_vectors(db, rid):
    me = _file(db, rid, "a/me.pdf", content_hash=HASH_A)
    _file(db, rid, "b/near.pdf", content_hash=HASH_B)
    _file(db, rid, "c/far.pdf", content_hash=HASH_C)
    _chunk(db, HASH_A, 1)
    _chunk(db, HASH_B, 2)
    _chunk(db, HASH_B, 3)
    _chunk(db, HASH_C, 4)
    store = FakeStore([(1, 1.0), (3, 0.9), (2, 0.8), (4, 0.3)], known={1})
    out = related(db, me, store=store, limit=2)
    assert store.asked == [1]
    assert [(Path(r.path).name, r.reason) for r in out] == [
        ("near.pdf", "similar_content"),
        ("far.pdf", "similar_content"),
    ]
    assert out[0].score == pytest.approx(0.9)


def test_related_without_vectors_still_works(db, rid):
    me = _file(db, rid, "a.pdf", content_hash=HASH_A)
    _file(db, rid, "b.pdf")
    _chunk(db, HASH_A, 1)
    out = related(db, me, store=FakeStore([], known=set()))
    assert [r.reason for r in out] == ["same_folder"]


def test_related_respects_limit(db, rid):
    me = _file(db, rid, "a.pdf")
    for i in range(5):
        _file(db, rid, f"n{i}.pdf")
    assert len(related(db, me, limit=3)) == 3


def test_related_hides_excluded_roots(db, rid, tmp_path: Path):
    me = _file(db, rid, "a.pdf", content_hash=HASH_A)
    secret = _root(db, tmp_path / "secret", "secret")
    _file(db, secret, "salary.pdf", content_hash=HASH_A)
    assert [Path(r.path).name for r in related(db, me)] == ["salary.pdf"]
    assert related(db, me, exclude_root_ids={secret}) == []


def test_related_unknown_file_is_not_found(db, rid):
    with pytest.raises(ToolError) as err:
        related(db, 999)
    assert err.value.code == "not_found"
