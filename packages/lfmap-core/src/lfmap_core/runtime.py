"""Building tools and contexts for adapters and SDK callers."""

from typing import Any

from pydantic import BaseModel

from lfmap_core.config import load_config, plugin_variables
from lfmap_core.permissions import PermissionManager
from lfmap_core.registry import PluginEntry
from lfmap_core.tool import Tool, ToolContext, invoke


def default_context(plugin_id: str, permissions: PermissionManager | None = None) -> ToolContext:
    return ToolContext(plugin_id=plugin_id, permissions=permissions or PermissionManager([], []))


def build_tool(entry: PluginEntry, variables: dict[str, str | list[str]] | None = None) -> Tool:
    """Variables default to the user's config.toml, never to anything the caller sends."""
    if variables is None:
        variables = plugin_variables(load_config(), entry.id)
    perms = PermissionManager.from_manifest(entry.manifest.permissions, variables)
    return entry.tool_class(default_context(entry.id, perms))


def run_operation(
    entry: PluginEntry, name: str, payload: dict[str, Any], variables: dict[str, str | list[str]] | None = None
) -> BaseModel:
    return invoke(build_tool(entry, variables), name, payload)
