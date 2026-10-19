import os
import sys
from pathlib import Path

import pytest

from lfmap_core import ToolContext, ToolError
from lfmap_core.permissions import PermissionManager
from lfmap_markitdown.backends import ocr
from lfmap_markitdown.schemas import ExportInput
from lfmap_markitdown.tool import MarkitdownTool

sys.path.insert(0, str(Path(__file__).parent))
import builders  # noqa: E402


@pytest.fixture(autouse=True)
def no_ocr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ocr, "find_tesseract", lambda: None)


@pytest.fixture
def source(root: Path) -> Path:
    folder = root / "in"
    folder.mkdir()
    builders.make_docx(folder / "report.docx", "Calibration report ABC")
    (folder / "old.doc").write_bytes(b"legacy")
    (folder / "data.xyz").write_bytes(b"other")
    return folder


def _by_name(result) -> dict[str, tuple[str, str]]:
    return {Path(f.source).name: (f.status, f.reason_code) for f in result.files}


def test_export_folder(tool: MarkitdownTool, root: Path, source: Path) -> None:
    out = root / "out"
    result = tool.export(ExportInput(path=str(source), output_dir=str(out)))
    assert (result.total, result.succeeded, result.skipped, result.failed) == (3, 1, 2, 0)
    assert _by_name(result) == {
        "report.docx": ("success", ""),
        "old.doc": ("skipped", "office_gui_only"),
        "data.xyz": ("skipped", "unsupported_format"),
    }
    assert "Calibration report ABC" in (out / "report.docx.md").read_text(encoding="utf-8")
    assert sorted(p.name for p in out.iterdir()) == ["report.docx.md"]


def test_existing_output_is_skipped(tool: MarkitdownTool, root: Path, source: Path) -> None:
    inp = ExportInput(path=str(source), output_dir=str(root / "out"))
    tool.export(inp)
    assert _by_name(tool.export(inp))["report.docx"] == ("skipped", "exists")


def test_overwrite_asks_once_and_refusal_writes_nothing(tool: MarkitdownTool, root: Path, source: Path) -> None:
    out = root / "out"
    tool.export(ExportInput(path=str(source), output_dir=str(out)))
    (out / "report.docx.md").write_text("kept", encoding="utf-8")
    asked: list[tuple[str, str, str]] = []

    def refuse(tier: str, reason: str, detail: str) -> None:
        asked.append((tier, reason, detail))
        raise ToolError("permission_denied", "refused")

    tool.ctx.approver = refuse
    with pytest.raises(ToolError) as caught:
        tool.export(ExportInput(path=str(source), output_dir=str(out), overwrite=True))
    assert caught.value.code == "permission_denied"
    assert asked == [("T2", "overwrite", str(out))]
    assert (out / "report.docx.md").read_text(encoding="utf-8") == "kept"

    tool.ctx.approver = lambda *args: asked.append(args)
    result = tool.export(ExportInput(path=str(source), output_dir=str(out), overwrite=True))
    assert _by_name(result)["report.docx"] == ("success", "")
    assert "Calibration" in (out / "report.docx.md").read_text(encoding="utf-8")


def test_new_files_need_no_approval(tool: MarkitdownTool, root: Path, source: Path) -> None:
    tool.ctx.approver = lambda *args: pytest.fail("no approval expected")
    assert tool.export(ExportInput(path=str(source), output_dir=str(root / "out"), overwrite=True)).succeeded == 1


def test_output_dir_outside_write_roots(root: Path, source: Path, tmp_path: Path) -> None:
    permissions = PermissionManager([str(root)], [str(root / "exports")])
    tool = MarkitdownTool(ToolContext(plugin_id="markitdown", permissions=permissions))
    with pytest.raises(ToolError) as caught:
        tool.export(ExportInput(path=str(source), output_dir=str(root / "elsewhere")))
    assert caught.value.code == "permission_denied"


def test_relative_output_dir_is_refused(tool: MarkitdownTool, source: Path) -> None:
    with pytest.raises(ToolError) as caught:
        tool.export(ExportInput(path=str(source), output_dir="out"))
    assert caught.value.code == "invalid_input"


def test_recursive_keeps_subfolders(tool: MarkitdownTool, root: Path, source: Path) -> None:
    (source / "sub").mkdir()
    builders.make_docx(source / "sub" / "inner.docx", "Inner ABC")
    out = root / "out"
    assert tool.export(ExportInput(path=str(source), output_dir=str(out))).total == 3
    result = tool.export(ExportInput(path=str(source), output_dir=str(out), recursive=True))
    assert _by_name(result)["inner.docx"] == ("success", "")
    assert (out / "sub" / "inner.docx.md").exists()


def test_single_file(tool: MarkitdownTool, root: Path, source: Path) -> None:
    result = tool.export(ExportInput(path=str(source / "report.docx"), output_dir=str(root / "out")))
    assert (result.total, result.succeeded) == (1, 1)
    assert (root / "out" / "report.docx.md").exists()


@pytest.mark.skipif(os.name == "nt", reason="symlinks need privileges on Windows; junctions are tested there")
def test_linked_folder_is_not_entered(tool: MarkitdownTool, root: Path, source: Path, tmp_path: Path) -> None:
    linked = root / "linked"
    linked.mkdir()
    builders.make_docx(linked / "hidden.docx", "Linked ABC")
    os.symlink(linked, source / "link", target_is_directory=True)
    result = tool.export(ExportInput(path=str(source), output_dir=str(root / "out"), recursive=True))
    assert "hidden.docx" not in _by_name(result)


@pytest.mark.skipif(os.name != "nt", reason="junctions exist only on Windows")
def test_junction_is_not_entered(tool: MarkitdownTool, root: Path, source: Path) -> None:
    import subprocess

    linked = root / "linked"
    linked.mkdir()
    builders.make_docx(linked / "hidden.docx", "Linked ABC")
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(source / "junction"), str(linked)], check=True, capture_output=True
    )
    result = tool.export(ExportInput(path=str(source), output_dir=str(root / "out"), recursive=True))
    assert "hidden.docx" not in _by_name(result)


def test_scan_limit(tool: MarkitdownTool, root: Path, source: Path) -> None:
    tool.ctx.settings["max_files"] = 2
    with pytest.raises(ToolError) as caught:
        tool.export(ExportInput(path=str(source), output_dir=str(root / "out")))
    assert caught.value.details["limit"] == "max_files"
