"""Ported from MarkitdownTool tests/test_document_core.py @ 923ff35 (TextQualityTests, PdfTextReportTests)."""

import sys
from pathlib import Path

import pytest

from lfmap_markitdown.quality import PdfTextReport, analyze_pdf_text, is_garbled_word, text_quality

sys.path.insert(0, str(Path(__file__).parent))
import pdf_samples  # noqa: E402

needs_arial = pytest.mark.skipif(not pdf_samples.ARIAL.exists(), reason="needs the Arial font")


@pytest.mark.parametrize(
    "text",
    [
        "Ngày hiệu chuẩn: 15/03/2026. Thiết bị đạt yêu cầu kỹ thuật.",
        "Nhiệt độ 25°C ±0.5, độ dày 12 µm, ©2026 Công ty ABC®.",
        "Größe, façade, naïve, Ærø, São Paulo, Zürich, McDonald's, iPhone.",
    ],
)
def test_correct_text_in_several_languages_scores_one(text: str) -> None:
    assert text_quality(text)[0] == 1


@pytest.mark.parametrize("word", ["hi\ufffdu", "hiÿu", "Ngµy", "®¹t", "hiÖu", "chuÈn", "a\x9bb", "x\ue000", "6ҧQ", "6͙"])
def test_garbled_words(word: str) -> None:
    assert is_garbled_word(word)


@pytest.mark.parametrize(
    "word", ["25°C", "µm", "ABC®", "«quoted»", "Ærø", "ĐẠT", "Ngày", "10kΩ", "Δt", "Москва", "ngày"]
)
def test_correct_words(word: str) -> None:
    assert not is_garbled_word(word)


def test_words_separated_by_control_characters() -> None:
    # Seen in real PDFs: pdfium returns U+0003 between words instead of a space.
    assert text_quality("Người\x03lập\x03biểu (Ký,\x03họ\x03tên) Kế\x03toán\x03trưởng") == (1.0, 9)


def test_wrongly_encoded_text_scores_low() -> None:
    assert text_quality("Biªn b¶n kiÓm tra thiÕt bÞ ®o l−êng")[0] < 0.5
    assert text_quality("Ngay hi\ufffdu chudn: Thi\ufffdt b\ufffd \ufffdat")[0] < 0.5


def test_too_little_text_is_not_judged() -> None:
    assert text_quality("Trang 3 / 12") == (None, 1)


def test_unreadable_pdf(tmp_path: Path) -> None:
    path = tmp_path / "bad.pdf"
    path.write_bytes(b"not a pdf")
    assert analyze_pdf_text(path) == PdfTextReport(False)


@needs_arial
def test_correct_text_layer(tmp_path: Path) -> None:
    report = analyze_pdf_text(pdf_samples.make_pdf(tmp_path / "good.pdf", "good"))
    assert report == PdfTextReport(True, (), (), 1.0)


@needs_arial
@pytest.mark.parametrize(
    ("layers", "pages"), [(("tcvn3",), (1,)), (("broken",), (1,)), (("good", "tcvn3", "good"), (2,))]
)
def test_garbled_text_layers_are_reported_per_page(tmp_path: Path, layers: tuple[str, ...], pages: tuple[int]) -> None:
    report = analyze_pdf_text(pdf_samples.make_pdf(tmp_path / "sample.pdf", *layers))
    assert report.readable and report.low_quality_pages == pages
    assert report.text_quality is not None and report.text_quality < 0.8


def test_empty_pdf_page_is_reported(tmp_path: Path) -> None:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument.new()
    pdf.new_page(595, 842).close()
    pdf.save(tmp_path / "blank.pdf")
    pdf.close()
    assert analyze_pdf_text(tmp_path / "blank.pdf") == PdfTextReport(True, (1,), (), None)
