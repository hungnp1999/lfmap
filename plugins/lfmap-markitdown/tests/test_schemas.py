import pytest
from pydantic import ValidationError

from lfmap_core.registry import load_entry
from lfmap_markitdown import formats
from lfmap_markitdown.schemas import ClassifyInput, ConvertInput, ExportInput, InfoInput


def test_inputs_accept_valid_examples() -> None:
    assert ClassifyInput(path=r"D:\Docs\a.pdf").path == r"D:\Docs\a.pdf"
    convert = ConvertInput(path=r"D:\Docs\a.pdf")
    assert (convert.ocr, convert.force_ocr, convert.max_chars) == (False, False, 2_000_000)
    export = ExportInput(path=r"D:\Docs", output_dir=r"D:\Exports", recursive=True)
    assert (export.recursive, export.overwrite) == (True, False)
    InfoInput()


def test_max_chars_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        ConvertInput(path="a.pdf", max_chars=0)


def test_format_groups_do_not_overlap() -> None:
    assert not formats.DOCUMENT_EXTENSIONS & formats.IMAGE_EXTENSIONS
    assert not formats.OFFICE_GUI_ONLY & set(formats.all_formats())
    assert ".pdf" in formats.all_formats()


def test_manifest_matches_tool() -> None:
    from lfmap_markitdown.tool import MarkitdownTool

    entry = load_entry(MarkitdownTool)
    assert entry.id == "markitdown"
    assert sorted(op.name for op in entry.manifest.operations) == ["classify", "convert", "export", "info"]
