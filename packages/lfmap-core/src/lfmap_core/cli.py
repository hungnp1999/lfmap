"""`lfmap` command line: plugin listing, generated operation commands, `serve mcp`, scheduled jobs and events."""

import base64
import dataclasses
import inspect
import json
import os
import secrets
import subprocess
import sys
import types
import typing
from pathlib import Path
from typing import Annotated, Any, Literal

import typer
from pydantic import BaseModel, ValidationError
from pydantic_core import PydanticUndefined

from lfmap_core import (
    approvals,
    auth,
    backup,
    flows,
    flows_run,
    flows_triggers,
    grants,
    jobs,
    jobs_doctor,
    jobs_flow,
    security_doctor,
    totp,
)
from lfmap_core.approval import Gate, Policy, audit, audit_path
from lfmap_core.config import (
    add_folder,
    commit_edit,
    config_path,
    data_class_key,
    edit_data_class,
    load_config,
    parse_config_text,
)
from lfmap_core.data_classes import CLASSES, load_class_map
from lfmap_core.errors import ToolError
from lfmap_core.events import MAX_PAYLOAD_BYTES
from lfmap_core.events_adapter import bus_path, drain_after_job, open_bus, run_adapter
from lfmap_core.permissions import PermissionManager
from lfmap_core.registry import PluginEntry, Registry
from lfmap_core.runtime import build_tool, call_tier, run_operation
from lfmap_core.tool import OperationSpec

_FLAT = (str, int, float, bool, Path)
_WINDOWS = sys.platform == "win32"
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O or 1/I
CODE_LENGTH = 6


def _is_flat(annotation: Any) -> bool:
    if annotation in _FLAT or typing.get_origin(annotation) is Literal:
        return True
    args = [a for a in typing.get_args(annotation) if a is not type(None)]
    return typing.get_origin(annotation) in (typing.Union, types.UnionType) and len(args) == 1 and _is_flat(args[0])


def _console_stdin() -> bool:
    """Windows: stdin is a console. `isatty()` is also True for NUL (a character device); GetConsoleMode
    fails for NUL, files and pipes."""
    try:
        import ctypes  # Windows-only modules, imported here
        import msvcrt
        from ctypes import wintypes

        handle = wintypes.HANDLE(msvcrt.get_osfhandle(sys.stdin.fileno()))
        mode = wintypes.DWORD()
        return bool(ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(mode)))
    except Exception:  # noqa: BLE001 - anything unexpected means nobody is known to be there
        return False


def _console_window() -> bool:
    """Windows: the console has a window a person can see. Hidden consoles of agent shells have none."""
    try:
        import ctypes  # Windows-only modules, imported here
        from ctypes import wintypes

        get_window = ctypes.WINFUNCTYPE(wintypes.HWND)(("GetConsoleWindow", ctypes.windll.kernel32))
        return bool(get_window())
    except Exception:  # noqa: BLE001 - anything unexpected means nobody is known to be there
        return False


def _interactive() -> bool:
    """A person at a terminal. Agents and scripts calling the CLI get no prompts and no extra rights.

    This stops scripts and accidents, not an agent of the same user that drives a real console (#108).
    """
    try:
        return _console_stdin() and _console_window() if _WINDOWS else sys.stdin.isatty()
    except Exception:  # noqa: BLE001 - a closed or replaced stdin is not a person
        return False


def _confirm_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def _deny(action: str, record: dict[str, Any], reason: str) -> None:
    audit({"channel": "cli", **record, "decision": "deny", "reason": f"{action}: {reason}"})


def _typed_code(action: str, record: dict[str, Any]) -> None:
    """The person types back a fresh random code; a mismatch or end of input refuses and is audited."""
    code = _confirm_code()
    typer.echo(approvals.visible(f"To {action}, type this code: {code}"))
    try:
        typed = typer.prompt("Code", default="", show_default=False)
    except (EOFError, typer.Abort):
        typed = ""
    if typed.strip().upper() != code:
        _deny(action, record, "confirmation code not typed")
        raise ToolError("permission_denied", f"{action} cancelled: the confirmation code did not match")


def _totp_code(action: str, record: dict[str, Any]) -> None:
    typer.echo(approvals.visible(f"To {action}, enter the code from your authenticator app:"))
    try:
        typed = typer.prompt("Code", default="", show_default=False, hide_input=True)
    except (EOFError, typer.Abort):
        typed = ""
    try:
        auth.check(typed)
    except ToolError as error:
        _deny(action, record, "authenticator code not accepted")
        raise ToolError("permission_denied", f"{action} cancelled: {error.message}") from None


def _require_code(action: str, record: dict[str, Any]) -> None:
    """The single owner-code prompt: the authenticator code once enrolled (an invalid auth.json refuses), else the
    typed random code. A terminal is checked first."""
    if not _interactive():
        raise ToolError("permission_denied", f"{action} only works in an interactive terminal")
    if auth.enrolled():
        _totp_code(action, record)
    else:
        _typed_code(action, record)


def _print_output(output: BaseModel, as_json: bool) -> None:
    if as_json:
        typer.echo(output.model_dump_json(indent=2))
        return
    for key, value in output.model_dump(mode="json").items():
        typer.echo(f"{key}: {value}")


def _operation_command(entry: PluginEntry, spec: OperationSpec):
    fields = spec.input_model.model_fields
    flat = all(_is_flat(f.annotation) for f in fields.values())

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
        gate(call_tier(entry, spec.name, payload), "side_effects")
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


def _events_counts() -> tuple[dict[str, dict[str, int]], str]:
    """Delivery counts of the user's bus and a note; never creates `events.db`."""
    if not bus_path().exists():
        return {}, "no events.db yet"
    try:
        bus = open_bus()
        try:
            return bus.counts(), ""
        finally:
            bus.close()
    except ToolError as error:
        return {}, f"cannot read the bus: {error.message}"


def _print_run(run: flows_run.FlowRun, as_json: bool) -> None:
    """A run step by step; outputs only with `--json`, errors without their details."""
    if as_json:
        typer.echo(run.model_dump_json(indent=2))
        return
    typer.echo(approvals.visible(f"{run.run_id}  {run.flow}  {run.status}"))
    for step in run.steps:
        note = f"  {step.error['code']}: {step.error['message']}" if step.error else ""
        typer.echo(approvals.visible(f"  {step.id}  {step.status}{note}"))
    if run.approval_id:
        typer.echo(f"Approve with: lfmap approvals approve {run.approval_id}")


def _input_json(file: str | None) -> dict[str, Any]:
    """The trigger payload of `flows start --input-json FILE`: a JSON object of at most 64 KiB. The path is read
    through a Permission Manager with no roots, so only a person at an interactive terminal may name a file."""

    def audit_read(path: str) -> None:
        audit(
            {
                "channel": "cli",
                "plugin": "flows",
                "tier": "T0",
                "decision": "allow",
                "reason": "read_outside_roots",
                "target": path,
            }
        )

    if file is None:
        return {}
    path = PermissionManager([], [], explicit_read=_interactive(), on_outside_read=audit_read).require_read(file)
    try:
        if path.stat().st_size > MAX_PAYLOAD_BYTES:
            raise ToolError("invalid_input", f"{file} is larger than {MAX_PAYLOAD_BYTES} bytes")
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ToolError("not_found", f"Cannot read {file}", {"error": error.strerror}) from error
    except ValueError as error:
        raise ToolError("invalid_input", f"{file} is not valid JSON", {"error": str(error)}) from error
    if not isinstance(payload, dict):
        raise ToolError("invalid_input", f"{file} must hold a JSON object")
    return payload


_EFFECTS = {
    "scratch": "Overwrites here will be audited instead of asked.",
    "normal": "Tiers here stay as each action sets them.",
    "private": "Tiers here stay as each action sets them.",
    "secret": "Reads here will be audited and writes asked.",
}


def _edit_class(verb: str, raw: str, data_class: str | None) -> None:
    """`data classify` and `data unclassify`: edit one line of [data.classes] after the person has agreed.

    Lowering is decided by comparing `class_of` before and after; raising asks yes/no, lowering asks the owner code."""
    if not _interactive():
        _deny(f"data {verb}", {"target": raw}, "not an interactive terminal")
        raise ToolError("permission_denied", f"data {verb} only works in an interactive terminal")
    if data_class is not None and data_class not in CLASSES:
        raise ToolError("invalid_input", f"Class must be one of {', '.join(CLASSES)}", {"class": data_class})
    key = data_class_key(raw)
    edit = edit_data_class(key, data_class)
    if edit.previous == data_class and data_class is not None:
        typer.echo(approvals.visible(f"{key} is already {data_class}; nothing to change."))
        return
    if edit.previous is None and data_class is None:
        raise ToolError("invalid_input", "No [data.classes] entry for this path", {"path": key})
    before_map = load_class_map(parse_config_text(edit.old_text))
    after_map = load_class_map(parse_config_text(edit.new_text))  # an invalid result is refused here, nothing written
    before, after = before_map.class_of(key), after_map.class_of(key)
    lowering = CLASSES.index(after) < CLASSES.index(before)
    word = "lower" if lowering else "higher" if after != before else "same"
    typer.echo(approvals.visible(f"{key}: {before} -> {after} ({word}). {_EFFECTS[after]}"))
    if not after_map:
        typer.echo("[data.classes] will have no entry left: the feature is off and every path behaves as before.")
    action = f"data {verb} {before} -> {after}"
    if lowering:
        _require_code(action, {"target": key})
    else:
        try:
            agreed = typer.confirm("Apply this change?", default=False)
        except typer.Abort:
            agreed = False
        if not agreed:
            _deny(action, {"target": key}, "not confirmed")
            raise ToolError("permission_denied", f"{action} cancelled")
    commit_edit(edit)
    audit({"channel": "cli", "decision": "grant", "reason": action, "target": key})
    typer.echo(approvals.visible(f"{key}: {after}"))


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
    events_app = typer.Typer(help="The event bus: run the event adapter, inspect and repair the queue.")
    flows_app = typer.Typer(help="Declared flows from flows.toml.")
    auth_app = typer.Typer(help="Authenticator (TOTP) for the owner code (interactive terminal only).")
    backup_app = typer.Typer(help="Back up and restore the owner's state (restore: interactive terminal only).")
    data_app = typer.Typer(help="Data classes of folders, [data.classes] (classify and unclassify: interactive only).")
    app.add_typer(plugins_app, name="plugins")
    app.add_typer(serve_app, name="serve")
    app.add_typer(approvals_app, name="approvals")
    app.add_typer(config_app, name="config")
    app.add_typer(audit_app, name="audit")
    app.add_typer(jobs_app, name="jobs")
    app.add_typer(events_app, name="events")
    app.add_typer(flows_app, name="flows")
    app.add_typer(auth_app, name="auth")
    app.add_typer(data_app, name="data")
    app.add_typer(backup_app, name="backup", invoke_without_command=True)
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
        length = grants.parse_duration(duration)
        grants.check(tier, length)
        _require_code(f"grant {key} up to {tier} for {duration}", {"plugin": plugin, "operation": op, "tier": tier})
        record = grants.add(key, tier, length)
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
        _require_code(f"revoke {key}", {"plugin": plugin, "operation": op})
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

    def approve_flow(proposal: approvals.Proposal, json_output: bool) -> None:
        flow, run, index = flows_run.check_resume(proposal)
        step = flow.steps[index]
        typer.echo(
            f"Proposal {proposal.id} from flow {run.flow}, run {run.run_id}, created {proposal.created.isoformat()}"
        )
        typer.echo(approvals.visible(f"flows.resume ({proposal.tier}, {proposal.reason})"))
        typer.echo("input: " + approvals.visible(json.dumps(proposal.input, ensure_ascii=False)))
        if not typer.confirm(f"Resume run {run.run_id} at step {step.id} now?"):
            typer.echo("Not approved; the proposal stays pending")
            return
        proposal_audit(proposal, "approve")
        _print_run(flows_run.resume(registry, proposal, typer.confirm), json_output)

    @auth_app.command("enroll")
    def auth_enroll() -> None:
        """Enrol an authenticator app. The secret is printed once here and stored only after one code verifies."""
        if not _interactive():
            raise ToolError("permission_denied", "auth enroll only works in an interactive terminal")
        protector = auth.default_protector()
        if auth.enrolled():
            _require_code("replace the authenticator enrolment", {})
        secret = totp.new_secret()
        typer.echo("Add this account in your authenticator app (manual entry), then enter one code.")
        typer.echo(f"URI:    {totp.provisioning_uri(secret)}")
        typer.echo(f"Secret: {base64.b32encode(secret).decode('ascii')}")
        try:
            typed = typer.prompt("Code", default="", show_default=False, hide_input=True)
        except (EOFError, typer.Abort):
            typed = ""
        try:
            auth.enroll(secret, typed, protector)
        except ToolError:
            _deny("auth enroll", {}, "authenticator code not accepted")
            raise
        audit({"channel": "cli", "decision": "allow", "reason": "auth enrolled"})
        typer.echo("Enrolled. Commands that ask for the owner code now ask for the app code.")

    @auth_app.command("status")
    def auth_status() -> None:
        """Show whether an authenticator is enrolled (never the secret)."""
        info = auth.status()
        if not info["enrolled"]:
            typer.echo("enrolled: no (the typed code is used)")
            return
        typer.echo(f"enrolled: yes, since {info['enrolled_at']}")
        typer.echo(f"locked: {'yes' if info['locked'] else 'no'}")

    @auth_app.command("reset")
    def auth_reset() -> None:
        """Remove the enrolment after a typed code; use it when the phone is lost (interactive terminal only)."""
        if not _interactive():
            raise ToolError("permission_denied", "auth reset only works in an interactive terminal")
        _typed_code("reset the authenticator enrolment", {})
        removed = auth.reset()
        audit({"channel": "cli", "decision": "allow", "reason": "auth reset" if removed else "auth reset: none"})
        typer.echo("Authenticator removed; the typed code is used again." if removed else "Nothing was enrolled.")

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
            line = f"{p.id}  {p.job}  {p.plugin}.{p.operation}  {p.tier}  {p.reason}  until {expires}"
            typer.echo(approvals.visible(line))

    @approvals_app.command("approve")
    def approve(
        approval_id: Annotated[str, typer.Argument(metavar="ID")],
        json_output: Annotated[bool, typer.Option("--json")] = False,
    ) -> None:
        """Show a job proposal and, once confirmed, run it one time (interactive terminal only).

        A flows.resume proposal resumes its paused flow run instead and carries on with the next steps."""
        proposal = queued_proposal("approve", approval_id)
        if approvals.is_flow_resume(proposal):
            approve_flow(proposal, json_output)
            return
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
        if proposal.tier == "T3":
            _require_code(
                f"run {key} (T3) now with this input",
                {"plugin": proposal.plugin, "operation": proposal.operation, "tier": proposal.tier},
            )
        elif not typer.confirm(f"Run {key} now with this input?"):
            typer.echo("Not approved; the proposal stays pending")
            return
        approvals.move(proposal.id, "done")
        proposal_audit(proposal, "approve")
        gate = approvals.ApprovedGate(proposal, Gate(entry.id, proposal.operation, "cli", policy, ask=typer.confirm))
        gate(call_tier(entry, proposal.operation, proposal.input), "side_effects")
        output = run_operation(entry, proposal.operation, proposal.input, channel="cli", approver=gate)
        _print_output(output, json_output)

    @approvals_app.command("reject")
    def reject(approval_id: Annotated[str, typer.Argument(metavar="ID")]) -> None:
        """Reject a job proposal; it moves to approvals\\rejected (interactive terminal only)."""
        proposal = queued_proposal("reject", approval_id)
        approvals.move(proposal.id, "rejected")
        proposal_audit(proposal, "reject")
        if approvals.is_flow_resume(proposal):
            flows_run.close(proposal, "rejected")
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
        _require_code(f"add {folder} as {name}", {"target": folder})
        root = add_folder(name, folder)
        audit({"channel": "cli", "decision": "grant", "reason": f"add-folder {name}", "target": root})
        typer.echo(root)

    @data_app.command("classes")
    def data_classes_command(json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
        """Show the [data.classes] table as loaded, and warn about folders that do not exist."""
        rows = [
            {"path": e.path, "class": e.data_class, "exists": os.path.isdir(e.path)}
            for e in sorted(load_class_map(load_config()).entries, key=lambda e: e.path)
        ]
        if json_output:
            typer.echo(json.dumps(rows, indent=2))
        elif not rows:
            typer.echo("no table (class model off)")
        for row in [] if json_output else rows:
            typer.echo(approvals.visible(f"{row['class']:<8} {row['path']}{'' if row['exists'] else '  (missing)'}"))

    @data_app.command("explain")
    def data_explain(
        path: Annotated[str, typer.Argument(metavar="PATH")],
        json_output: Annotated[bool, typer.Option("--json")] = False,
    ) -> None:
        """Show which entry decides the class of PATH. Reads only the configuration."""
        class_map = load_class_map(load_config())
        data_class, entry = class_map.lookup(path)  # refuses network and device paths before any realpath
        report = {
            "path": os.path.realpath(path),
            "active": bool(class_map),
            "class_of": data_class,
            "entry": entry,
            "class_under": class_map.class_under(path),
        }
        if json_output:
            typer.echo(json.dumps(report, indent=2))
            return
        typer.echo(approvals.visible(report["path"]))
        typer.echo(approvals.visible(f"  class_of:    {data_class} ({'entry ' + entry if entry else 'no entry'})"))
        typer.echo(f"  class_under: {report['class_under']}")
        if not class_map:
            typer.echo("  [data.classes] is empty: the class model is off and nothing here changes")

    @data_app.command("classify")
    def data_classify(
        path: Annotated[str, typer.Argument(metavar="PATH")],
        data_class: Annotated[str, typer.Argument(metavar="CLASS", help=" | ".join(CLASSES))],
    ) -> None:
        """Add or change the class of a folder. Lowering it also needs the owner code."""
        _edit_class("classify", path, data_class)

    @data_app.command("unclassify")
    def data_unclassify(path: Annotated[str, typer.Argument(metavar="PATH")]) -> None:
        """Remove the entry of a folder. Lowering its class also needs the owner code."""
        _edit_class("unclassify", path, None)

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

    @backup_app.callback()
    def backup_create(
        ctx: typer.Context,
        to: Annotated[str | None, typer.Option("--to", help="Folder inside the declared [backup] folder.")] = None,
        json_output: Annotated[bool, typer.Option("--json")] = False,
    ) -> None:
        """Without a subcommand: write one dated zip into the [backup] folder of config.toml, then prune old ones."""
        if ctx.invoked_subcommand is not None:
            return
        result = backup.create(to)
        audit({"channel": "cli", "decision": "allow", "reason": "backup created", "target": Path(result["path"]).name})
        typer.echo(json.dumps(result, ensure_ascii=False) if json_output else approvals.visible(result["path"]))

    @backup_app.command("list")
    def backup_list(json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
        """List the backups in the declared folder, oldest first."""
        names = [p.name for p in backup.list_backups(backup.settings()["folder"])]
        typer.echo(json.dumps(names, indent=2) if json_output else "\n".join(names))

    @backup_app.command("restore")
    def backup_restore(
        archive: Annotated[str, typer.Argument(metavar="ZIP")],
        json_output: Annotated[bool, typer.Option("--json")] = False,
    ) -> None:
        """Replace the owner's files with the ones in ZIP (interactive terminal and a typed code)."""
        if not _interactive():
            raise ToolError("permission_denied", "backup restore only works in an interactive terminal")
        path = PermissionManager([], [], explicit_read=True).require_read(archive)
        if not path.is_file():
            raise ToolError("not_found", "Backup file not found", {"path": archive})
        _require_code(f"restore {path.name}", {"target": path.name})
        result = backup.restore(path)
        audit({"channel": "cli", "decision": "grant", "reason": "backup restored", "target": path.name})
        typer.echo(json.dumps(result, ensure_ascii=False) if json_output else f"Restored {result['restored']} files")
        if result["reindex"]:
            typer.echo("Run `lfmap knowledge reindex` to rebuild search (the backup holds no document text).", err=True)

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
        max_events: Annotated[
            int, typer.Option("--max-events", min=1, help="Handler calls allowed when draining the event bus.")
        ] = 1000,
    ) -> None:
        """Run one job now, as Task Scheduler would, then drain the event bus (bounded by --max-events)."""
        try:
            _print_output(jobs_flow.run_job(registry, job_id, max_events=max_events), json_output)
        finally:
            try:
                handled = drain_after_job(registry, max_events)
            except ToolError as error:
                typer.echo(f"Warning: events were not drained: {error}", err=True)
            else:
                if handled:
                    typer.echo(f"Handled {handled} event(s)", err=True)

    @jobs_app.command("register")
    def jobs_register(
        dry_run: Annotated[bool, typer.Option("--dry-run", help="Print the schtasks commands only.")] = False,
        repo: Annotated[
            Path | None,
            typer.Option("--repo", help="Runtime root; default [runtime] root in jobs.toml, else this checkout."),
        ] = None,
        uv: Annotated[Path | None, typer.Option("--uv", help="Path to uv.exe; default PATH, then WinGet.")] = None,
        pwsh: Annotated[
            Path | None, typer.Option("--pwsh", help="Path to pwsh.exe; default found by full path.")
        ] = None,
    ) -> None:
        """Create or update a task in \\LFMAP\\ for each enabled job and scheduled flow; delete the others."""
        jobs_file = jobs.load_jobs_file()
        repo = repo or jobs.runtime_root(jobs_file)
        uv = uv or jobs.find_uv()
        pwsh = pwsh or jobs.find_pwsh()
        job_list = jobs_file.jobs
        script = repo / "scripts" / "Invoke-LfmapJob.ps1"
        flow_tasks = flows_triggers.task_commands(flows.load_flows(), repo, uv, script, pwsh)
        flow_tasks |= backup.task_commands(load_config(), repo, uv, script, pwsh)
        try:
            existing = jobs.existing_tasks()
        except ToolError as error:
            if not dry_run or error.code != "backend_unavailable":
                raise
            typer.echo(f"Warning: {error.message}; assuming no task is registered yet", err=True)
            existing = set()
        for command in jobs.register_commands(job_list, existing, repo, uv, script, pwsh, extra=flow_tasks):
            typer.echo(subprocess.list2cmdline(command))
            if not dry_run:
                jobs._schtasks(command)

    @jobs_app.command("doctor")
    def jobs_doctor_command(json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
        """Check, read-only, that this machine can run the jobs; exit 1 when a check fails."""
        checks = jobs_doctor.run_checks(registry)
        if json_output:
            typer.echo(json.dumps([dataclasses.asdict(check) for check in checks], indent=2, ensure_ascii=False))
        else:
            width = max(len(check.name) for check in checks)
            for check in checks:
                status = {True: "ok", None: "warn", False: "FAIL"}[check.ok]
                fix = f"  -> {check.fix}" if check.fix else ""
                typer.echo(f"{check.name:<{width}}  {status:<4}  {check.detail}{fix}")
        if any(check.ok is False for check in checks):
            raise typer.Exit(1)

    @app.command("doctor")
    def doctor_command(json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
        """Run `jobs doctor`, `flows check`, `events status` and the Windows Security checks together, read-only.

        Exit 1 when a job check or a flow fails; the security group only warns."""
        checks = jobs_doctor.run_checks(registry)
        try:
            findings = [text for flow in jobs_flow.load_all() for text in flows.check_flow(registry, flow)]
        except ToolError as error:
            findings = [error.message]
        counts, events_note = _events_counts()
        security = security_doctor.run_checks()
        dead = [name for name, states in counts.items() if states.get("dead")]
        failed = any(check.ok is False for check in checks) or bool(findings)
        if json_output:
            report = {
                "ok": not failed,
                "jobs": [dataclasses.asdict(check) for check in checks],
                "flows": [{"finding": text} for text in findings],
                "events": {"note": events_note, "subscriptions": counts, "warn": dead},
                "security": {"skipped": "Windows only"}
                if security is None
                else [dataclasses.asdict(check) for check in security],
            }
            typer.echo(json.dumps(report, indent=2, ensure_ascii=False))
        else:
            typer.echo("jobs")
            width = max(len(check.name) for check in checks)
            for check in checks:
                status = {True: "ok", None: "warn", False: "FAIL"}[check.ok]
                fix = f"  -> {check.fix}" if check.fix else ""
                typer.echo(f"  {check.name:<{width}}  {status:<4}  {check.detail}{fix}")
            typer.echo("flows")
            for text in findings:
                typer.echo(approvals.visible(f"  FAIL  {text}"))
            if not findings:
                typer.echo("  ok    All flows ok")
            typer.echo("events")
            if events_note:
                typer.echo(f"  warn  {events_note}" if events_note.startswith("cannot") else f"  ok    {events_note}")
            for name, states in counts.items():
                status = "warn" if name in dead else "ok  "
                typer.echo(
                    approvals.visible(f"  {status}  {name}  " + "  ".join(f"{s}={n}" for s, n in states.items()))
                )
            typer.echo("security")
            if security is None:
                typer.echo("  skipped (Windows only)")
            for check in security or []:
                fix = f"  -> {check.fix}" if check.fix else ""
                typer.echo(f"  {'ok  ' if check.ok else 'warn'}  {check.name}  {check.detail}{fix}")
        if failed:
            raise typer.Exit(1)

    @flows_app.command("list")
    def flows_list(json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
        """List the flows in flows.toml with their trigger and last run status."""
        rows = [
            {
                "id": flow.id,
                "trigger": flow.trigger.describe(),
                "enabled": flow.enabled,
                "steps": len(flow.steps),
                "last_run": flows.last_run_status(flow.id),
            }
            for flow in jobs_flow.load_all()
        ]
        if json_output:
            typer.echo(json.dumps(rows, indent=2, ensure_ascii=False))
            return
        for row in rows:
            state = "enabled" if row["enabled"] else "disabled"
            typer.echo(approvals.visible(f"{row['id']}  {row['trigger']}  {state}  {row['last_run'] or '-'}"))

    @flows_app.command("check")
    def flows_check(json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
        """Check every flow against the registry; exit 1 when there is a finding."""
        found = [(flow.id, text) for flow in jobs_flow.load_all() for text in flows.check_flow(registry, flow)]
        if json_output:
            typer.echo(json.dumps([{"flow": i, "finding": t} for i, t in found], indent=2, ensure_ascii=False))
        else:
            for _, text in found:
                typer.echo(approvals.visible(text))
            if not found:
                typer.echo("All flows ok")
        if found:
            raise typer.Exit(1)

    @flows_app.command("start")
    def flows_start(
        flow_id: Annotated[str, typer.Argument(metavar="FLOW")],
        input_json: Annotated[
            str | None, typer.Option("--input-json", help="JSON object file: the trigger payload.")
        ] = None,
        json_output: Annotated[bool, typer.Option("--json")] = False,
    ) -> None:
        """Start a run of FLOW; it stops at the first step above the flow's max_tier or at an approve step."""
        run = flows_run.start(registry, flow_id, _input_json(input_json))
        _print_run(run, json_output)
        if run.status == "failed":
            raise typer.Exit(1)

    @flows_app.command("status")
    def flows_status(
        run_id: Annotated[str, typer.Argument(metavar="RUN")],
        json_output: Annotated[bool, typer.Option("--json", help="Include the step outputs.")] = False,
    ) -> None:
        """Show one run, step by step."""
        _print_run(flows_run.load_run(run_id), json_output)

    @flows_app.command("runs")
    def flows_runs(
        flow: Annotated[str | None, typer.Option("--flow", help="Only runs of this flow.")] = None,
        limit: Annotated[int, typer.Option("--limit", min=1)] = 20,
    ) -> None:
        """Recent runs, newest first."""
        for run in flows_run.list_runs(flow, limit):
            typer.echo(
                approvals.visible(
                    f"{run.run_id}  {run.flow}  {run.status}  {run.updated.isoformat(timespec='seconds')}"
                )
            )

    def require_terminal(action: str) -> None:
        if not _interactive():
            raise ToolError("permission_denied", f"events {action} only works in an interactive terminal")

    @events_app.command("status")
    def events_status(json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
        """Deliveries per subscription and state."""
        bus = open_bus()
        try:
            counts = bus.counts()
        finally:
            bus.close()
        if json_output:
            typer.echo(json.dumps(counts, indent=2))
            return
        for name, states in counts.items():
            typer.echo(approvals.visible(f"{name}  " + "  ".join(f"{s}={n}" for s, n in states.items())))

    @events_app.command("dead")
    def events_dead(
        subscription: Annotated[str | None, typer.Option("--subscription", help="Only this subscription.")] = None,
        json_output: Annotated[bool, typer.Option("--json")] = False,
    ) -> None:
        """List dead letters (events a handler gave up on)."""
        bus = open_bus()
        try:
            letters = bus.dead_letters(subscription)
        finally:
            bus.close()
        if json_output:
            typer.echo(json.dumps([letter.model_dump(mode="json") for letter in letters], indent=2))
            return
        for letter in letters:
            line = f"{letter.event.id}  {letter.subscription}  {letter.event.topic}  attempts={letter.attempts}"
            typer.echo(approvals.visible(f"{line}  {letter.error}"))

    @events_app.command("retry")
    def events_retry(
        event_id: Annotated[str, typer.Argument(metavar="EVENT_ID")],
        subscription: Annotated[str, typer.Argument(metavar="SUBSCRIPTION")],
    ) -> None:
        """Put one dead letter back in the queue (interactive terminal only)."""
        require_terminal("retry")
        bus = open_bus()
        try:
            bus.retry(event_id, subscription)
        finally:
            bus.close()
        typer.echo(approvals.visible(f"Queued {event_id} for {subscription} again"))

    @events_app.command("prune")
    def events_prune(
        days: Annotated[int, typer.Option("--days", min=0, help="Keep events younger than this.")] = 7,
    ) -> None:
        """Delete handled events older than --days; dead letters and pending work stay (interactive terminal only)."""
        require_terminal("prune")
        bus = open_bus()
        try:
            removed = bus.prune(older_than=days * 86400)
            watchers = bus.prune_watchers(older_than=86400)
        finally:
            bus.close()
        typer.echo(f"Deleted {removed} event(s)")
        typer.echo(f"Deleted {watchers} stale watcher subscription(s)")

    @events_app.command("run")
    def events_run(
        until_idle: Annotated[bool, typer.Option("--until-idle", help="Stop when nothing is ready.")] = False,
        max_seconds: Annotated[int, typer.Option("--max-seconds", min=1, help="Stop after this long.")] = 60,
    ) -> None:
        """Attach the event adapter and run handlers for queued events."""
        bus = open_bus()
        try:
            handled = run_adapter(registry, bus, max_seconds=max_seconds, until_idle=until_idle)
        finally:
            bus.close()
        typer.echo(f"Handled {handled} event(s)")

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
