"""`lfmap` command line: plugin listing, generated operation commands and `serve mcp`."""

import inspect
import json
import sys
import types
import typing
from pathlib import Path
from typing import Annotated, Any, Literal

import typer
from pydantic import BaseModel, ValidationError
from pydantic_core import PydanticUndefined

from lfmap_core import grants
from lfmap_core.approval import Gate, Policy, audit, base_tier
from lfmap_core.config import load_config
from lfmap_core.errors import ToolError
from lfmap_core.registry import PluginEntry, Registry
from lfmap_core.runtime import run_operation
from lfmap_core.tool import OperationSpec

_FLAT = (str, int, float, bool, Path)


def _is_flat(annotation: Any) -> bool:
    if annotation in _FLAT or typing.get_origin(annotation) is Literal:
        return True
    args = [a for a in typing.get_args(annotation) if a is not type(None)]
    return typing.get_origin(annotation) in (typing.Union, types.UnionType) and len(args) == 1 and _is_flat(args[0])


def _interactive() -> bool:
    """A person at a terminal. Agents and scripts calling the CLI get no prompts and no extra rights."""
    return sys.stdin.isatty()


def _print_output(output: BaseModel, as_json: bool) -> None:
    if as_json:
        typer.echo(output.model_dump_json(indent=2))
        return
    for key, value in output.model_dump(mode="json").items():
        typer.echo(f"{key}: {value}")


def _operation_command(entry: PluginEntry, spec: OperationSpec):
    fields = spec.input_model.model_fields
    flat = all(_is_flat(f.annotation) for f in fields.values())
    side_effects = entry.manifest.operation(spec.name).side_effects

    def command(**kwargs: Any) -> None:
        as_json = kwargs.pop("json_output")
        assume_yes = kwargs.pop("yes")
        payload = (
            json.loads(kwargs.pop("input_json")) if not flat else {k: v for k, v in kwargs.items() if v is not None}
        )
        gate = Gate(
            entry.id,
            spec.name,
            "cli",
            Policy.from_config(load_config()),
            frozenset({f"{entry.id}.{spec.name}"}) if assume_yes else frozenset(),
            typer.confirm if _interactive() else None,
        )
        gate(base_tier(side_effects), "side_effects")
        _print_output(run_operation(entry, spec.name, payload, channel="cli", approver=gate), as_json)

    params = []
    if flat:
        for name, field in fields.items():
            required = field.default is PydanticUndefined
            option = typer.Option("--" + name.replace("_", "-"), help=field.description)
            default = ... if required else field.default
            if field.annotation is bool:
                option = typer.Option(
                    f"--{name.replace('_', '-')}/--no-{name.replace('_', '-')}", help=field.description
                )
            params.append(
                inspect.Parameter(
                    name,
                    inspect.Parameter.KEYWORD_ONLY,
                    default=default,
                    annotation=Annotated[field.annotation, option],
                )
            )
    else:
        option = typer.Option("--input-json", help="Whole input as JSON (this operation has nested fields).")
        params.append(
            inspect.Parameter("input_json", inspect.Parameter.KEYWORD_ONLY, annotation=Annotated[str, option])
        )
    params.append(
        inspect.Parameter(
            "json_output",
            inspect.Parameter.KEYWORD_ONLY,
            default=False,
            annotation=Annotated[bool, typer.Option("--json")],
        )
    )
    params.append(
        inspect.Parameter(
            "yes",
            inspect.Parameter.KEYWORD_ONLY,
            default=False,
            annotation=Annotated[bool, typer.Option("--yes", "-y", help="Approve overwrites and deletes (not T3).")],
        )
    )
    command.__signature__ = inspect.Signature(params)
    command.__doc__ = spec.description
    return command


def build_app(registry: Registry) -> typer.Typer:
    app = typer.Typer(
        name="lfmap",
        no_args_is_help=True,
        pretty_exceptions_enable=False,
        help="LFMAP plugins.",
    )
    plugins_app = typer.Typer(help="Inspect installed plugins.")
    serve_app = typer.Typer(help="Run adapters as servers.")
    approvals_app = typer.Typer(help="Time-limited approvals (interactive terminal only).")
    app.add_typer(plugins_app, name="plugins")
    app.add_typer(serve_app, name="serve")
    app.add_typer(approvals_app, name="approvals")
    known = {f"{e.id}.{op.name}" for e in registry.all() for op in e.manifest.operations}

    def require_person(action: str, key: str) -> tuple[str, str]:
        if not _interactive():
            raise ToolError("permission_denied", f"approvals {action} only works in an interactive terminal")
        if key not in known:
            raise ToolError("invalid_input", "Unknown operation; use <plugin>.<operation>", {"operation": key})
        plugin, _, op = key.partition(".")
        return plugin, op

    @approvals_app.command("grant")
    def grant(
        key: Annotated[str, typer.Argument(metavar="PLUGIN.OPERATION")],
        tier: Annotated[str, typer.Option("--tier", help="Highest tier covered: T1, T2 or T3.")] = "T2",
        duration: Annotated[str, typer.Option("--for", help="30m, 1h, 7d. T3 at most 24h, others 7d.")] = "1h",
    ) -> None:
        """Approve PLUGIN.OPERATION up to TIER for a limited time."""
        plugin, op = require_person("grant", key)
        record = grants.add(key, tier, grants.parse_duration(duration))
        audit(
            {
                "channel": "cli",
                "plugin": plugin,
                "operation": op,
                "tier": tier,
                "decision": "grant",
                "reason": f"until {record['expires_at']}",
            }
        )
        typer.echo(f"Granted {key} up to {tier} until {record['expires_at']}")

    @approvals_app.command("revoke")
    def revoke(key: Annotated[str, typer.Argument(metavar="PLUGIN.OPERATION")]) -> None:
        """Remove every grant for PLUGIN.OPERATION."""
        plugin, op = require_person("revoke", key)
        removed = grants.revoke(key)
        audit({"channel": "cli", "plugin": plugin, "operation": op, "decision": "revoke"})
        typer.echo(f"Revoked {removed} grant(s) for {key}")

    @approvals_app.command("list")
    def list_grants(json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
        """Show grants, including expired ones."""
        rows = grants.load()
        if json_output:
            typer.echo(json.dumps(rows, indent=2))
            return
        for row in rows:
            typer.echo(f"{row.get('operation')}  {row.get('tier')}  until {row.get('expires_at')}")

    @plugins_app.command("list")
    def list_plugins(json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
        """List installed plugins and their operations."""
        rows = [
            {"id": e.id, "version": e.manifest.plugin.version, "operations": [op.name for op in e.manifest.operations]}
            for e in registry.all()
        ]
        if json_output:
            typer.echo(json.dumps(rows, indent=2))
            return
        for row in rows:
            typer.echo(f"{row['id']}  {row['version']}  {', '.join(row['operations'])}")

    @serve_app.command("mcp")
    def serve_mcp(
        plugins: Annotated[list[str] | None, typer.Option("--plugins", help="Plugin ids; default all.")] = None,
        approve: Annotated[
            list[str] | None,
            typer.Option("--approve", help="Pre-approve <plugin>.<operation> up to T2 for 8 hours (never T3)."),
        ] = None,
    ) -> None:
        """Serve plugin operations as MCP tools over stdio."""
        from lfmap_core.mcp_adapter import build_server

        build_server(registry, plugins or [], approve or []).run()

    for entry in registry.all():
        if not entry.manifest.adapters.cli:
            continue
        plugin_app = typer.Typer(help=entry.manifest.plugin.description, no_args_is_help=True)
        for spec in entry.tool_class.operations().values():
            plugin_app.command(spec.name)(_operation_command(entry, spec))
        app.add_typer(plugin_app, name=entry.id)
    return app


def main() -> None:
    """Exit codes: 0 success, 1 business error (ToolError), 2 usage error or unexpected failure."""
    registry = Registry()
    registry.discover()
    try:
        build_app(registry)()
    except ToolError as error:
        typer.echo(f"Error [{error.code}]: {error.message}", err=True)
        sys.exit(1)
    except (ValidationError, json.JSONDecodeError) as error:
        typer.echo(f"Error [invalid_input]: {error}", err=True)
        sys.exit(1)
    except Exception as error:  # noqa: BLE001 - last resort for the CLI exit-code contract
        typer.echo(f"Error [internal]: {error}", err=True)
        sys.exit(2)
