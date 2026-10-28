"""Version parsing and comparison for plugin compatibility checks."""

import re

from lfmap_core.errors import ToolError

_VERSION_RE = re.compile(r"\d+\.\d+\.\d+", re.ASCII)


def parse_version(text: str) -> tuple[int, int, int]:
    """Parse a version string into a tuple of integers.

    The version string must be exactly three groups of ASCII digits separated by single dots.
    """
    if not isinstance(text, str):
        raise ToolError("invalid_input", f"Version must be a string, got {text!r}", {"version": repr(text)})
    if not _VERSION_RE.fullmatch(text):
        raise ToolError("invalid_input", f"Invalid version {text!r}, expected X.Y.Z", {"version": text})
    major, minor, patch = map(int, text.split("."))
    return (major, minor, patch)


def require_core_version(plugin_id: str, required: str, current: str) -> None:
    """Check if the current core version meets the required version for a plugin.

    Raises a ToolError if the current version is older than the required version.
    """
    if parse_version(current) < parse_version(required):
        raise ToolError(
            "invalid_input",
            f"Plugin {plugin_id!r} needs lfmap-core {required} or newer, found {current}",
            {"plugin": plugin_id, "min_core_version": required, "core_version": current},
        )
