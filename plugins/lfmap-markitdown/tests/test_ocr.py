import io
import shutil
from pathlib import Path

import pytest

from lfmap_markitdown.backends import ocr
from lfmap_markitdown.backends.markitdown import MarkItDownBackend

needs_ocr = pytest.mark.skipif(not ocr.ocr_available(), reason="needs the ocr extra and Tesseract")
TEXT = "INSPECTION PASSED"


def _png(alpha: bool = False) -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGBA" if alpha else "RGB", (1400, 300), (255, 255, 255, 255) if alpha else "white")
    ImageDraw.Draw(image).text((60, 100), TEXT, fill="black", font=ImageFont.load_default(size=96))
    buffer = io.BytesIO()
    image.save(buffer, "PNG", dpi=(300, 300))
    return buffer.getvalue()


@needs_ocr
@pytest.mark.parametrize("alpha", [False, True])
def test_image_to_searchable_pdf(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, alpha: bool) -> None:
    from ocrmypdf.subprocess import _run

    calls: list[str] = []
    original = _run.run

    def recording_run(args, *rest, **kwargs):
        calls.append(Path(str(args[0])).stem.lower())
        return original(args, *rest, **kwargs)

    monkeypatch.setattr(_run, "run", recording_run)
    real_which = shutil.which
    monkeypatch.setattr(shutil, "which", lambda name, *a, **k: None if "gs" in name else real_which(name, *a, **k))

    pdf = ocr.ocr_to_pdf(io.BytesIO(_png(alpha)), ".png", tmp_path / "tmp", ["eng"])
    try:
        with open(pdf, "rb") as stream:
            markdown = MarkItDownBackend().to_markdown(stream, ".pdf", pdf.name)
    finally:
        pdf.unlink()
    assert "INSPECTION" in markdown.upper()
    assert not {"gs", "gswin64c", "gswin32c"} & set(calls)
    assert list((tmp_path / "tmp").iterdir()) == []


@needs_ocr
def test_languages_include_english() -> None:
    assert "eng" in ocr.available_languages()


def test_missing_tesseract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ocr, "find_tesseract", lambda: None)
    assert not ocr.ocr_available()
    assert ocr.available_languages() == []
