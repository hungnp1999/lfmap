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


def test_italic_opening_sentence_is_not_a_heading():
    text = (
        "# *Tài liệu này mô tả quy trình mua sắm thiết bị văn phòng cho toàn công ty ABC.*\n\n"
        "Nội dung mở đầu.\n\n# Phạm vi\n\nÁp dụng cho mọi phòng ban.\n"
    )
    chunks = chunk_markdown(text)
    _assert_slices(text, chunks)
    assert _with(chunks, "Nội dung mở đầu").heading_path == ""
    assert _with(chunks, "Áp dụng").heading_path == "Phạm vi"


def test_overlong_heading_is_body_text():
    title = "Báo cáo " + "rất dài " * 20
    chunks = chunk_markdown(f"# A\n\n## {title}\n\nPhần thân.\n")
    assert _with(chunks, "Phần thân").heading_path == "A"


def test_short_headings_with_punctuation_are_kept():
    chunks = chunk_markdown("# Điều 1.\n\nPhần một.\n\n# Vì sao cần quy trình này?\n\nPhần hai.\n")
    assert _with(chunks, "Phần một").heading_path == "Điều 1."
    assert _with(chunks, "Phần hai").heading_path == "Vì sao cần quy trình này?"
