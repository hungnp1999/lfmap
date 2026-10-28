"""Version parsing and comparison for plugin compatibility checks."""

import re

from lfmap_core.errors import ToolError


def parse_version(text: str) -> tuple[int, int, int]:
    """Parse a version string into a tuple of three integers.

    The version string must match the pattern X.Y.Z where X, Y, and Z are non-negative integers.
    """
    if not isinstance(text, str):
        raise ToolError("invalid_input", f"Version must be a string, got {repr(text)}", {"version": repr(text)})

    version_pattern = re.compile(r"^\d+\.\d+\.\d+$", re.ASCII)
    match = version_pattern.fullmatch(text)
    if not match:
        raise ToolError("invalid_input", f"Invalid version format: {text}", {"version": text})

    major, minor, patch = map(int, text.split("."))
    return (major, minor, patch)


def require_core_version(plugin_id: str, required: str, current: str) -> None:
    """Check if the current core version meets the required version for a plugin.

    Raises a ToolError if the current version is older than the required version.
    """
    try:
        required_version = parse_version(required)
        current_version = parse_version(current)
    except ToolError as e:
        raise e

    if current_version < required_version:
        raise ToolError(
            "invalid_input",
            f"Plugin {plugin_id!r} needs lfmap-core {required} or newer, found {current}",
            {"plugin": plugin_id, "min_core_version": required, "core_version": current},
        )
