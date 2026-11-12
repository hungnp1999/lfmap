"""Class guard: data classes applied to one operation call (ADR-025, docs/specs/data-classes.md section 5.3).

`PermissionManager` reports every path it resolved; `ctx.require_approval(..., paths=...)` reports destructive
actions. The guard raises the tier for `secret`, lowers a destructive T2 to T1 only when everything declared
and written is `scratch`, and keeps the call label (highest class read). It never widens a permission root.
"""

import os
from collections.abc import Callable, Iterable
from typing import Any

from lfmap_core.data_classes import Access, ClassMap, DataClass, TierName, adjust, highest
from lfmap_core.errors import ToolError
from lfmap_core.permissions import _is_remote

_SECRET_FLOOR: dict[str, TierName] = {"read": "T1", "write": "T2"}


class ClassGuard:
    """One per operation call; shared with in-process callees through `context_for`."""

    def __init__(self, class_map: ClassMap, approver: Callable[..., Any]) -> None:
        self.class_map = class_map
        self.approver = approver
        self.label: DataClass | None = None
        self.written: list[str] = []
        self._asked: set[tuple[str, str]] = set()

    def on_path(self, access: str, resolved: str) -> None:
        """`PermissionManager` hook, called with a path that already passed its checks."""
        path = _resolve(resolved)
        data_class = self.class_map.class_under(path)
        if access == "read":
            self._raise_label(data_class)
        else:
            self.written.append(path)
        if data_class != "secret":
            return
        kind: Access = "read" if access == "read" else "write"
        action: TierName = "T0" if kind == "read" else "T1"
        key = (kind, self._secret_key(path))
        if key in self._asked:
            return
        tier = _tier(action, kind, data_class)
        self.approver(tier, f"secret_{kind}", path, data_class=data_class, action_tier=action)
        self._asked.add(key)

    def destructive(self, reason: str, detail: str, paths: Iterable[str | os.PathLike[str]]) -> None:
        """A T2 action (overwrite, rename, delete) on `paths`; lowered to T1 only when all is `scratch`."""
        declared = [_resolve(path) for path in paths]
        data_class = highest(self.class_map.class_under(path) for path in declared + self.written)
        tier = _tier("T2", "write", data_class)
        self.approver(tier, reason, detail, data_class=data_class, action_tier="T2")

    def mark(self, path: str | os.PathLike[str]) -> None:
        """Raise the call label for content that came from `path` without a read in this call."""
        self._raise_label(self.class_map.class_under(_resolve(path)))

    def _raise_label(self, data_class: DataClass) -> None:
        self.label = data_class if self.label is None else highest((self.label, data_class))

    def _secret_key(self, path: str) -> str:
        data_class, entry = self.class_map.lookup(path)
        return entry if data_class == "secret" and entry is not None else os.path.normcase(path)


def _resolve(path: str | os.PathLike[str]) -> str:
    # String check before any file-system call, then resolve links; classification only, no root check.
    text = os.fspath(path)
    if _is_remote(text):
        raise ToolError("permission_denied", "Network and device paths are refused", {"path": text})
    resolved = os.path.realpath(text)
    if _is_remote(resolved):
        raise ToolError("permission_denied", "Path resolves to a network path", {"path": text})
    return resolved


def _tier(action: TierName, access: Access, data_class: DataClass) -> TierName:
    """`adjust`, failing safe: any error keeps the action tier, and the literal floor for `secret`."""
    try:
        return adjust(action, access, data_class)
    except Exception:  # noqa: BLE001 - an error in the adjustment must never drop a protection
        if data_class == "secret":
            floor = _SECRET_FLOOR[access]
            return max(action, floor, key=("T0", "T1", "T2", "T3").index)
        return action
