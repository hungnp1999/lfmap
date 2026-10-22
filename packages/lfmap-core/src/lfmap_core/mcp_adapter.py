"""MCP adapter: every operation of the selected plugins becomes one MCP tool (stdio).

Tools are registered with `MCPServer.add_tool` (mcp 2.3.0). The schema comes from the
function signature, so each tool gets a generated function whose `__signature__` lists the
input model's fields as keyword-only parameters.
"""

import contextlib
import inspect
import re
import sys
import time
from collections.abc import Callable, Iterable
from typing import Any

import anyio.from_thread
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError as MCPToolError
from mcp.shared.exceptions import NoBackChannelError
from mcp.types import ClientCapabilities, ElicitationCapability, ToolAnnotations
from pydantic import BaseModel, Field
from pydantic_core import PydanticUndefined

from lfmap_core import __version__
from lfmap_core.approval import Asker, Gate, Policy, base_tier
from lfmap_core.config import load_config
from lfmap_core.errors import ToolError
from lfmap_core.registry import PluginEntry, Registry
from lfmap_core.runtime import call_tier, run_operation
from lfmap_core.tool import OperationSpec

# `serve mcp --approve` covers one working session, not an open-ended one (ADR-017).
APPROVE_TTL_SECONDS = 8 * 3600
_CONTEXT_PARAM = "mcp_context"

# Claude accepts tool names matching ^[a-zA-Z0-9_-]{1,64}$, so no dot (ADR-014).
_TOOL_NAME = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def tool_name(plugin_id: str, operation: str) -> str:
    name = f"{plugin_id}_{operation}".replace("-", "_")
    if not _TOOL_NAME.match(name):
        raise ToolError("invalid_input", "MCP tool name is not valid", {"name": name})
    return name


def _signature(spec: OperationSpec) -> inspect.Signature:
    params = [inspect.Parameter(_CONTEXT_PARAM, inspect.Parameter.KEYWORD_ONLY, annotation=Context)]
    for field_name, field in spec.input_model.model_fields.items():
        default = inspect.Parameter.empty if field.default is PydanticUndefined else field.default
        params.append(
            inspect.Parameter(field_name, inspect.Parameter.KEYWORD_ONLY, default=default, annotation=field.annotation)
        )
    return inspect.Signature(params, return_annotation=spec.output_model)


class _Confirmation(BaseModel):
    approve: bool = Field(description="Approve this action?")


def _asker(context: Context) -> Asker | None:
    """Ask through MCP elicitation when the client supports it. Tools run in a worker thread."""
    try:
        session = context.request_context.session
        supported = session.check_client_capability(ClientCapabilities(elicitation=ElicitationCapability()))
    except (AttributeError, LookupError, ValueError):
        return None
    if not supported:
        return None

    def ask(question: str) -> bool:
        try:
            result = anyio.from_thread.run(context.elicit, question, _Confirmation)
        except NoBackChannelError:
            return False  # this connection cannot carry a server-initiated request: nobody was asked
        return result.action == "accept" and result.data.approve

    return ask


def _make_tool(entry: PluginEntry, spec: OperationSpec, preapproved: Callable[[], frozenset[str]]):
    def call(**kwargs: Any) -> Any:
        context = kwargs.pop(_CONTEXT_PARAM, None)
        # Third-party backends may print; stdout belongs to the MCP protocol stream.
        with contextlib.redirect_stdout(sys.stderr):
            try:
                gate = Gate(
                    entry.id,
                    spec.name,
                    "mcp",
                    Policy.from_config(load_config()),
                    preapproved(),
                    _asker(context) if context is not None else None,
                )
                # ADR-017: the declared side effects set the starting tier; the plugin may escalate at run time.
                gate(call_tier(entry, spec.name, kwargs), "side_effects")
                return run_operation(entry, spec.name, kwargs, channel="mcp", approver=gate)
            except ToolError as error:
                details = f" {error.details}" if error.details else ""
                raise MCPToolError(f"{error.code}: {error.message}{details}") from error

    call.__signature__ = _signature(spec)
    call.__annotations__ = {_CONTEXT_PARAM: Context}  # how MCPServer finds the parameter to inject
    call.__name__ = tool_name(entry.id, spec.name)
    return call


def _description(spec: OperationSpec, side_effects: str, approved: bool, min_tier: str | None = None) -> str:
    tier = base_tier(side_effects)
    if tier == "T0":
        return spec.description
    if min_tier is not None:
        note = f"The user's config sets each call's tier ({min_tier} to {tier}); {tier} needs a time-limited grant."
        return f"{spec.description} Side effects: {side_effects}. {note}".strip()
    if tier == "T3":
        note = "Needs a time-limited grant from `lfmap approvals grant` in the user's terminal."
    elif approved:
        note = "Approved by the user for this server; recorded in the audit log."
    else:
        note = "Recorded in the audit log; overwriting or deleting needs the user's approval."
    return f"{spec.description} Side effects: {side_effects} (tier {tier}). {note}".strip()


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
    approved_ops = frozenset(approve)
    _check_approvals(entries, set(approved_ops))
    started = time.monotonic()

    def preapproved() -> frozenset[str]:
        return approved_ops if time.monotonic() - started < APPROVE_TTL_SECONDS else frozenset()

    server = MCPServer(
        name="lfmap", version=__version__, instructions="LFMAP plugins: " + ", ".join(e.id for e in entries)
    )
    for entry in entries:
        if not entry.manifest.adapters.mcp:
            continue
        for spec in entry.tool_class.operations().values():
            declared = entry.manifest.operation(spec.name)
            side_effects = declared.side_effects
            approved = f"{entry.id}.{spec.name}" in approved_ops
            annotations = ToolAnnotations(
                read_only_hint=side_effects == "none",
                open_world_hint=side_effects == "external" or entry.manifest.permissions.network,
            )
            server.add_tool(
                _make_tool(entry, spec, preapproved),
                name=tool_name(entry.id, spec.name),
                description=_description(spec, side_effects, approved, declared.min_tier),
                annotations=annotations,
                structured_output=True,
            )
    return server
