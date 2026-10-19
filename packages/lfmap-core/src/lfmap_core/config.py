"""User configuration: `%LOCALAPPDATA%\\lfmap\\config.toml`.

The user edits this file by hand; no operation writes it. `[paths]` defines the folders that
`${name}` variables in a manifest's `[permissions]` expand to, so a caller can never widen them.
"""

import json
import os
import tomllib
from pathlib import Path
from typing import Any

from lfmap_core.errors import ToolError
from lfmap_core.permissions import _is_remote

FOLDER_NAMES = ("documents", "exports", "knowledge")


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


def add_folder(name: str, folder: str, path: Path | None = None) -> str:
    if name not in FOLDER_NAMES:
        raise ToolError("invalid_input", f"Invalid folder name: {name}", {"name": name})
    if _is_remote(folder):
        raise ToolError("permission_denied", f"Remote folders are not allowed: {folder}", {"folder": folder})
    if not os.path.isabs(folder):
        raise ToolError("invalid_input", f"Folder must be an absolute path: {folder}", {"folder": folder})
    root = os.path.realpath(folder)
    if _is_remote(root):
        raise ToolError("permission_denied", f"Remote folders are not allowed: {root}", {"folder": root})
    if not os.path.isdir(root):
        raise ToolError("invalid_input", f"Folder does not exist: {root}", {"folder": root})

    path = path or config_path()
    config = load_config(path)
    values = config.get("paths", {}).get(name, [])
    if root in values:
        return root

    lines = []
    header_found = False
    name_found = False
    with path.open(encoding="utf-8") as f:
        for line in f:
            lines.append(line)
            if line.strip() == "[paths]":
                header_found = True
            if header_found and line.startswith(f"{name} = "):
                name_found = True
                try:
                    current_values = tomllib.loads(line).get(name, [])
                    if isinstance(current_values, str):
                        current_values = [current_values]
                    if root in current_values:
                        return root
                    lines[-1] = f"{name} = {json.dumps([*current_values, root], ensure_ascii=False)}\n"
                except tomllib.TOMLDecodeError:
                    raise ToolError("invalid_input", f"Invalid TOML for {name}: {line}", {"line": line})

    if not header_found:
        lines.append("")
        lines.append("[paths]")
    if not name_found:
        lines.append(f"{name} = {json.dumps([root], ensure_ascii=False)}\n")

    temp_path = path.with_name(path.name + ".tmp")
    os.makedirs(temp_path.parent, exist_ok=True)
    with temp_path.open("w", encoding="utf-8") as f:
        f.writelines(lines)
    os.replace(temp_path, path)

    return root
