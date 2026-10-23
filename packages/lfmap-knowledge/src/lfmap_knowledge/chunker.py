"""Split Markdown into citation-friendly chunks by heading, paragraph and table."""

import re
from dataclasses import dataclass

_HEADING = re.compile(r"^(#{1,6})[ \t]+(.*)$", re.MULTILINE)
_SENTENCE_ENDS = (". ", "? ", "! ")
HEADING_MAX_CHARS = 120
SENTENCE_HEADING_WORDS = 8


@dataclass(frozen=True)
class Chunk:
    """One chunk; text == source[char_start:char_end] except for repeated-header table pieces."""

    ordinal: int
    heading_path: str
    char_start: int
    char_end: int
    text: str


Span = tuple[int, int, str]  # char_start, char_end, text


def chunk_markdown(text: str, target_chars: int = 1500, max_chars: int = 3000) -> list[Chunk]:
    """Chunk Markdown without overlap; offsets point into text for citations.

    Sections start at ATX headings and carry a heading path such as "A > B". A heading line
    that reads like body text (see _is_heading) stays in the current section. Blocks (runs of
    non-blank lines) are merged up to target_chars. A paragraph longer than max_chars is cut at
    a sentence boundary or hard cut. A table longer than max_chars is cut by rows and every
    piece repeats the header and separator lines; for those pieces char_start/char_end cover
    only the data rows in text, so text is not a slice of the source.
    """
    spans: list[tuple[str, Span]] = []
    for start, end, path in _sections(text):
        spans.extend((path, span) for span in _section_spans(text, start, end, target_chars, max_chars))
    return [Chunk(i, path, s, e, chunk_text) for i, (path, (s, e, chunk_text)) in enumerate(spans)]


def _sections(text: str) -> list[tuple[int, int, str]]:
    stack: list[tuple[int, str]] = []
    sections: list[tuple[int, int, str]] = []
    start, path = 0, ""
    for match in _HEADING.finditer(text):
        if not _is_heading(match.group(2)):
            continue
        sections.append((start, match.start(), path))
        level = len(match.group(1))
        stack = [(n, title) for n, title in stack if n < level] + [(level, match.group(2).strip())]
        start, path = match.start(), " > ".join(title for _, title in stack)
    sections.append((start, len(text), path))
    return [section for section in sections if section[0] < section[1]]


def _is_heading(title: str) -> bool:
    """False for a sentence markitdown turned into a heading, e.g. a .docx opening paragraph in italics.

    Such a title is longer than HEADING_MAX_CHARS, or ends with a period after at least
    SENTENCE_HEADING_WORDS words. Emphasis marks around the title are ignored.
    """
    plain = title.strip().strip("*_").strip()
    if len(plain) > HEADING_MAX_CHARS:
        return False
    return not (plain.endswith(".") and len(plain.split()) >= SENTENCE_HEADING_WORDS)


def _blocks(text: str, start: int, end: int) -> list[tuple[int, int]]:
    blocks: list[tuple[int, int]] = []
    block_start: int | None = None
    pos = start
    while pos < end:
        line_end = text.find("\n", pos, end)
        line_end = end if line_end == -1 else line_end
        if text[pos:line_end].strip():
            if block_start is None:
                block_start = pos
            last_end = line_end
        elif block_start is not None:
            blocks.append((block_start, last_end))
            block_start = None
        pos = line_end + 1
    if block_start is not None:
        blocks.append((block_start, last_end))
    return [(s, e - 1 if text[e - 1] == "\r" else e) for s, e in blocks]


def _section_spans(text: str, start: int, end: int, target_chars: int, max_chars: int) -> list[Span]:
    spans: list[Span] = []
    merged: tuple[int, int] | None = None

    def flush() -> None:
        nonlocal merged
        if merged is not None:
            spans.append((merged[0], merged[1], text[merged[0] : merged[1]]))
            merged = None

    for block_start, block_end in _blocks(text, start, end):
        if block_end - block_start > max_chars:
            flush()
            if _is_table(text[block_start:block_end]):
                spans.extend(_table_pieces(text, block_start, block_end, max_chars))
            else:
                spans.extend(_paragraph_pieces(text, block_start, block_end, max_chars))
        elif merged is not None and block_end - merged[0] <= target_chars:
            merged = (merged[0], block_end)
        else:
            flush()
            merged = (block_start, block_end)
    flush()
    return spans


def _is_table(block: str) -> bool:
    return all(line.lstrip().startswith("|") for line in block.splitlines())


def _paragraph_pieces(text: str, start: int, end: int, max_chars: int) -> list[Span]:
    pieces: list[Span] = []
    while end - start > max_chars:
        cut = _sentence_cut(text, start, start + max_chars)
        if text[start:cut].strip():
            pieces.append((start, cut, text[start:cut]))
        start = cut
        while start < end and text[start].isspace():
            start += 1
    if start < end and text[start:end].strip():
        pieces.append((start, end, text[start:end]))
    return pieces


def _sentence_cut(text: str, start: int, limit: int) -> int:
    best = text.rfind("\n", start + 1, limit)
    for mark in _SENTENCE_ENDS:
        found = text.rfind(mark, start, limit)
        if found != -1:
            best = max(best, found + 1)
    return best if best > start else limit


def _table_pieces(text: str, start: int, end: int, max_chars: int) -> list[Span]:
    lines = _line_spans(text, start, end)
    prefix = text[lines[0][0] : lines[1][1]] + "\n"
    pieces: list[Span] = []
    piece_start, extra, last = start, "", None  # the first piece is a plain slice that has the header
    for row_start, row_end in lines[2:]:
        if last is not None and len(extra) + row_end - piece_start > max_chars:
            pieces.append((piece_start, last, extra + text[piece_start:last]))
            piece_start, extra, last = row_start, prefix, None
        last = row_end
    if last is not None:
        pieces.append((piece_start, last, extra + text[piece_start:last]))
    return pieces


def _line_spans(text: str, start: int, end: int) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    pos = start
    while pos < end:
        line_end = text.find("\n", pos, end)
        line_end = end if line_end == -1 else line_end
        stop = line_end - 1 if line_end > pos and text[line_end - 1] == "\r" else line_end
        spans.append((pos, stop))
        pos = line_end + 1
    return spans
