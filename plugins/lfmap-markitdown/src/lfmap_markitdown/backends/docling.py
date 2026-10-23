"""Docling backend (the `docling` extra), PDF only and offline: models come from a local folder.

Docling and torch are imported only inside DoclingBackend, after force_offline(), so the plugin loads
without the extra and Hugging Face never tries the network.
"""

import functools
import importlib.util
import io
import os
import threading
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from typing import BinaryIO

from lfmap_markitdown.headings import fix_heading_levels

LAYOUT_MODEL = "docling-project--docling-layout-heron"
TABLE_MODEL = "docling-project--docling-models"


def docling_installed() -> bool:
    """The extra is installed; nothing is imported."""
    return importlib.util.find_spec("docling") is not None and importlib.util.find_spec("cv2") is not None


def docling_version() -> str:
    try:
        return version("docling-slim")
    except PackageNotFoundError:
        return ""


def missing_models(artifacts_path: str) -> list[str]:
    """Model folders that `docling-tools models download layout tableformer` creates, if absent."""
    return [name for name in (LAYOUT_MODEL, TABLE_MODEL) if not os.path.isdir(os.path.join(artifacts_path, name))]


def force_offline() -> None:
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"


@dataclass(frozen=True)
class DoclingOptions:
    artifacts_path: str
    ocr: bool = False
    full_page_ocr: bool = False
    languages: tuple[str, ...] = ("eng",)
    tesseract_cmd: str | None = None
    tessdata_dir: str | None = None
    device: str = "auto"
    threads: int = 4


class DoclingBackend:
    name = "docling"

    def __init__(self, options: DoclingOptions) -> None:
        force_offline()
        from docling.datamodel.accelerator_options import AcceleratorOptions
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import OcrMode, PdfPipelineOptions, TesseractCliOcrOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption

        extra = {}
        if options.ocr:
            mode = {"mode": OcrMode.FULL_PAGE} if options.full_page_ocr else {}
            extra["ocr_options"] = TesseractCliOcrOptions(
                lang=list(options.languages),
                tesseract_cmd=options.tesseract_cmd or "tesseract",
                path=options.tessdata_dir,
                **mode,
            )
        pipeline = PdfPipelineOptions(
            artifacts_path=options.artifacts_path,
            do_ocr=options.ocr,
            do_table_structure=True,
            enable_remote_services=False,
            accelerator_options=AcceleratorOptions(device=options.device, num_threads=options.threads),
            **extra,
        )
        self._converter = DocumentConverter(
            allowed_formats=[InputFormat.PDF],
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline)},
        )
        self._lock = threading.Lock()

    def version(self) -> str:
        return docling_version()

    def to_markdown(self, stream: BinaryIO, extension: str, filename: str) -> str:
        from docling_core.types.io import DocumentStream

        source = DocumentStream(name=filename, stream=io.BytesIO(stream.read()))
        with self._lock:
            result = self._converter.convert(source, raises_on_error=True)
        return fix_heading_levels(result.document.export_to_markdown())


@functools.lru_cache(maxsize=2)
def get_backend(options: DoclingOptions) -> DoclingBackend:
    """Building a converter loads about 700 MB of models in about 5 s, so keep it for the process."""
    return DoclingBackend(options)
