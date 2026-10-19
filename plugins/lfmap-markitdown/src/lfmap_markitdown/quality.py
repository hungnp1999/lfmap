"""Text-layer quality checks, ported from MarkitdownTool `document_core.py` @ 923ff35 (same author).

A PDF page whose extracted words look wrongly encoded (legacy TCVN3 fonts, fonts without a
Unicode map) renders correctly but yields garbage text; such pages need OCR.
"""

import unicodedata
from dataclasses import dataclass
from pathlib import Path

# Pages whose share of correctly encoded words is below this are OCRed again (force OCR).
TEXT_QUALITY_THRESHOLD = 0.8
# Pages with fewer words that contain letters are not judged.
MIN_JUDGED_WORDS = 3
# Latin-1 symbols that legitimately touch letters or numbers (25°C, ±0.5, µm, ABC®).
_COMMON_SYMBOLS = frozenset("°±©®«»§²³¼½¾·µ")


@dataclass(frozen=True)
class PdfTextReport:
    readable: bool
    empty_pages: tuple[int, ...] = ()
    low_quality_pages: tuple[int, ...] = ()
    text_quality: float | None = None


def _is_broken_char(char: str) -> bool:
    return char in "\ufffd\xff" or "\ue000" <= char <= "\uf8ff" or "\x80" <= char <= "\x9f"


def _script(char: str) -> str:
    return unicodedata.name(char, "").split(" ", 1)[0]


def is_garbled_word(word: str) -> bool:
    """Signs that a word was extracted with the wrong encoding, independent of its language:

    - replacement, private-use or C1 control characters, or U+00FF, which broken encodings
      produce for every character they cannot map ("hi�u", "hiÿu");
    - a Latin-1 symbol (U+00A1-U+00BF) between two letters, as TCVN3 fonts produce ("Ngµy"),
      or an uncommon one anywhere in a word with letters ("®¹t");
    - an accented Latin capital right after a lowercase letter ("hiÖu", "chuÈn"), which TCVN3
      produces for lowercase toned vowels;
    - Latin and Cyrillic letters in one word, or a combining mark that follows no letter,
      as fonts without a usable Unicode map produce ("3+Ҫ1", "6͙").
    """
    has_letters = any(char.isalpha() for char in word)
    scripts: set[str] = set()
    for index, char in enumerate(word):
        previous = word[index - 1] if index else ""
        following = word[index + 1] if index + 1 < len(word) else ""
        if _is_broken_char(char):
            return True
        if "¡" <= char <= "¿":
            if char not in _COMMON_SYMBOLS and has_letters:
                return True
            if previous.isalpha() and following.isalpha():
                return True
        elif char.isupper() and not char.isascii() and previous.islower() and _script(char) == "LATIN":
            return True
        elif unicodedata.category(char) == "Mn" and not (
            previous.isalpha() or unicodedata.category(previous or " ") == "Mn"
        ):
            return True
        if char.isalpha():
            scripts.add(_script(char))
    return {"LATIN", "CYRILLIC"} <= scripts


def _words(text: str) -> list[str]:
    # Some PDFs separate words with C0 control characters (often U+0003) instead of spaces.
    separated = "".join(" " if unicodedata.category(char) == "Cc" else char for char in text)
    return [word for word in separated.split() if any(char.isalpha() or _is_broken_char(char) for char in word)]


def text_quality(text: str) -> tuple[float | None, int]:
    """Share of words that look correctly encoded, and how many words were judged.

    The score is None when fewer than MIN_JUDGED_WORDS words contain letters.
    """
    words = _words(text)
    if len(words) < MIN_JUDGED_WORDS:
        return None, len(words)
    return 1 - sum(is_garbled_word(word) for word in words) / len(words), len(words)


def analyze_pdf_text(pdf_path: Path | str | bytes) -> PdfTextReport:
    """Find pages without text and pages whose text layer looks wrongly encoded.

    Accepts the PDF bytes as well, so a caller can analyse what it already read from one handle.
    """
    try:
        import pypdfium2 as pdfium

        empty: list[int] = []
        low_quality: list[int] = []
        weighted, judged = 0.0, 0
        with pdfium.PdfDocument(pdf_path if isinstance(pdf_path, bytes) else str(pdf_path)) as document:
            for page_index in range(len(document)):
                page = document[page_index]
                try:
                    text_page = page.get_textpage()
                    try:
                        text = text_page.get_text_bounded()
                    finally:
                        text_page.close()
                finally:
                    page.close()
                if not text.strip():
                    empty.append(page_index + 1)
                    continue
                quality, words = text_quality(text)
                if quality is None:
                    continue
                weighted += quality * words
                judged += words
                if quality < TEXT_QUALITY_THRESHOLD:
                    low_quality.append(page_index + 1)
        return PdfTextReport(True, tuple(empty), tuple(low_quality), round(weighted / judged, 3) if judged else None)
    except Exception:
        return PdfTextReport(False)
