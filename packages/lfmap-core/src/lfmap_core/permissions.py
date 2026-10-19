"""Permission Manager: grants exactly what a plugin declares in [permissions]."""

import logging
import os
import re
from collections.abc import Callable
from pathlib import Path

from lfmap_core.errors import ToolError
from lfmap_core.manifest import Permissions

# Network and device paths: touching them can send the user's NTLM hash or reach other machines.
_REMOTE_PREFIXES = ("\\\\", "//")
_VARIABLE = re.compile(r"\$\{(\w+)\}")

log = logging.getLogger(__name__)


def _is_remote(value: str) -> bool:
    return value.startswith(_REMOTE_PREFIXES) or value.startswith("\\??\\")


def _expand(pattern: str, variables: dict[str, list[str]]) -> list[str]:
    """Expand `${name}` variables; a list variable gives one root per value. Unknown variable: no root."""
    results = [pattern]
    for name in _VARIABLE.findall(pattern):
        if name not in variables:
            log.warning("Permission %r uses undefined variable ${%s}; it grants nothing", pattern, name)
            return []
        results = [r.replace("${" + name + "}", value) for r in results for value in variables[name]]
    roots = []
    for result in results:
        if _is_remote(result):
            raise ToolError("permission_denied", "Network paths cannot be granted", {"pattern": pattern})
        if not os.path.isabs(result):
            raise ToolError("invalid_input", "Permission roots must be absolute paths", {"root": result})
        root = os.path.realpath(result)
        if _is_remote(root):
            raise ToolError("permission_denied", "Root resolves to a network path", {"pattern": pattern})
        roots.append(root)
    return roots


class PermissionManager:
    def __init__(
        self,
        read_roots: list[str],
        write_roots: list[str],
        network: bool = False,
        explicit_read: bool = False,
        on_outside_read: Callable[[str], None] | None = None,
    ) -> None:
        self.write_roots = list(write_roots)
        self.read_roots = list(read_roots) + self.write_roots
        self.network = network
        self.explicit_read = explicit_read
        self.on_outside_read = on_outside_read

    @classmethod
    def from_manifest(
        cls,
        perms: Permissions,
        variables: dict[str, str | list[str]],
        *,
        explicit_read: bool = False,
        on_outside_read: Callable[[str], None] | None = None,
    ) -> "PermissionManager":
        values = {name: [v] if isinstance(v, str) else list(v) for name, v in variables.items()}
        return cls(
            [root for p in perms.fs_read for root in _expand(p, values)],
            [root for p in perms.fs_write for root in _expand(p, values)],
            perms.network,
            explicit_read=explicit_read,
            on_outside_read=on_outside_read,
        )

    def require_read(self, value: str | os.PathLike[str]) -> Path:
        try:
            return self._require(value, self.read_roots, "read")
        except ToolError:
            if not self.explicit_read:
                raise
            return self._typed_read(value)

    def require_write(self, value: str | os.PathLike[str]) -> Path:
        return self._require(value, self.write_roots, "write")

    def require_network(self) -> None:
        if not self.network:
            raise ToolError("permission_denied", "This plugin did not declare network access")

    @staticmethod
    def _require(value: str | os.PathLike[str], roots: list[str], access: str) -> Path:
        # String checks only until the path is known to be inside a root; then resolve links.
        # Both guards keep the inline startswith form that static analysis recognises.
        text = os.fspath(value)
        if _is_remote(text):
            raise ToolError("permission_denied", "Network and device paths are refused", {"path": text})
        normalized = os.path.normpath(os.path.abspath(os.path.expanduser(text)))
        candidate = os.path.normcase(normalized)
        for root in roots:
            base = os.path.normcase(root)
            if candidate.startswith(base) and candidate[len(base) : len(base) + 1] in ("", os.sep):
                break
        else:
            raise ToolError(
                "permission_denied", f"Path is outside the folders this plugin may {access}", {"path": text}
            )
        # Roots are already realpath-resolved, so the resolved path is compared as is.
        resolved = os.path.realpath(normalized)
        for root in roots:
            if resolved.startswith(root) and resolved[len(root) : len(root) + 1] in ("", os.sep):
                return Path(resolved)
        raise ToolError(
            "permission_denied", f"Path resolves outside the folders this plugin may {access}", {"path": text}
        )

    def _typed_read(self, value: str | os.PathLike[str]) -> Path:
        text = os.fspath(value)
        if _is_remote(text):
            raise ToolError("permission_denied", "Network and device paths are refused", {"path": text})
        resolved = os.path.realpath(os.path.abspath(os.path.expanduser(text)))
        if _is_remote(resolved):
            raise ToolError("permission_denied", "Network and device paths are refused", {"path": resolved})
        if resolved not in self.read_roots:
            if self.on_outside_read:
                self.on_outside_read(resolved)
        return Path(resolved)
