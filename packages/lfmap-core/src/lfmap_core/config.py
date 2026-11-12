"""User configuration: `%LOCALAPPDATA%\\lfmap\\config.toml`.

The user edits this file by hand or with `lfmap config add-folder` in an interactive terminal;
no operation or MCP tool writes it. `[paths]` defines the folders that
`${name}` variables in a manifest's `[permissions]` expand to, so a caller can never widen them.
"""

import json
import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lfmap_core.errors import ToolError
from lfmap_core.permissions import _is_remote

FOLDER_NAMES = ("documents", "exports", "knowledge", "scripts")
_SECTION = re.compile(r"^\s*\[")
_PATHS_HEADER = re.compile(r"^\s*\[paths\]\s*(#.*)?$")
_CLASSES_HEADER = re.compile(r"^\s*\[data\.classes\]\s*(#.*)?$")
_CLASS_LINE = re.compile(
    r"""^(?P<head>\s*(?:'[^']*'|"(?:[^"\\]|\\.)*")\s*=\s*)(?P<value>"[^"]*"|'[^']*')(?P<tail>.*)$""", re.S
)
_UNQUOTABLE = re.compile(r"[\x00-\x1f\x7f']")

PRINCIPAL = "owner"
"""Who acts. Always `owner` today; later users only add values. Records without a principal mean `owner`."""


def app_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "lfmap"


def config_path() -> Path:
    override = os.environ.get("LFMAP_CONFIG")
    return Path(override) if override else app_dir() / "config.toml"


def load_config(path: Path | None = None) -> dict[str, Any]:
    path = path or config_path()
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise ToolError("invalid_input", f"{path} is not valid TOML", {"error": str(error)}) from error


def plugin_variables(config: dict[str, Any], plugin_id: str) -> dict[str, list[str]]:
    """Variables for one plugin: the user's `[paths]` plus the built-in `data_dir` and `temp_dir`."""
    variables: dict[str, list[str]] = {}
    for name, value in config.get("paths", {}).items():
        values = [value] if isinstance(value, str) else value
        if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
            raise ToolError("invalid_input", "[paths] values must be a path or a list of paths", {"name": name})
        variables[name] = values
    data_dir = app_dir() / plugin_id
    temp_dir = data_dir / "tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    variables["data_dir"] = [str(data_dir)]
    variables["temp_dir"] = [str(temp_dir)]
    return variables


def _folder_root(folder: str) -> str:
    # String checks first: never touch a network or device path (NTLM leak).
    if _is_remote(folder):
        raise ToolError("permission_denied", "Network and device paths cannot be added", {"path": folder})
    if not os.path.isabs(folder):
        raise ToolError("invalid_input", "Use an absolute folder path", {"path": folder})
    root = os.path.realpath(folder)
    if _is_remote(root):
        raise ToolError("permission_denied", "Folder resolves to a network path", {"path": folder})
    if not os.path.isdir(root):
        raise ToolError("invalid_input", "Folder does not exist", {"path": folder})
    return root


def _paths_line(lines: list[str], name: str) -> tuple[int, int | None]:
    """Index of the `[paths]` header (-1 if absent) and of the `name = ...` line inside it."""
    header = next((i for i, line in enumerate(lines) if _PATHS_HEADER.match(line)), -1)
    if header < 0:
        return -1, None
    key = re.compile(rf"^\s*{name}\s*=")
    for i in range(header + 1, len(lines)):
        if _SECTION.match(lines[i]):
            break
        if key.match(lines[i]):
            return header, i
    return header, None


def add_folder(name: str, folder: str, path: Path | None = None) -> str:
    """Add `folder` to `[paths].name`, editing only that line so the user's comments stay. Returns the root."""
    if name not in FOLDER_NAMES:
        raise ToolError("invalid_input", f"Folder name must be one of {', '.join(FOLDER_NAMES)}", {"name": name})
    root = _folder_root(folder)
    path = path or config_path()
    current = load_config(path).get("paths", {}).get(name, [])
    values = [current] if isinstance(current, str) else list(current)
    if root in values:
        return root
    line = f"{name} = {json.dumps([*values, root], ensure_ascii=False)}"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    header, index = _paths_line(lines, name)
    if header < 0:
        lines += ["", "[paths]", line] if lines else ["[paths]", line]
    elif index is None:
        lines.insert(header + 1, line)
    else:
        try:
            tomllib.loads(lines[index])
        except tomllib.TOMLDecodeError as error:
            raise ToolError("invalid_input", f"[paths].{name} spans several lines; edit {path} by hand") from error
        lines[index] = line
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return root


def data_class_key(folder: str) -> str:
    """The key for `[data.classes]`: the resolved absolute path. String checks come before any `realpath`."""
    if _is_remote(folder):
        raise ToolError("permission_denied", "Network and device paths cannot be classified", {"path": folder})
    if not os.path.isabs(folder):
        raise ToolError("invalid_input", "Use an absolute path", {"path": folder})
    root = os.path.realpath(folder)
    if _is_remote(root):
        raise ToolError("permission_denied", "Path resolves to a network path", {"path": folder})
    if _UNQUOTABLE.search(root):
        raise ToolError(
            "invalid_input",
            "A path with a single quote or a control character cannot be written here; edit config.toml by hand",
        )
    return root


@dataclass(frozen=True)
class ClassEdit:
    old_text: str
    new_text: str
    previous: str | None
    """Class of the entry for this exact key before the edit, or None when it had none."""


def parse_config_text(text: str) -> dict[str, Any]:
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise ToolError("invalid_input", "config.toml would not be valid TOML", {"error": str(error)}) from error


def _read_text(path: Path) -> str:
    return path.read_bytes().decode("utf-8") if path.exists() else ""


def _class_entry(line: str) -> tuple[str, str] | None:
    try:
        parsed = tomllib.loads(line)
    except tomllib.TOMLDecodeError:
        return None
    if len(parsed) == 1:
        [(key, value)] = parsed.items()
        if isinstance(value, str):
            return key, value
    return None


def _same_key(found: str, key: str) -> bool:
    if _is_remote(found) or not os.path.isabs(found):
        return False
    return os.path.normcase(os.path.realpath(found)).rstrip(os.sep) == os.path.normcase(key).rstrip(os.sep)


def edit_data_class(key: str, data_class: str | None, path: Path | None = None) -> ClassEdit:
    """Text of config.toml with the one `[data.classes]` line for `key` set, or removed when `data_class` is None.

    Nothing is written. Comments, other tables and line endings stay byte for byte; the table is created if absent.
    """
    old = _read_text(path or config_path())
    lines = old.splitlines(keepends=True)
    newline = "\r\n" if "\r\n" in old else "\n"
    header = next((i for i, line in enumerate(lines) if _CLASSES_HEADER.match(line)), -1)
    end = len(lines)
    index, previous = None, None
    if header >= 0:
        for i in range(header + 1, len(lines)):
            if _SECTION.match(lines[i]):
                end = i
                break
            found = _class_entry(lines[i])
            if found and index is None and _same_key(found[0], key):
                index, previous = i, found[1]
    new_line = f"'{key}' = \"{data_class}\""
    if index is not None and data_class is None:
        del lines[index]
    elif index is not None:
        match = _CLASS_LINE.match(lines[index].rstrip("\r\n"))
        if not match:
            raise ToolError("invalid_input", "That [data.classes] line has an unusual form; edit config.toml by hand")
        ending = lines[index][len(lines[index].rstrip("\r\n")) :]
        lines[index] = f'{match["head"]}"{data_class}"{match["tail"]}{ending}'
    elif data_class is not None:
        if header < 0:
            tail = [newline, f"[data.classes]{newline}"] if lines else [f"[data.classes]{newline}"]
            lines = _with_ending(lines, newline) + tail + [new_line + newline]
        else:
            while end > header + 1 and not lines[end - 1].strip():
                end -= 1
            lines = _with_ending(lines[:end], newline) + [new_line + newline] + lines[end:]
    return ClassEdit(old, "".join(lines), previous)


def _with_ending(lines: list[str], newline: str) -> list[str]:
    return [*lines[:-1], lines[-1] + newline] if lines and not lines[-1].endswith(("\n", "\r")) else lines


def commit_edit(edit: ClassEdit, path: Path | None = None) -> None:
    """Write an edit made by `edit_data_class`: only if the file is unchanged since, and only if the new text
    still loads as a valid class map. A temporary file and `os.replace` keep the write atomic."""
    from lfmap_core.data_classes import load_class_map  # data_classes imports this module

    path = path or config_path()
    if _read_text(path) != edit.old_text:
        raise ToolError("invalid_input", f"{path.name} changed while waiting; run the command again")
    load_class_map(parse_config_text(edit.new_text))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(edit.new_text.encode("utf-8"))
    os.replace(tmp, path)
