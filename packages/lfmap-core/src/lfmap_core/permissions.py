"""Permission Manager: grants exactly what a plugin declares in [permissions]."""

import os
from pathlib import Path

from lfmap_core.errors import ToolError
from lfmap_core.manifest import Permissions

# Network and device paths: touching them can send the user's NTLM hash or reach other machines.
_REMOTE_PREFIXES = ("\\\\", "//")


def _is_remote(value: str) -> bool:
    return value.startswith(_REMOTE_PREFIXES) or value.startswith("\\??\\")


def _expand(pattern: str, variables: dict[str, str]) -> str:
    result = pattern
    for name, value in variables.items():
        result = result.replace("${" + name + "}", value)
    if "${" in result:
        raise ToolError("invalid_input", "Permission uses an undefined variable", {"pattern": pattern})
    if _is_remote(result):
        raise ToolError("permission_denied", "Network paths cannot be granted", {"pattern": pattern})
    return os.path.realpath(os.path.abspath(result))


class PermissionManager:
    def __init__(self, read_roots: list[str], write_roots: list[str], network: bool = False) -> None:
        self.write_roots = list(write_roots)
        self.read_roots = list(read_roots) + self.write_roots
        self.network = network

    @classmethod
    def from_manifest(cls, perms: Permissions, variables: dict[str, str]) -> "PermissionManager":
        return cls(
            [_expand(p, variables) for p in perms.fs_read],
            [_expand(p, variables) for p in perms.fs_write],
            perms.network,
        )

    def require_read(self, value: str | os.PathLike[str]) -> Path:
        return self._require(value, self.read_roots, "read")

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
