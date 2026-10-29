"""Safe and free Windows file names for plugins that create or rename files (pure functions, no I/O)."""

import unicodedata
from collections.abc import Iterable

from lfmap_core.errors import ToolError

MAX_EXTENSION = 11
FORBIDDEN = set('<>:"/\\|?*')
RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}


def split_extension(name: str) -> tuple[str, str]:
    """Split a file name into stem and extension (dot included)."""
    if not isinstance(name, str):
        raise ToolError("invalid_input", f"File name must be a string, got {name!r}", {"name": repr(name)})
    index = name.rfind(".")
    if index > 0 and len(name) - index <= MAX_EXTENSION:
        return name[:index], name[index:]
    return name, ""


def unique_name(name: str, existing: Iterable[str]) -> str:
    """Generate a unique file name by appending a number in parentheses if necessary.

    The function ensures that the name is unique by checking against the existing names.
    """
    if not isinstance(name, str):
        raise ToolError("invalid_input", "Name must be a string", {"name": repr(name)})
    name = unicodedata.normalize("NFC", name)
    taken = {unicodedata.normalize("NFC", item).casefold() for item in existing}
    if name.casefold() not in taken:
        return name
    stem, extension = split_extension(name)
    number = 2
    while True:
        candidate = f"{stem} ({number}){extension}"
        if candidate.casefold() not in taken:
            return candidate
        number += 1


def _is_bad_char(char: str) -> bool:
    """Check if a character is forbidden or a control character."""
    return char in FORBIDDEN or ord(char) < 32


def clean_filename(name: str, replacement: str = "_") -> str:
    """Turn any text into a name Windows accepts.

    Raises:
        ToolError: If the input is invalid.
    """
    if not isinstance(name, str):
        raise ToolError("invalid_input", "Name must be a string", {"name": repr(name)})
    if not isinstance(replacement, str):
        raise ToolError("invalid_input", "Replacement must be a string", {"replacement": repr(replacement)})
    if replacement and (len(replacement) != 1 or replacement.isspace() or _is_bad_char(replacement)):
        raise ToolError(
            "invalid_input",
            "Replacement must be a single character, not a space or forbidden character",
            {"replacement": replacement},
        )

    original = name
    text = unicodedata.normalize("NFC", name)
    text = "".join(replacement if _is_bad_char(char) else char for char in text)
    text = text.lstrip(" ").rstrip(". ")
    if not text:
        raise ToolError("invalid_input", "Resulting filename is empty", {"name": original})
    base = text.split(".", 1)[0].rstrip(" ").upper()
    if base in RESERVED:
        text = "_" + text
    return text


def shorten_filename(name: str, max_length: int = 255) -> str:
    """Shorten a file name to fit within a maximum length while keeping its extension."""
    if not isinstance(name, str):
        raise ToolError("invalid_input", f"File name must be a string, got {name!r}", {"name": repr(name)})
    if not isinstance(max_length, int) or isinstance(max_length, bool) or max_length < 1:
        raise ToolError(
            "invalid_input",
            f"max_length must be a positive integer, got {max_length!r}",
            {"max_length": repr(max_length)},
        )
    if len(name) <= max_length:
        return name

    stem, extension = split_extension(name)
    if extension and len(extension) < max_length:
        result = stem[: max_length - len(extension)] + extension
    else:
        result = name[:max_length]

    result = result.rstrip(". ")
    if not result:
        raise ToolError("invalid_input", f"Shortened file name is empty: {name}", {"name": name})

    return result


def safe_filename(name: str, replacement: str = "_", max_length: int = 255) -> str:
    """Return one safe Windows file name for ``name``: cleaned, then shortened to ``max_length``."""
    return shorten_filename(clean_filename(name, replacement), max_length)
