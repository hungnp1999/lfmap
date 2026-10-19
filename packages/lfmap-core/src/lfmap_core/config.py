"""User configuration: `%LOCALAPPDATA%\\lfmap\\config.toml`.

The user edits this file by hand or with `lfmap config add-folder` in an interactive terminal;
no operation or MCP tool writes it. `[paths]` defines the folders that
`${name}` variables in a manifest's `[permissions]` expand to, so a caller can never widen them.
"""

import json
import os
import re
import tomllib
from pathlib import Path
from typing import Any

from lfmap_core.errors import ToolError
from lfmap_core.permissions import _is_remote

FOLDER_NAMES = ("documents", "exports", "knowledge")
_SECTION = re.compile(r"^\s*\[")
_PATHS_HEADER = re.compile(r"^\s*\[paths\]\s*(#.*)?$")


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
