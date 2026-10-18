"""MCP adapter: every operation of the selected plugins becomes one MCP tool (stdio).

Tools are registered with `MCPServer.add_tool` (mcp 2.3.0). The schema comes from the
function signature, so each tool gets a generated function whose `__signature__` lists the
input model's fields as keyword-only parameters.
"""

import contextlib
import inspect
import re
import sys
from collections.abc import Iterable
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError as MCPToolError
from mcp.types import ToolAnnotations
from pydantic_core import PydanticUndefined

from lfmap_core import __version__
from lfmap_core.errors import ToolError
from lfmap_core.registry import PluginEntry, Registry
from lfmap_core.runtime import run_operation
from lfmap_core.tool import OperationSpec

# Claude accepts tool names matching ^[a-zA-Z0-9_-]{1,64}$, so no dot (ADR-014).
_TOOL_NAME = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def tool_name(plugin_id: str, operation: str) -> str:
    name = f"{plugin_id}_{operation}".replace("-", "_")
    if not _TOOL_NAME.match(name):
        raise ToolError("invalid_input", "MCP tool name is not valid", {"name": name})
    return name


def _signature(spec: OperationSpec) -> inspect.Signature:
    params = []
    for field_name, field in spec.input_model.model_fields.items():
        default = inspect.Parameter.empty if field.default is PydanticUndefined else field.default
        params.append(
            inspect.Parameter(field_name, inspect.Parameter.KEYWORD_ONLY, default=default, annotation=field.annotation)
        )
    return inspect.Signature(params, return_annotation=spec.output_model)


def _make_tool(entry: PluginEntry, spec: OperationSpec, approved: bool):
    side_effects = entry.manifest.operation(spec.name).side_effects

    def call(**kwargs: Any) -> Any:
        # ADR-009: an agent cannot confirm on the user's behalf, so side effects need approval
        # given by the user when starting the server. Checked before the tool is even built.
        if side_effects != "none" and not approved:
            hint = f"start the server with --approve {entry.id}.{spec.name}"
            raise MCPToolError(f"permission_denied: {entry.id}.{spec.name} has side effects ({side_effects}); {hint}")
        # Third-party backends may print; stdout belongs to the MCP protocol stream.
        with contextlib.redirect_stdout(sys.stderr):
            try:
                return run_operation(entry, spec.name, kwargs)
            except ToolError as error:
                details = f" {error.details}" if error.details else ""
                raise MCPToolError(f"{error.code}: {error.message}{details}") from error

    call.__signature__ = _signature(spec)
    call.__name__ = tool_name(entry.id, spec.name)
    return call


def _description(spec: OperationSpec, side_effects: str, approved: bool) -> str:
    if side_effects == "none":
        return spec.description
    note = "Approved by the user for this server." if approved else "Requires approval when the server starts."
    return f"{spec.description} Side effects: {side_effects}. {note}".strip()


def _check_approvals(entries: list[PluginEntry], approve: set[str]) -> None:
    known = {f"{e.id}.{op.name}": op.side_effects for e in entries for op in e.manifest.operations}
    for item in sorted(approve):
        if item not in known:
            raise ToolError("invalid_input", "--approve names an unknown operation", {"operation": item})
        if known[item] == "external":
            # Effects that leave the machine cannot be undone; one approval must not cover a whole session.
            raise ToolError(
                "invalid_input", "Operations with external side effects cannot be pre-approved", {"operation": item}
            )


def build_server(registry: Registry, plugin_ids: list[str], approve: Iterable[str] = ()) -> MCPServer:
    entries = [registry.get(plugin_id) for plugin_id in plugin_ids] if plugin_ids else registry.all()
    approved_ops = set(approve)
    _check_approvals(entries, approved_ops)
    server = MCPServer(
        name="lfmap", version=__version__, instructions="LFMAP plugins: " + ", ".join(e.id for e in entries)
    )
    for entry in entries:
        if not entry.manifest.adapters.mcp:
            continue
        for spec in entry.tool_class.operations().values():
            side_effects = entry.manifest.operation(spec.name).side_effects
            approved = f"{entry.id}.{spec.name}" in approved_ops
            annotations = ToolAnnotations(
                read_only_hint=side_effects == "none",
                open_world_hint=side_effects == "external" or entry.manifest.permissions.network,
            )
            server.add_tool(
                _make_tool(entry, spec, approved),
                name=tool_name(entry.id, spec.name),
                description=_description(spec, side_effects, approved),
                annotations=annotations,
                structured_output=True,
            )
    return server
