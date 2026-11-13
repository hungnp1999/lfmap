"""Building tools and contexts for adapters and SDK callers."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from lfmap_core.approval import TIERS, Tier, audit, base_tier, raise_tier
from lfmap_core.config import load_config, plugin_variables
from lfmap_core.data_classes import load_class_map
from lfmap_core.data_guard import ClassGuard
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


def _attach_models(ctx: ToolContext, entry: PluginEntry, config: dict) -> None:
    """Give `ctx.models` to a plugin whose manifest has `[adapters] models = true`; the config is read lazily."""
    if not entry.manifest.adapters.models:
        return
    from lfmap_core.models_router import ModelRouter  # keeps the models modules out of plain imports

    ctx.model_router = ModelRouter(
        config,
        plugin_id=entry.id,
        channel=ctx.channel,
        operation=getattr(ctx.approver, "operation", ""),
        permissions=ctx.permissions,
        cloud_ai=entry.manifest.permissions.cloud_ai,
        approve=ctx.require_approval,
    )


def _attach_web(ctx: ToolContext, entry: PluginEntry, config: dict) -> None:
    """Give `ctx.web` to a plugin whose manifest has `[adapters] web = true`.

    The fetcher takes `[web]` and nothing else: no resolver, SSL context, clock, policy or port (spec section 5)."""
    if not entry.manifest.adapters.web:
        return
    from lfmap_core.web import load_web_config  # keeps the web modules out of plain imports
    from lfmap_core.web_http import WebFetcher, web_access

    plugin_id, channel, permissions = entry.id, ctx.channel, ctx.permissions
    operation = getattr(ctx.approver, "operation", "")

    def factory() -> WebFetcher:
        return WebFetcher(
            load_web_config(config), plugin_id=plugin_id, channel=channel, operation=operation, permissions=permissions
        )

    ctx.web_fetcher = web_access(factory)


def _class_guard(config: dict, approver: Any) -> ClassGuard | None:
    """ADR-025: a guard only when `[data.classes]` has an entry and someone approves (plain SDK use has none).
    An invalid table raises, so gated calls fail until the owner fixes it."""
    if approver is None:
        return None
    class_map = load_class_map(config)
    return ClassGuard(class_map, approver) if class_map else None


def build_tool(
    entry: PluginEntry,
    variables: Variables | None = None,
    *,
    channel: Channel = "sdk",
    approver: Any = None,
    explicit_read: bool = False,
    config: dict | None = None,
    events: Any = None,
) -> Tool:
    """Variables and settings default to the user's config.toml, never to anything the caller sends.

    Only the interactive CLI sets `explicit_read`; reads outside the roots are then audited.
    With `[data.classes]` and an approver, a `ClassGuard` sees every path the plugin resolves (ADR-025).
    `events` replaces the default `PluginEvents` (the event adapter passes its bus and the request);
    it is ignored unless the manifest has `[adapters] events = true`.
    """
    from lfmap_core.events_adapter import PluginEvents  # events_adapter imports this module

    config = load_config() if config is None else config
    if variables is None:
        variables = plugin_variables(config, entry.id)
    guard = _class_guard(config, approver)
    ctx = ToolContext(
        plugin_id=entry.id,
        permissions=PermissionManager.from_manifest(
            entry.manifest.permissions,
            variables,
            explicit_read=explicit_read,
            on_outside_read=_outside_read_audit(entry.id, channel),
            on_path=guard.on_path if guard else None,
        ),
        settings=_plugin_settings(config, entry.id),
        channel=channel,
        approver=approver,
        event_publisher=(events or PluginEvents(entry.id)) if entry.manifest.adapters.events else None,
        data_guard=guard,
        **_plugin_dirs(variables),
    )
    _attach_models(ctx, entry, config)
    _attach_web(ctx, entry, config)
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
    events: Any = None,
) -> BaseModel:
    tool = build_tool(entry, variables, channel=channel, approver=approver, explicit_read=explicit_read, events=events)
    return invoke(tool, name, payload)


def context_for(
    plugin_id: str, parent: ToolContext, config: dict | None = None, entry: PluginEntry | None = None
) -> ToolContext:
    """Context for an in-process call to another plugin: the caller's rights, the callee's own folders and settings.

    Pass the callee's `entry` so a callee with `[adapters] models = true` or `web = true` gets its own
    `ctx.models` or `ctx.web`."""
    config = load_config() if config is None else config
    ctx = ToolContext(
        plugin_id=plugin_id,
        permissions=parent.permissions,
        dry_run=parent.dry_run,
        settings=_plugin_settings(config, plugin_id),
        channel=parent.channel,
        approver=parent.approver,
        data_guard=parent.data_guard,
        **_plugin_dirs(plugin_variables(config, plugin_id)),
    )
    if entry is not None:
        _attach_models(ctx, entry, config)
        _attach_web(ctx, entry, config)
    return ctx
