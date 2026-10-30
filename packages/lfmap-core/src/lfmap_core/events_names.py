"""Topic names of the event adapter: `<plugin>.<operation>.<phase>` (ADR-014)."""

import re

from lfmap_core.errors import ToolError

PHASES = ("requested", "completed", "failed")
_PLUGIN = re.compile(r"[a-z][a-z0-9-]{0,63}", re.ASCII)
_OPERATION = re.compile(r"[a-z][a-z0-9_]{0,63}", re.ASCII)


def _ok(pattern: re.Pattern[str], value: object) -> bool:
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _shown(value: object) -> object:
    return value if isinstance(value, str) else repr(value)


def _check_plugin(plugin_id: str) -> None:
    if not _ok(_PLUGIN, plugin_id):
        raise ToolError("invalid_input", "Invalid plugin id", {"plugin": _shown(plugin_id)})


def operation_topic(plugin_id: str, operation: str, phase: str) -> str:
    """The topic of one phase of an operation call."""
    _check_plugin(plugin_id)
    if not _ok(_OPERATION, operation):
        raise ToolError("invalid_input", "Invalid operation name", {"operation": _shown(operation)})
    if not isinstance(phase, str) or phase not in PHASES:
        raise ToolError("invalid_input", "Invalid phase", {"phase": _shown(phase)})
    return f"{plugin_id}.{operation}.{phase}"


def parse_operation_topic(topic: str) -> tuple[str, str, str] | None:
    """(plugin, operation, phase) for an operation topic, otherwise None."""
    if not isinstance(topic, str):
        return None
    parts = topic.split(".")
    if len(parts) != 3:
        return None
    plugin_id, operation, phase = parts
    if _ok(_PLUGIN, plugin_id) and _ok(_OPERATION, operation) and phase in PHASES:
        return plugin_id, operation, phase
    return None


def plugin_may_publish(plugin_id: str, topic: str) -> bool:
    """A plugin publishes only its own topics and never the adapter's operation topics."""
    _check_plugin(plugin_id)
    if not isinstance(topic, str):
        return False
    parts = topic.split(".")
    return len(parts) >= 2 and parts[0] == plugin_id and parse_operation_topic(topic) is None
