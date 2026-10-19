"""Folder scanning for export, ported from MarkitdownTool `document_core.scan_folder` @ 923ff35."""

import os
import stat
from collections.abc import Iterator
from pathlib import Path

from lfmap_markitdown.formats import DOCUMENT_EXTENSIONS, IMAGE_EXTENSIONS, OFFICE_GUI_ONLY

_KNOWN_EXTENSIONS = DOCUMENT_EXTENSIONS | IMAGE_EXTENSIONS | OFFICE_GUI_ONLY


class ScanLimitExceeded(Exception):
    def __init__(self, limit: str, value: int) -> None:
        super().__init__(f"{limit} exceeded ({value})")
        self.limit = limit
        self.value = value


def _is_document_name(name: str) -> bool:
    return os.path.splitext(name)[1].lower() in _KNOWN_EXTENSIONS and not name.startswith("~$")


def _is_hidden(entry: os.DirEntry) -> bool:
    if entry.name.startswith((".", "~$")):
        return True
    attributes = getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0)
    return bool(attributes & (stat.FILE_ATTRIBUTE_HIDDEN | stat.FILE_ATTRIBUTE_SYSTEM))


def scan_folder(folder: Path, recursive: bool, max_depth: int, max_files: int) -> list[Path]:
    """Files of known formats plus other visible files (reported as unsupported), sorted.

    Linked folders (symlinks, junctions) are never entered, because the target may be a network
    share. A linked file is returned without being opened, so the caller can check where it points.
    Hidden and system files, Office lock files (~$) and anything in hidden folders are left out
    unless they are known documents.
    """
    found: list[Path] = []

    def wanted(entry: os.DirEntry, hidden_folder: bool) -> bool:
        if _is_document_name(entry.name):
            return True
        return not hidden_folder and not _is_hidden(entry)

    def walk(directory: Path, depth: int, hidden_folder: bool) -> Iterator[Path]:
        with os.scandir(directory) as entries:
            for entry in entries:
                if entry.is_symlink() or entry.is_junction():
                    if not entry.is_junction() and wanted(entry, hidden_folder):
                        yield Path(entry.path)
                elif entry.is_dir(follow_symlinks=False):
                    if recursive:
                        if depth >= max_depth:
                            raise ScanLimitExceeded("max_scan_depth", max_depth)
                        yield from walk(Path(entry.path), depth + 1, hidden_folder or _is_hidden(entry))
                elif entry.is_file(follow_symlinks=False) and wanted(entry, hidden_folder):
                    yield Path(entry.path)

    for path in walk(folder, 0, False):
        if len(found) >= max_files:
            raise ScanLimitExceeded("max_files", max_files)
        found.append(path)
    return sorted(found, key=lambda path: str(path).casefold())
