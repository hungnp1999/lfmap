"""User configuration: `%LOCALAPPDATA%\\lfmap\\config.toml`.

The user edits this file by hand; no operation writes it. `[paths]` defines the folders that
`${name}` variables in a manifest's `[permissions]` expand to, so a caller can never widen them.
"""

import os
import tomllib
from pathlib import Path
from typing import Any

from lfmap_core.errors import ToolError


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
