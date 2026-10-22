import os
import secrets
import shutil
import tempfile
from pathlib import Path

from lfmap_core import Tool, ToolError, operation
from lfmap_core.approval import audit
from lfmap_core.permissions import _is_remote
from lfmap_powershell import runner
from lfmap_powershell.allowlist import ParamSpec, ScriptEntry, build_args, load_allowlist, sha256_hex
from lfmap_powershell.schemas import ListInput, ListOutput, ParamInfo, RunInput, RunOutput, ScriptInfo

PWSH_FLAGS = ["-NoProfile", "-NonInteractive", "-NoLogo", "-File"]
_SCRIPT_INDEX = len(PWSH_FLAGS) + 1


def pwsh_path(settings: dict) -> str:
    """`settings.pwsh` (an absolute local file) or `pwsh` on PATH."""
    value = settings.get("pwsh")
    if value is None:
        found = shutil.which("pwsh")
        if not found:
            raise ToolError("backend_unavailable", "PowerShell 7 (pwsh) was not found on PATH")
        return found
    # String checks first: never touch a network or device path (NTLM leak).
    if not isinstance(value, str) or _is_remote(value) or not os.path.isabs(value):
        raise ToolError("invalid_input", "settings.pwsh must be an absolute local path", {"pwsh": str(value)})
    if not os.path.isfile(value):
        raise ToolError("invalid_input", "settings.pwsh does not exist", {"pwsh": value})
    return value


def _param_info(name: str, spec: ParamSpec) -> ParamInfo:
    return ParamInfo(
        name=name,
        type=spec.type,
        required=spec.required,
        pattern=spec.pattern,
        min=spec.min if spec.type == "int" else None,
        max=spec.max if spec.type == "int" else None,
        choices=list(spec.choices),
    )


class PowerShellTool(Tool):
    def _checked(self, entry: ScriptEntry) -> tuple[Path, bytes]:
        """The script's resolved path and bytes, after the root and hash checks."""
        path = self.ctx.permissions.require_read(entry.path)
        try:
            data = path.read_bytes()
        except OSError as error:
            raise ToolError("not_found", "Script cannot be read", {"path": entry.path, "error": str(error)}) from error
        actual = sha256_hex(data)
        if actual != entry.sha256:
            raise ToolError(
                "permission_denied",
                "Script sha256 does not match the allow-list",
                {"path": entry.path, "expected": entry.sha256, "actual": actual},
            )
        return path, data

    def _info(self, script_id: str, entry: ScriptEntry) -> ScriptInfo:
        try:
            self._checked(entry)
            problem = ""
        except ToolError as error:
            problem = error.message
        return ScriptInfo(
            id=script_id,
            description=entry.description,
            path=entry.path,
            timeout_s=entry.timeout_s,
            params=[_param_info(name, spec) for name, spec in entry.params.items()],
            ready=not problem,
            problem=problem,
        )

    def health(self) -> dict:
        try:
            return {"ok": True, "pwsh": pwsh_path(self.ctx.settings)}
        except ToolError as error:
            return {"ok": False, "pwsh": "", "error": error.message}

    @operation("list")
    def list_scripts(self, inp: ListInput) -> ListOutput:
        """List the allow-listed PowerShell scripts, their parameters and whether each can run now."""
        entries, problems = load_allowlist(self.ctx.settings)
        scripts = [
            self._info(script_id, entries[script_id])
            if script_id in entries
            else ScriptInfo(id=script_id, ready=False, problem=problems[script_id])
            for script_id in sorted(entries.keys() | problems.keys())
        ]
        return ListOutput(scripts=scripts)

    def _execute(self, script_id: str, entry: ScriptEntry, path: Path, data: bytes, command: list[str]) -> RunOutput:
        """Run a fresh copy of the checked bytes, so the file cannot change between check and start."""
        base = self.ctx.temp_dir
        if base is not None:
            base.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base, prefix="run-", ignore_cleanup_errors=True) as work:
            copy = Path(work) / f"{script_id}-{secrets.token_hex(4)}.ps1"
            with open(copy, "xb") as stream:
                stream.write(data)
            result = runner.run_process(
                [*command[:_SCRIPT_INDEX], str(copy), *command[_SCRIPT_INDEX + 1 :]],
                path.parent,
                entry.timeout_s,
                entry.max_output_chars,
            )
        audit(
            {
                "channel": self.ctx.channel,
                "plugin": self.ctx.plugin_id,
                "operation": "run",
                "tier": "T3",
                "decision": "allow",
                "reason": "timeout" if result.timed_out else f"exit {result.exit_code}",
                "target": script_id,
            }
        )
        return RunOutput(
            script=script_id,
            dry_run=False,
            command=command,
            exit_code=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
            stdout_truncated=result.stdout_truncated,
            stderr_truncated=result.stderr_truncated,
            timed_out=result.timed_out,
            duration_ms=result.duration_ms,
        )

    @operation("run")
    def run(self, inp: RunInput) -> RunOutput:
        """Run an allow-listed PowerShell 7 script with checked parameters; returns its exit code and output."""
        entries, problems = load_allowlist(self.ctx.settings)
        if inp.script in problems:
            raise ToolError(
                "invalid_input",
                "Script entry in the allow-list is invalid",
                {"script": inp.script, "problem": problems[inp.script]},
            )
        entry = entries.get(inp.script)
        if entry is None:
            raise ToolError(
                "not_found", "Script is not allow-listed", {"script": inp.script, "allowed": sorted(entries)}
            )
        args = build_args(entry.params, inp.params)
        path, data = self._checked(entry)
        command = [pwsh_path(self.ctx.settings), *PWSH_FLAGS, str(path), *args]
        if self.ctx.dry_run:
            return RunOutput(script=inp.script, dry_run=True, command=command)
        return self._execute(inp.script, entry, path, data, command)
