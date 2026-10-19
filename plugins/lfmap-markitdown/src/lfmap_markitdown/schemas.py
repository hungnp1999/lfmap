from typing import Literal

from pydantic import BaseModel, Field

from lfmap_markitdown.formats import ReasonCode

PATH_DESCRIPTION = "Absolute path of a file inside an allowed folder."


class ClassifyInput(BaseModel):
    """A local file to inspect before conversion."""

    path: str = Field(description=PATH_DESCRIPTION, examples=[r"D:\Docs\report.pdf"])


class ClassifyOutput(BaseModel):
    path: str
    extension: str
    supported: bool = Field(description="The format can be converted (possibly after OCR).")
    needs_ocr: bool
    markdown_eligible: bool = Field(description="Convertible now without OCR.")
    reason_code: ReasonCode
    text_quality: float | None = Field(description="Share of correctly encoded words in a PDF text layer, 0-1.")
    low_quality_pages: list[int] = []
    ocr_available: bool


class ConvertInput(BaseModel):
    """Convert one local file to Markdown and return the text. Nothing is written to disk."""

    path: str = Field(description=PATH_DESCRIPTION, examples=[r"D:\Docs\report.pdf"])
    ocr: bool = Field(default=False, description="Run OCR when the file needs it (requires the ocr extra).")
    ocr_languages: str = Field(default="", description="Tesseract languages like 'vie+eng'; empty uses settings.")
    force_ocr: bool = Field(default=False, description="Replace the PDF text layer even if it looks fine.")
    max_chars: int = Field(default=2_000_000, ge=1, description="Truncate Markdown longer than this.")


class ConvertOutput(BaseModel):
    path: str
    markdown: str
    chars: int
    truncated: bool
    stage: Literal["markdown", "ocr_markdown"]
    text_quality: float | None
    sha256: str = Field(description="Hash of the bytes that were converted.")
    backend: str = "markitdown"
    backend_version: str


class ExportInput(BaseModel):
    """Convert a file or a folder and write Markdown files next to each other in output_dir."""

    path: str = Field(description="File or folder inside an allowed folder.", examples=[r"D:\Docs"])
    output_dir: str = Field(description="Absolute folder inside an allowed export folder.", examples=[r"D:\Exports"])
    recursive: bool = Field(default=False, description="Include subfolders when path is a folder.")
    ocr: bool = Field(default=False, description="Run OCR on files that need it (requires the ocr extra).")
    ocr_languages: str = Field(default="", description="Tesseract languages like 'vie+eng'; empty uses settings.")
    force_ocr: bool = Field(default=False, description="Replace PDF text layers even if they look fine.")
    overwrite: bool = Field(default=False, description="Replace Markdown files that already exist (asks first).")


class ExportedFile(BaseModel):
    source: str
    status: Literal["success", "skipped", "failed"]
    reason_code: ReasonCode
    outputs: list[str] = []
    message: str = ""


class ExportOutput(BaseModel):
    output_dir: str
    total: int
    succeeded: int
    skipped: int
    failed: int
    files: list[ExportedFile]


class InfoInput(BaseModel):
    """No input."""


class InfoOutput(BaseModel):
    plugin_version: str
    markitdown_version: str
    formats: list[str]
    ocr_available: bool
    tesseract_path: str | None
    ocr_languages: list[str]
