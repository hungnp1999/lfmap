"""`lfmap` command line: plugin listing, generated operation commands, `serve mcp` and scheduled jobs."""

import inspect
import json
import subprocess
import sys
import types
import typing
from pathlib import Path
from typing import Annotated, Any, Literal

import typer
from pydantic import BaseModel, ValidationError
from pydantic_core import PydanticUndefined

from lfmap_core import approvals, grants, jobs
from lfmap_core.approval import Gate, Policy, audit, audit_path, base_tier
from lfmap_core.config import add_folder, config_path, load_config
from lfmap_core.errors import ToolError
from lfmap_core.registry import PluginEntry, Registry
from lfmap_core.runtime import build_tool, run_operation
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
        _print_output(
            run_operation(entry, spec.name, payload, channel="cli", approver=gate, explicit_read=_interactive()),
            as_json,
        )

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
    approvals_app = typer.Typer(help="Time-limited grants and the job approval queue (interactive terminal only).")
    config_app = typer.Typer(help="Manage configuration.")
    audit_app = typer.Typer(help="Audit logs.")
    jobs_app = typer.Typer(help="Scheduled jobs from jobs.toml (Windows Task Scheduler).")
    app.add_typer(plugins_app, name="plugins")
    app.add_typer(serve_app, name="serve")
    app.add_typer(approvals_app, name="approvals")
    app.add_typer(config_app, name="config")
    app.add_typer(audit_app, name="audit")
    app.add_typer(jobs_app, name="jobs")
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

    def queued_proposal(action: str, approval_id: str) -> approvals.Proposal:
        if not _interactive():
            raise ToolError("permission_denied", f"approvals {action} only works in an interactive terminal")
        approvals.sweep()
        return approvals.load(approval_id)

    def proposal_audit(proposal: approvals.Proposal, decision: str) -> None:
        record = {"channel": "cli", "plugin": proposal.plugin, "operation": proposal.operation, "tier": proposal.tier}
        audit({**record, "decision": decision, "reason": f"proposal {proposal.id}"})

    @approvals_app.command("pending")
    def pending(json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
        """Show job proposals waiting for approval; expired ones move to approvals\\expired."""
        proposals = approvals.pending()
        if json_output:
            rows = [p.model_dump(mode="json") for p in proposals]
            typer.echo(json.dumps(rows, indent=2, ensure_ascii=False))
            return
        for p in proposals:
            expires = p.expires.isoformat(timespec="minutes")
            typer.echo(f"{p.id}  {p.job}  {p.plugin}.{p.operation}  {p.tier}  {p.reason}  until {expires}")

    @approvals_app.command("approve")
    def approve(
        approval_id: Annotated[str, typer.Argument(metavar="ID")],
        json_output: Annotated[bool, typer.Option("--json")] = False,
    ) -> None:
        """Show a job proposal and, once confirmed, run it one time (interactive terminal only)."""
        proposal = queued_proposal("approve", approval_id)
        entry = registry.get(proposal.plugin)
        declared = entry.manifest.operation(proposal.operation)
        if declared is None:
            raise ToolError("not_found", f"Unknown operation {proposal.plugin}.{proposal.operation}")
        jobs.check_input(entry, proposal.operation, proposal.input)
        policy = Policy.from_config(load_config())
        key = f"{proposal.plugin}.{proposal.operation}"
        typer.echo(f"Proposal {proposal.id} from job {proposal.job}, created {proposal.created.isoformat()}")
        on = f" on {proposal.detail}" if proposal.detail else ""
        typer.echo(approvals.visible(f"{key} ({proposal.tier}, {proposal.reason}){on}"))
        typer.echo("input: " + approvals.visible(json.dumps(proposal.input, ensure_ascii=False)))
        if not typer.confirm(f"Run {key} now with this input?"):
            typer.echo("Not approved; the proposal stays pending")
            return
        approvals.move(proposal.id, "done")
        proposal_audit(proposal, "approve")
        gate = approvals.ApprovedGate(proposal, Gate(entry.id, proposal.operation, "cli", policy, ask=typer.confirm))
        gate(base_tier(declared.side_effects), "side_effects")
        output = run_operation(entry, proposal.operation, proposal.input, channel="cli", approver=gate)
        _print_output(output, json_output)

    @approvals_app.command("reject")
    def reject(approval_id: Annotated[str, typer.Argument(metavar="ID")]) -> None:
        """Reject a job proposal; it moves to approvals\\rejected (interactive terminal only)."""
        proposal = queued_proposal("reject", approval_id)
        approvals.move(proposal.id, "rejected")
        proposal_audit(proposal, "reject")
        typer.echo(f"Rejected {proposal.id}")

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

    @plugins_app.command("health")
    def plugins_health(json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
        """Check the health of all plugins."""
        results = []
        for entry in registry.all():
            try:
                health = build_tool(entry).health()
                results.append({"id": entry.id, **health})
            except ToolError as error:
                results.append({"id": entry.id, "ok": False, "error": f"{error.code}: {error.message}"})
        if json_output:
            typer.echo(json.dumps(results, indent=2))
            return
        for result in results:
            typer.echo(f"{result['id']}  {'ok' if result.get('ok', False) else 'FAIL'}  {result.get('error', '')}")

    @config_app.command("path")
    def config_path_command(json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
        """Show the configuration path and plugin permissions."""
        config = str(config_path())
        plugins = []
        for entry in registry.all():
            perms = build_tool(entry).ctx.permissions
            plugins.append({"id": entry.id, "read": perms.read_roots, "write": perms.write_roots})
        if json_output:
            typer.echo(json.dumps({"config": config, "plugins": plugins}, indent=2))
            return
        typer.echo(config)
        for plugin in plugins:
            typer.echo(f"{plugin['id']}  read: {', '.join(plugin['read'])}  write: {', '.join(plugin['write'])}")

    @config_app.command("add-folder")
    def config_add_folder(
        folder: Annotated[str, typer.Argument(metavar="FOLDER")],
        name: Annotated[str, typer.Option("--as", help="Name of the folder in the config.")],
    ) -> None:
        """Add a folder to the configuration."""
        if not _interactive():
            raise ToolError("permission_denied", "config add-folder only works in an interactive terminal")
        root = add_folder(name, folder)
        audit({"channel": "cli", "decision": "grant", "reason": f"add-folder {name}", "target": root})
        typer.echo(root)

    @audit_app.command("tail")
    def audit_tail(
        n: Annotated[int, typer.Option("-n", help="Number of lines to show.")] = 20,
        json_output: Annotated[bool, typer.Option("--json")] = False,
    ) -> None:
        """Show the last N lines of the audit log."""
        try:
            with audit_path().open(encoding="utf-8") as f:
                lines = f.readlines()
        except FileNotFoundError:
            lines = []
        records = [json.loads(line) for line in lines[-n:] if line.strip()] if n > 0 else []
        if json_output:
            typer.echo(json.dumps(records, indent=2, ensure_ascii=False))
            return
        for record in records:
            fields = [
                record.get("time"),
                record.get("channel"),
                f"{record.get('plugin')}.{record.get('operation')}" if record.get("plugin") else None,
                record.get("tier"),
                record.get("decision"),
                record.get("reason"),
                record.get("target"),
            ]
            typer.echo("  ".join(str(field) for field in fields if field is not None))

    @jobs_app.command("list")
    def jobs_list(json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
        """List the jobs in jobs.toml."""
        rows = [
            {
                "id": job.id,
                "operation": f"{job.plugin}.{job.operation}",
                "schedule": job.schedule.describe(),
                "enabled": job.enabled,
            }
            for job in jobs.load_jobs()
        ]
        if json_output:
            typer.echo(json.dumps(rows, indent=2, ensure_ascii=False))
            return
        for row in rows:
            state = "enabled" if row["enabled"] else "disabled"
            typer.echo(f"{row['id']}  {row['operation']}  {row['schedule']}  {state}")

    @jobs_app.command("run")
    def jobs_run(
        job_id: Annotated[str, typer.Argument(metavar="ID")],
        json_output: Annotated[bool, typer.Option("--json")] = False,
    ) -> None:
        """Run one job now, as Task Scheduler would."""
        _print_output(jobs.run_job(registry, job_id), json_output)

    @jobs_app.command("register")
    def jobs_register(
        dry_run: Annotated[bool, typer.Option("--dry-run", help="Print the schtasks commands only.")] = False,
        repo: Annotated[Path | None, typer.Option("--repo", help="Repository root; default this checkout.")] = None,
        uv: Annotated[Path | None, typer.Option("--uv", help="Path to uv.exe; default PATH, then WinGet.")] = None,
    ) -> None:
        """Create or update a task in \\LFMAP\\ for each enabled job; delete the tasks of the others."""
        repo = repo or jobs.repo_root()
        uv = uv or jobs.find_uv()
        job_list = jobs.load_jobs()
        try:
            existing = jobs.existing_tasks()
        except ToolError as error:
            if not dry_run or error.code != "backend_unavailable":
                raise
            typer.echo(f"Warning: {error.message}; assuming no task is registered yet", err=True)
            existing = set()
        script = repo / "scripts" / "Invoke-LfmapJob.ps1"
        for command in jobs.register_commands(job_list, existing, repo, uv, script):
            typer.echo(subprocess.list2cmdline(command))
            if not dry_run:
                jobs._schtasks(command)

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
