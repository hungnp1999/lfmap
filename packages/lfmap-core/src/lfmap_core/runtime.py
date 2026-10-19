from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from lfmap_core.config import load_config, plugin_variables
from lfmap_core.errors import ToolError
from lfmap_core.permissions import PermissionManager
from lfmap_core.registry import PluginEntry
from lfmap_core.tool import Tool, ToolContext, invoke


def default_context(plugin_id: str, permissions: PermissionManager | None = None) -> ToolContext:
    return ToolContext(plugin_id=plugin_id, permissions=permissions or PermissionManager([], []))


def _get_settings(config: dict, plugin_id: str) -> dict[str, Any]:
    settings = config.get("plugins", {}).get(plugin_id, {}).get("settings", {})
    if not isinstance(settings, dict):
        raise ToolError("invalid_input", f"[plugins.{plugin_id}.settings] must be a table", {"plugin": plugin_id})
    return settings


def build_tool(
    entry: PluginEntry,
    variables: dict[str, str | list[str]] | None = None,
    *,
    channel: Literal["sdk", "cli", "mcp", "rest", "job"] = "sdk",
    approver: Any = None,
    config: dict | None = None,
) -> Tool:
    config = load_config() if config is None else config
    if variables is None:
        variables = plugin_variables(config, entry.id)
    perms = PermissionManager.from_manifest(entry.manifest.permissions, variables)
    data_dir = Path(variables["data_dir"][0]) if "data_dir" in variables else None
    temp_dir = Path(variables["temp_dir"][0]) if "temp_dir" in variables else None
    settings = _get_settings(config, entry.id)
    return entry.tool_class(
        ToolContext(
            plugin_id=entry.id,
            permissions=perms,
            data_dir=data_dir,
            temp_dir=temp_dir,
            settings=settings,
            channel=channel,
            approver=approver,
            dry_run=False,
        )
    )


def run_operation(
    entry: PluginEntry,
    name: str,
    payload: dict[str, Any],
    variables: dict[str, str | list[str]] | None = None,
    *,
    channel: Literal["sdk", "cli", "mcp", "rest", "job"] = "sdk",
    approver: Any = None,
) -> BaseModel:
    return invoke(build_tool(entry, variables, channel=channel, approver=approver), name, payload)


def context_for(plugin_id: str, parent: ToolContext, config: dict | None = None) -> ToolContext:
    config = load_config() if config is None else config
    variables = plugin_variables(config, plugin_id)
    data_dir = Path(variables["data_dir"][0]) if "data_dir" in variables else None
    temp_dir = Path(variables["temp_dir"][0]) if "temp_dir" in variables else None
    settings = _get_settings(config, plugin_id)
    return ToolContext(
        plugin_id=plugin_id,
        permissions=parent.permissions,
        data_dir=data_dir,
        temp_dir=temp_dir,
        settings=settings,
        channel=parent.channel,
        approver=parent.approver,
        dry_run=parent.dry_run,
    )
