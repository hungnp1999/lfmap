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
        if side_effects != "none" and not assume_yes:
            typer.confirm(f"{entry.id} {spec.name} has side effects ({side_effects}). Continue?", abort=True)
        _print_output(run_operation(entry, spec.name, payload), as_json)

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
            annotation=Annotated[bool, typer.Option("--yes", "-y", help="Skip the side-effect confirmation.")],
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
    app.add_typer(plugins_app, name="plugins")
    app.add_typer(serve_app, name="serve")

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
    ) -> None:
        """Serve plugin operations as MCP tools over stdio."""
        from lfmap_core.mcp_adapter import build_server

        build_server(registry, plugins or []).run()

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
