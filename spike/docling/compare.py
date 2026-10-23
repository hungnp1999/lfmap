"""Convert each PDF with MarkItDown and Docling; write both Markdown files and a timing table.

Usage: python compare.py <pdf_dir> <out_dir> [artifacts_path]
Set HF_HUB_OFFLINE=1 together with artifacts_path to prove offline operation, ORT_DISABLE_TELEMETRY=1
to silence onnxruntime telemetry, ACCEL_DEVICE (cpu|cuda|auto), and TESSERACT_CMD to OCR with Tesseract instead of RapidOCR.
"""

import os
import sys
import time
from pathlib import Path

pdf_dir, out_dir = Path(sys.argv[1]), Path(sys.argv[2])
artifacts = sys.argv[3] if len(sys.argv) > 3 else None
out_dir.mkdir(parents=True, exist_ok=True)

from markitdown import MarkItDown  # noqa: E402

started = time.perf_counter()
from docling.datamodel.accelerator_options import AcceleratorOptions  # noqa: E402
from docling.datamodel.base_models import InputFormat  # noqa: E402
from docling.datamodel.pipeline_options import PdfPipelineOptions, TesseractCliOcrOptions  # noqa: E402
from docling.document_converter import DocumentConverter, PdfFormatOption  # noqa: E402

options = PdfPipelineOptions(artifacts_path=artifacts) if artifacts else PdfPipelineOptions()
options.do_ocr = True
tesseract = os.environ.get("TESSERACT_CMD")
if tesseract:
    # Reuse the Tesseract the ocr extra already needs, instead of RapidOCR (downloads from modelscope.cn).
    options.ocr_options = TesseractCliOcrOptions(lang=os.environ.get("OCR_LANG", "eng").split("+"), tesseract_cmd=tesseract)
options.do_table_structure = True
options.accelerator_options = AcceleratorOptions(device=os.environ.get("ACCEL_DEVICE", "auto"))
print(f"device {options.accelerator_options.device}")
docling = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)})
print(f"docling import+init {time.perf_counter() - started:.1f}s")
markitdown = MarkItDown(enable_plugins=False)

for pdf in sorted(pdf_dir.glob("*.pdf")):
    t0 = time.perf_counter()
    md_a = markitdown.convert(str(pdf)).markdown
    t1 = time.perf_counter()
    md_b = docling.convert(pdf).document.export_to_markdown()
    t2 = time.perf_counter()
    (out_dir / f"{pdf.stem}.markitdown.md").write_text(md_a, encoding="utf-8")
    (out_dir / f"{pdf.stem}.docling.md").write_text(md_b, encoding="utf-8")
    headings = (md_a.count("\n#") + md_a.startswith("#"), md_b.count("\n#") + md_b.startswith("#"))
    print(f"{pdf.name}: markitdown {t1 - t0:.2f}s {len(md_a)} chars {headings[0]} headings | "
          f"docling {t2 - t1:.2f}s {len(md_b)} chars {headings[1]} headings")
