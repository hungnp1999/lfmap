"""Building tools and contexts for adapters and SDK callers."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from lfmap_core.approval import TIERS, Tier, audit, base_tier, raise_tier
from lfmap_core.config import load_config, plugin_variables
from lfmap_core.errors import ToolError
from lfmap_core.permissions import PermissionManager
from lfmap_core.registry import PluginEntry
from lfmap_core.tool import Channel, Tool, ToolContext, invoke

Variables = dict[str, str | list[str]]


def default_context(plugin_id: str, permissions: PermissionManager | None = None) -> ToolContext:
    return ToolContext(plugin_id=plugin_id, permissions=permissions or PermissionManager([], []))


def _plugin_settings(config: dict, plugin_id: str) -> dict[str, Any]:
    section = config.get("plugins", {})
    section = section.get(plugin_id, {}) if isinstance(section, dict) else None
    settings = section.get("settings", {}) if isinstance(section, dict) else None
    if not isinstance(settings, dict):
        raise ToolError("invalid_input", f"[plugins.{plugin_id}.settings] must be a table", {"plugin": plugin_id})
    return settings


def call_tier(entry: PluginEntry, operation: str, payload: dict[str, Any], config: dict | None = None) -> Tier:
    """The tier the adapters gate one call on: the declared tier, lowered only as far as the manifest's
    `min_tier` allows and only when the plugin reads a lower tier from the user's config (ADR-020)."""
    declared = entry.manifest.operation(operation)
    if declared is None:
        raise ToolError("not_found", f"Unknown operation {entry.id}.{operation}", {"operation": operation})
    tier = base_tier(declared.side_effects)
    spec = entry.tool_class.operations().get(operation)
    if declared.min_tier is None or spec is None:
        return tier
    try:
        inp = spec.input_model.model_validate(payload)
        settings = _plugin_settings(load_config() if config is None else config, entry.id)
        wanted = entry.tool_class.call_tier(operation, inp, settings)
    except Exception:  # noqa: BLE001 - any failure keeps the declared tier
        return tier
    if wanted not in TIERS:
        return tier
    return min(raise_tier(wanted, declared.min_tier), tier, key=TIERS.index)


def _plugin_dirs(variables: Variables) -> dict[str, Path | None]:
    return {key: Path(variables[key][0]) if variables.get(key) else None for key in ("data_dir", "temp_dir")}


def _outside_read_audit(plugin_id: str, channel: Channel) -> Callable[[str], None]:
    def audit_func(path: str) -> None:
        audit(
            {
                "channel": channel,
                "plugin": plugin_id,
                "tier": "T0",
                "decision": "allow",
                "reason": "read_outside_roots",
                "target": path,
            }
        )

    return audit_func


def build_tool(
    entry: PluginEntry,
    variables: Variables | None = None,
    *,
    channel: Channel = "sdk",
    approver: Any = None,
    explicit_read: bool = False,
    config: dict | None = None,
) -> Tool:
    """Variables and settings default to the user's config.toml, never to anything the caller sends.

    Only the interactive CLI sets `explicit_read`; reads outside the roots are then audited.
    """
    config = load_config() if config is None else config
    if variables is None:
        variables = plugin_variables(config, entry.id)
    ctx = ToolContext(
        plugin_id=entry.id,
        permissions=PermissionManager.from_manifest(
            entry.manifest.permissions,
            variables,
            explicit_read=explicit_read,
            on_outside_read=_outside_read_audit(entry.id, channel),
        ),
        settings=_plugin_settings(config, entry.id),
        channel=channel,
        approver=approver,
        **_plugin_dirs(variables),
    )
    return entry.tool_class(ctx)


def run_operation(
    entry: PluginEntry,
    name: str,
    payload: dict[str, Any],
    variables: Variables | None = None,
    *,
    channel: Channel = "sdk",
    approver: Any = None,
    explicit_read: bool = False,
) -> BaseModel:
    return invoke(
        build_tool(entry, variables, channel=channel, approver=approver, explicit_read=explicit_read), name, payload
    )


def context_for(plugin_id: str, parent: ToolContext, config: dict | None = None) -> ToolContext:
    """Context for an in-process call to another plugin: the caller's rights, the callee's own folders and settings."""
    config = load_config() if config is None else config
    return ToolContext(
        plugin_id=plugin_id,
        permissions=parent.permissions,
        dry_run=parent.dry_run,
        settings=_plugin_settings(config, plugin_id),
        channel=parent.channel,
        approver=parent.approver,
        **_plugin_dirs(plugin_variables(config, plugin_id)),
    )
