"""OCR backend (the `ocr` extra): OCRmyPDF + Tesseract, ported from MarkitdownTool `document_core.py` @ 923ff35.

OCRmyPDF is imported only inside functions, so the plugin loads without the extra. Ghostscript (AGPL)
is never used: pages are rasterized with pypdfium and the output is a plain PDF, not PDF/A.
"""

import importlib.util
import os
import shutil
import subprocess
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, BinaryIO

from lfmap_core import ToolError
from lfmap_markitdown.formats import IMAGE_EXTENSIONS

# Used when an image has no usable resolution metadata; OCRmyPDF refuses such images otherwise.
DEFAULT_IMAGE_DPI = 300
LOCK_TIMEOUT_SECONDS = 300
_WINDOWS_CANDIDATES = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
)
# OCR rewrites process-wide environment variables (PATH, TESSDATA_PREFIX), so runs must not overlap.
_lock = threading.Lock()


def find_tesseract() -> str | None:
    executable = shutil.which("tesseract")
    if executable:
        return executable
    if os.name == "nt":
        for candidate in _WINDOWS_CANDIDATES:
            if os.path.isfile(candidate):
                return candidate
    return None


def ocr_available() -> bool:
    """The `ocr` extra is installed and Tesseract can be found."""
    return importlib.util.find_spec("ocrmypdf") is not None and find_tesseract() is not None


def available_languages(tessdata_dir: str | None = None) -> list[str]:
    """Languages Tesseract can use; nothing is downloaded."""
    tesseract = find_tesseract()
    if tesseract is None:
        return []
    environment = os.environ.copy()
    if tessdata_dir:
        environment["TESSDATA_PREFIX"] = tessdata_dir
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        result = subprocess.run(
            [tesseract, "--list-langs"],
            capture_output=True,
            text=True,
            timeout=30,
            env=environment,
            creationflags=flags,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    lines = result.stdout.splitlines()
    return sorted(line.strip() for line in lines[1:] if line.strip())


@contextmanager
def hide_ocr_console_windows() -> Iterator[None]:
    if os.name != "nt":
        yield
        return

    from ocrmypdf.subprocess import _run as ocrmypdf_subprocess

    original_run = ocrmypdf_subprocess.subprocess_run
    original_popen = ocrmypdf_subprocess.Popen
    creation_flag = subprocess.CREATE_NO_WINDOW

    def run_without_console(*args: Any, **kwargs: Any) -> Any:
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | creation_flag
        return original_run(*args, **kwargs)

    def popen_without_console(*args: Any, **kwargs: Any) -> Any:
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | creation_flag
        return original_popen(*args, **kwargs)

    ocrmypdf_subprocess.subprocess_run = run_without_console
    ocrmypdf_subprocess.Popen = popen_without_console
    try:
        yield
    finally:
        ocrmypdf_subprocess.subprocess_run = original_run
        ocrmypdf_subprocess.Popen = original_popen


def _has_alpha(image: Any) -> bool:
    return image.mode in ("RGBA", "LA", "PA") or "transparency" in image.info


def _flatten(frame: Any) -> Any:
    from PIL import Image

    rgba = frame.convert("RGBA")
    background = Image.new("RGB", rgba.size, "white")
    background.paste(rgba, mask=rgba.getchannel("A"))
    return background


def prepare_image_input(stream: BinaryIO, work_dir: Path) -> tuple[str | BinaryIO, dict[str, Any]]:
    """Make an image acceptable to OCRmyPDF, which refuses images without a resolution and
    images with an alpha channel. Returns the input to pass on and extra OCRmyPDF options."""
    from PIL import Image, ImageSequence

    with Image.open(stream) as image:
        dpi = image.info.get("dpi")
        usable_dpi = bool(dpi) and min(dpi) >= 50
        options: dict[str, Any] = {} if usable_dpi else {"image_dpi": DEFAULT_IMAGE_DPI}
        if not _has_alpha(image):
            stream.seek(0)
            return stream, options
        frames = [_flatten(frame) for frame in ImageSequence.Iterator(image)]

    flattened = work_dir / "flattened.tiff"
    frames[0].save(
        flattened,
        save_all=True,
        append_images=frames[1:],
        compression="tiff_deflate",
        dpi=dpi if usable_dpi else (DEFAULT_IMAGE_DPI, DEFAULT_IMAGE_DPI),
    )
    return str(flattened), options


def ocr_to_pdf(
    stream: BinaryIO,
    extension: str,
    temp_dir: Path,
    languages: list[str],
    force_pages: tuple[int, ...] | None = None,
    tessdata_dir: str | None = None,
) -> Path:
    """OCR into a searchable PDF inside temp_dir. Pages that already have text are kept, unless
    force_pages is given: then the text layer is replaced on those pages, or on every page when it
    is empty. The caller deletes the returned file."""
    import ocrmypdf

    tesseract = find_tesseract()
    if tesseract is None:
        raise ToolError("backend_unavailable", "Tesseract was not found", {"reason_code": "ocr_unavailable"})
    temp_dir.mkdir(parents=True, exist_ok=True)
    output_pdf = temp_dir / f"ocr-{os.getpid()}-{threading.get_ident()}.pdf"
    if not _lock.acquire(timeout=LOCK_TIMEOUT_SECONDS):
        raise ToolError("timeout", "Another OCR run is still busy")
    previous = {key: os.environ.get(key) for key in ("PATH", "TESSDATA_PREFIX")}
    try:
        os.environ["PATH"] = str(Path(tesseract).parent) + os.pathsep + os.environ.get("PATH", "")
        if tessdata_dir:
            os.environ["TESSDATA_PREFIX"] = tessdata_dir
        work_dir = temp_dir / f"work-{os.getpid()}-{threading.get_ident()}"
        work_dir.mkdir(exist_ok=True)
        try:
            input_file, image_options = (
                prepare_image_input(stream, work_dir) if extension in IMAGE_EXTENSIONS else (stream, {})
            )
            if force_pages is None:
                text_options: dict[str, Any] = {"skip_text": True}
            else:
                text_options = {"force_ocr": True}
                if force_pages:
                    text_options["pages"] = ",".join(str(page) for page in force_pages)
            with hide_ocr_console_windows():
                exit_code = ocrmypdf.ocr(
                    input_file,
                    str(output_pdf),
                    language=languages,
                    output_type="pdf",
                    rasterizer="pypdfium",
                    deskew=True,
                    rotate_pages=True,
                    progress_bar=False,
                    use_threads=True,  # a process pool forks a threaded host (MCP server)
                    **text_options,
                    **image_options,
                )
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        _lock.release()
    if exit_code != ocrmypdf.ExitCode.ok:
        output_pdf.unlink(missing_ok=True)
        raise ToolError("internal", f"OCRmyPDF failed with exit code {exit_code}")
    return output_pdf
