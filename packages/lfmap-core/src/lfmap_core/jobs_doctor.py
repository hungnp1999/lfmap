"""`lfmap jobs doctor`: read-only checks that the machine can run the jobs in `jobs.toml` (TC-J4).

Only `schtasks /Query` and `powercfg /query` are run, through `_run`, and Ollama is only asked for its version.
`ok` is `True` (fine), `None` (warning or unknown) or `False` (a job will not run as expected).
"""

import json
import re
import subprocess
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from lfmap_core import jobs
from lfmap_core.errors import ToolError
from lfmap_core.registry import Registry

POWER_QUERY = ["powercfg", "/query", "SCHEME_CURRENT", "SUB_SLEEP", "STANDBYIDLE"]
OLLAMA_URL = "http://localhost:11434/api/version"
REGISTER_FIX = "uv run lfmap jobs register"
SIGNED_OUT_FIX = 'Task Scheduler > \\LFMAP\\ > task > General: "Run whether user is logged on or not"'
WAKE_FIX = 'Task Scheduler > \\LFMAP\\ > task > Conditions: "Wake the computer to run this task"'
_HEX = re.compile(r"0x([0-9a-fA-F]+)")


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool | None
    detail: str
    fix: str = ""


def _run(args: list[str]) -> str:
    try:
        result = subprocess.run(args, capture_output=True, text=True, errors="replace", check=False)
    except FileNotFoundError as error:
        raise ToolError("backend_unavailable", f"{args[0]} was not found (Windows only)") from error
    if result.returncode != 0:
        details = {"command": subprocess.list2cmdline(args), "stderr": result.stderr.strip()}
        raise ToolError("internal", f"{args[0]} exited with {result.returncode}", details)
    return result.stdout


def _http_get(url: str, timeout: float) -> str:
    with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - fixed loopback URL
        return response.read().decode("utf-8", errors="replace")


def _check_uv() -> Check:
    try:
        return Check("uv", True, str(jobs.find_uv()))
    except ToolError as error:
        return Check("uv", False, error.message, "winget install astral-sh.uv")


def _load(registry: Registry, path: Path) -> tuple[Check, list[jobs.Job] | None]:
    if not path.is_file():
        return Check("jobs_file", None, f"{path} does not exist; no jobs", "see docs/jobs.md"), []
    try:
        job_list = jobs.load_jobs(path)
    except ToolError as error:
        detail = f"{error.message}: {error.details.get('error', '')}".strip()
        return Check("jobs_file", False, detail, f"fix {path} (see docs/jobs.md)"), None
    broken = []
    for job in job_list:
        try:
            known = registry.get(job.plugin).manifest.operation(job.operation) is not None
        except ToolError:
            known = False
        if not known:
            broken.append(f"{job.id} ({job.plugin}.{job.operation})")
    if broken:
        detail = "unknown plugin or operation: " + ", ".join(broken)
        return Check("jobs_file", False, detail, "fix the jobs or install the plugin"), job_list
    return Check("jobs_file", True, f"{path}: {len(job_list)} job(s)"), job_list


def _check_tasks(enabled: set[str] | None, registered: set[str] | None, error: str) -> Check:
    if registered is None:
        return Check("tasks", None, error)
    if enabled is None:
        return Check("tasks", None, "jobs.toml could not be read")
    missing, stale = sorted(enabled - registered), sorted(registered - enabled)
    if missing or stale:
        parts = {"missing": missing, "disabled or gone": stale}
        detail = "; ".join(f"{label}: {', '.join(ids)}" for label, ids in parts.items() if ids)
        return Check("tasks", False, detail, REGISTER_FIX)
    if not enabled:
        return Check("tasks", None, "no enabled job and no task")
    return Check("tasks", True, f"{len(enabled)} task(s) in \\LFMAP\\")


def _task_xml(job_ids: list[str]) -> dict[str, str | None]:
    """Task XML by job id; `None` when it could not be read."""
    found: dict[str, str | None] = {}
    for job_id in job_ids:
        try:
            found[job_id] = _run(["schtasks", "/Query", "/TN", jobs.TASK_FOLDER + job_id, "/XML"])
        except ToolError:
            found[job_id] = None
    return found


def _tag(xml: str, tag: str) -> str | None:
    match = re.search(rf"<{tag}>\s*([^<]*?)\s*</{tag}>", xml)
    return match.group(1) if match else None


def _check_logon(xml: dict[str, str | None]) -> Check:
    if not xml:
        return Check("logon_mode", None, "no task to inspect")
    unknown = sorted(i for i, text in xml.items() if text is None or _tag(text, "LogonType") is None)
    interactive = sorted(i for i, text in xml.items() if text and _tag(text, "LogonType") == "InteractiveToken")
    if interactive:
        detail = f"runs only while you are logged on: {', '.join(interactive)}"
        return Check("logon_mode", None, detail, SIGNED_OUT_FIX)
    if unknown:
        return Check("logon_mode", None, f"logon type unknown: {', '.join(unknown)}")
    return Check("logon_mode", True, "every task runs whether you are logged on or not")


def _sleep_seconds() -> tuple[int | None, str]:
    """Sleep-after on AC power in seconds: the second-last hex value, so any Windows language works."""
    try:
        values = _HEX.findall(_run(POWER_QUERY))
    except ToolError as error:
        return None, error.message
    if len(values) < 2:
        return None, "powercfg output could not be read"
    return int(values[-2], 16), ""


def _check_sleep(seconds: int | None, error: str) -> Check:
    if seconds is None:
        return Check("sleep", None, error)
    if seconds == 0:
        return Check("sleep", True, "never sleeps on AC power")
    return Check("sleep", None, f"sleeps after {seconds // 60} min on AC power", "fine if every task wakes the machine")


def _check_wake(xml: dict[str, str | None], seconds: int | None) -> Check:
    if seconds == 0:
        return Check("wake", True, "the machine never sleeps on AC power")
    if not xml:
        return Check("wake", None, "no task to inspect")
    asleep = sorted(i for i, text in xml.items() if not (text and _tag(text, "WakeToRun") == "true"))
    if not asleep:
        return Check("wake", True, "every task wakes the machine")
    detail = f"no WakeToRun: {', '.join(asleep)}"
    if seconds is None:
        return Check("wake", None, detail + " (sleep setting unknown)", WAKE_FIX)
    return Check("wake", False, detail, WAKE_FIX + ", or powercfg /change standby-timeout-ac 0")


def _check_ollama(registry: Registry, enabled: list[jobs.Job]) -> Check:
    def uses_network(job: jobs.Job) -> bool:
        try:
            return registry.get(job.plugin).manifest.permissions.network
        except ToolError:
            return False

    if not any(uses_network(job) for job in enabled):
        return Check("ollama", None, "no enabled job uses a plugin with network access")
    try:
        body = _http_get(OLLAMA_URL, timeout=2)
    except OSError as error:
        return Check("ollama", False, f"{OLLAMA_URL}: {error}", "start Ollama")
    try:
        version = json.loads(body).get("version", "?")
    except (ValueError, AttributeError):
        version = "?"
    return Check("ollama", True, f"version {version}")


def run_checks(registry: Registry, path: Path | None = None) -> list[Check]:
    path = path or jobs.jobs_path()
    uv = _check_uv()
    jobs_file, job_list = _load(registry, path)
    enabled = [job for job in job_list or [] if job.enabled]
    enabled_ids = None if job_list is None else {job.id for job in enabled}
    try:
        registered, error = jobs.registered_tasks(_run(jobs.QUERY)), ""
    except ToolError as failure:
        registered, error = None, failure.message
    xml = _task_xml(sorted((enabled_ids or set()) & (registered or set())))
    seconds, power_error = _sleep_seconds()
    return [
        uv,
        jobs_file,
        _check_tasks(enabled_ids, registered, error),
        _check_logon(xml),
        _check_wake(xml, seconds),
        _check_sleep(seconds, power_error),
        _check_ollama(registry, enabled),
    ]
