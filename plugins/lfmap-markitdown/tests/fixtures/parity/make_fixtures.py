"""Build the TC-M8 parity fixtures: synthetic files only, no real documents.

Run from the lfmap repo root with the ocr extra synced (needs fontTools and Pillow):
    uv run --no-sync python make_fixtures.py <output folder> [font.ttf]

The embedded font is a glyph subset of Liberation Sans (SIL OFL 1.1), embedding allowed.
"""

import ctypes
import io
import sys
import zipfile
from pathlib import Path

GOOD = "Ngày hiệu chuẩn: 15/03/2026. Thiết bị đạt yêu cầu kỹ thuật."
TCVN3 = "Ngµy hiÖu chuÈn: 15/03/2026. ThiÕt bÞ ®¹t yªu cÇu kü thuËt."
FONT = Path(sys.argv[2] if len(sys.argv) > 2 else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf")


def subset_font() -> bytes:
    from fontTools import subset

    options = subset.Options()
    font = subset.load_font(str(FONT), options)
    subsetter = subset.Subsetter(options)
    subsetter.populate(text=GOOD + TCVN3 + "0123456789 .:/")
    subsetter.subset(font)
    buffer = io.BytesIO()
    subset.save_font(font, buffer, options)
    return buffer.getvalue()


def make_pdf(path: Path, layers: list[str], font_data: bytes) -> None:
    import pypdfium2 as pdfium
    import pypdfium2.raw as raw

    pdf = pdfium.PdfDocument.new()
    for layer in layers:
        page = pdf.new_page(595, 144)
        if layer == "scan":
            from PIL import Image, ImageDraw

            image = Image.new("RGB", (1240, 300), "white")
            ImageDraw.Draw(image).rectangle((100, 120, 1100, 180), fill="black")
            picture = pdfium.PdfImage.new(pdf)
            picture.set_bitmap(pdfium.PdfBitmap.from_pil(image))
            picture.set_matrix(pdfium.PdfMatrix().scale(595, 144))
            page.insert_obj(picture)
        else:
            if layer == "good":
                data = (ctypes.c_uint8 * len(font_data)).from_buffer_copy(font_data)
                font = raw.FPDFText_LoadFont(pdf.raw, data, len(font_data), raw.FPDF_FONT_TRUETYPE, True)
                text = GOOD
            else:
                font = raw.FPDFText_LoadStandardFont(pdf.raw, b"Helvetica")
                text = TCVN3 if layer == "tcvn3" else GOOD
            obj = raw.FPDFPageObj_CreateTextObj(pdf.raw, font, 10)
            buffer = ctypes.create_string_buffer((text + "\0").encode("utf-16-le"))
            raw.FPDFText_SetText(obj, ctypes.cast(buffer, ctypes.POINTER(raw.FPDF_WCHAR)))
            raw.FPDFPageObj_Transform(obj, 1, 0, 0, 1, 20, 60)
            raw.FPDFPage_InsertObject(page.raw, obj)
        page.gen_content()
        page.close()
    pdf.save(path)
    pdf.close()


def make_docx(path: Path) -> None:
    parts = {
        "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',  # noqa: E501
        "_rels/.rels": '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="word/document.xml" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"/></Relationships>',  # noqa: E501
        "word/document.xml": f'<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>{GOOD}</w:t></w:r></w:p></w:body></w:document>',  # noqa: E501
    }
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in parts.items():
            archive.writestr(name, content)


def main(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    font = subset_font()
    make_pdf(out / "good.pdf", ["good"], font)
    make_pdf(out / "tcvn3.pdf", ["tcvn3"], font)
    make_pdf(out / "broken.pdf", ["broken"], font)
    make_pdf(out / "mixed.pdf", ["good", "tcvn3", "good"], font)
    make_pdf(out / "scan.pdf", ["scan"], font)
    make_docx(out / "report.docx")
    from openpyxl import Workbook

    book = Workbook()
    book.active.append(["Thiết bị", "Số lượng"])
    book.active.append(["Đồng hồ áp suất", 3])
    book.save(out / "list.xlsx")
    (out / "page.html").write_text(f"<html><body><h1>{GOOD}</h1></body></html>", encoding="utf-8")
    (out / "old.doc").write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + bytes(504))
    (out / "data.xyz").write_text("x", encoding="utf-8")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
