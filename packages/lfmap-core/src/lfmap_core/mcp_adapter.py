"""MCP adapter: every operation of the selected plugins becomes one MCP tool (stdio).

Tools are registered with `MCPServer.add_tool` (mcp 2.3.0). The schema comes from the
function signature, so each tool gets a generated function whose `__signature__` lists the
input model's fields as keyword-only parameters.
"""

import contextlib
import inspect
import re
import sys
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError as MCPToolError
from pydantic_core import PydanticUndefined

from lfmap_core import __version__
from lfmap_core.errors import ToolError
from lfmap_core.registry import PluginEntry, Registry
from lfmap_core.runtime import run_operation
from lfmap_core.tool import OperationSpec

# Claude accepts tool names matching ^[a-zA-Z0-9_-]{1,64}$, so no dot (proposed ADR-014).
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


def _make_tool(entry: PluginEntry, spec: OperationSpec):
    def call(**kwargs: Any) -> Any:
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


def build_server(registry: Registry, plugin_ids: list[str]) -> MCPServer:
    entries = [registry.get(plugin_id) for plugin_id in plugin_ids] if plugin_ids else registry.all()
    server = MCPServer(
        name="lfmap", version=__version__, instructions="LFMAP plugins: " + ", ".join(e.id for e in entries)
    )
    for entry in entries:
        if not entry.manifest.adapters.mcp:
            continue
        for spec in entry.tool_class.operations().values():
            name = tool_name(entry.id, spec.name)
            server.add_tool(_make_tool(entry, spec), name=name, description=spec.description, structured_output=True)
    return server
