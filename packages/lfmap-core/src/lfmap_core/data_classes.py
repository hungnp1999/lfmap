"""Data classes for paths (ADR-025, docs/specs/data-classes.md sections 4 and 5.1).

Leaf module: pure lookups and tier arithmetic. The owner's `[data.classes]` table is the only source of a class.
"""

import os
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal, get_args

from pydantic import TypeAdapter, ValidationError

from lfmap_core.config import app_dir
from lfmap_core.errors import ToolError
from lfmap_core.permissions import _is_remote

DataClass = Literal["scratch", "normal", "private", "secret"]
EgressLevel = Literal["normal", "private", "secret"]
Access = Literal["read", "write"]
TierName = Literal["T0", "T1", "T2", "T3"]

CLASSES: tuple[DataClass, ...] = get_args(DataClass)
TIER_NAMES: tuple[TierName, ...] = get_args(TierName)
DEFAULT_CLASS: DataClass = "private"

_TABLE = TypeAdapter(dict[str, DataClass])


def _invalid(error: object) -> ToolError:
    return ToolError("invalid_input", "[data.classes] in config.toml is invalid", {"error": str(error)})


def highest(classes: Iterable[DataClass]) -> DataClass:
    """The highest class of `classes`; `scratch` for none."""
    return max(classes, key=CLASSES.index, default=CLASSES[0])


def egress_level(data_class: DataClass) -> EgressLevel:
    """`scratch` is an approval convenience only: for leaving the machine it counts as `normal`."""
    return "normal" if data_class == "scratch" else data_class


def adjust(action_tier: TierName, access: Access, data_class: DataClass) -> TierName:
    """Tier after the class is applied (section 5.1). Raises ValueError on an unknown value."""
    if action_tier not in TIER_NAMES or access not in ("read", "write") or data_class not in CLASSES:
        raise ValueError(f"unknown tier, access or class: {action_tier!r}, {access!r}, {data_class!r}")
    level = TIER_NAMES.index(action_tier)
    if data_class == "scratch" and access == "write" and action_tier == "T2":
        level = 1
    elif data_class == "secret":
        level = max(level, 1 if access == "read" else 2)
    return TIER_NAMES[level]


@dataclass(frozen=True)
class ClassEntry:
    path: str
    base: str
    data_class: DataClass


@dataclass(frozen=True)
class ClassMap:
    entries: tuple[ClassEntry, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.entries)

    def lookup(self, path: str | os.PathLike[str]) -> tuple[DataClass, str | None]:
        """Class of the most specific entry at or above `path`, and that entry; `private` and None when none."""
        resolved = _resolve(path)
        best: ClassEntry | None = None
        for entry in self.entries:
            if resolved.startswith(entry.base) and resolved[len(entry.base) : len(entry.base) + 1] in ("", os.sep):
                if best is None or len(entry.base) > len(best.base):
                    best = entry
        return (best.data_class, best.path) if best else (DEFAULT_CLASS, None)

    def class_of(self, path: str | os.PathLike[str]) -> DataClass:
        return self.lookup(path)[0]

    def class_under(self, path: str | os.PathLike[str]) -> DataClass:
        """Highest of `class_of(path)` and every entry strictly below `path`."""
        resolved = _resolve(path)
        top = resolved.rstrip(os.sep)
        found = [self.class_of(path)]
        for entry in self.entries:
            if entry.base.startswith(top) and entry.base[len(top) : len(top) + 1] == os.sep:
                found.append(entry.data_class)
        return highest(found)


def _resolve(path: str | os.PathLike[str]) -> str:
    text = os.fspath(path)
    if _is_remote(text):
        raise ToolError("permission_denied", "Network and device paths are refused", {"path": text})
    resolved = os.path.normcase(os.path.realpath(text))
    return resolved


def load_class_map(config: dict[str, Any]) -> ClassMap:
    """Build the map from a loaded config.toml; absent or empty table gives an empty (inactive) map."""
    section = config.get("data", {})
    raw = section.get("classes", {}) if isinstance(section, dict) else None
    if raw is None:
        raise _invalid("[data] must be a table")
    try:
        table = _TABLE.validate_python(raw, strict=True)
    except ValidationError as error:
        raise _invalid(error) from error
    for key in table:
        if _is_remote(key):
            raise ToolError("invalid_input", "[data.classes] in config.toml is invalid", {"path": key})
        if not os.path.isabs(key):
            raise _invalid(f"{key!r} is not an absolute path")
    entries: dict[str, ClassEntry] = {}
    app_base = os.path.normcase(os.path.realpath(app_dir())) if table else ""
    for key, data_class in table.items():
        resolved = os.path.realpath(key)
        if _is_remote(resolved):
            raise _invalid(f"{key!r} resolves to a network path")
        base = os.path.normcase(resolved).rstrip(os.sep)
        if base.startswith(app_base) and base[len(app_base) : len(app_base) + 1] in ("", os.sep):
            raise _invalid(f"{key!r} is inside the application folder")
        if base in entries:
            raise _invalid(f"{key!r} and {entries[base].path!r} resolve to the same path")
        entries[base] = ClassEntry(resolved, base, data_class)
    return ClassMap(tuple(entries.values()))
