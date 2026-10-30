"""`lfmap jobs doctor`: read-only checks that the machine can run the jobs in `jobs.toml` (TC-J4).

Only `schtasks /Query`, `powercfg /query`, `whoami /user` and `icacls /save` (into a temporary folder) are run,
through `_run`, and Ollama is only asked for its version.
`ok` is `True` (fine), `None` (warning or unknown) or `False` (a job will not run as expected).
"""

import html
import json
import os
import re
import subprocess
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

from lfmap_core import jobs
from lfmap_core.errors import ToolError
from lfmap_core.registry import Registry

POWER_QUERY = ["powercfg", "/query", "SCHEME_CURRENT", "SUB_SLEEP", "STANDBYIDLE"]
OLLAMA_URL = "http://localhost:11434/api/version"
REGISTER_FIX = "uv run lfmap jobs register"
SIGNED_OUT_FIX = 'Task Scheduler > \\LFMAP\\ > task > General: "Run whether user is logged on or not"'
WAKE_FIX = 'Task Scheduler > \\LFMAP\\ > task > Conditions: "Wake the computer to run this task"'
RUNTIME_FIX = "point [runtime] root in jobs.toml at a clone only you can write (docs/jobs.md), then register"
_HEX = re.compile(r"0x([0-9a-fA-F]+)")
_SID = re.compile(r"S-1-\d+(-\d+)+")

# SDDL abbreviations icacls writes for well-known accounts: SID and a readable name.
_WELL_KNOWN = {
    "SY": ("S-1-5-18", "SYSTEM"),
    "BA": ("S-1-5-32-544", "Administrators"),
    "BU": ("S-1-5-32-545", "Users"),
    "BG": ("S-1-5-32-546", "Guests"),
    "PU": ("S-1-5-32-547", "Power Users"),
    "AU": ("S-1-5-11", "Authenticated Users"),
    "WD": ("S-1-1-0", "Everyone"),
    "IU": ("S-1-5-4", "Interactive"),
    "NU": ("S-1-5-2", "Network"),
    "AN": ("S-1-5-7", "Anonymous"),
    "LS": ("S-1-5-19", "Local Service"),
    "NS": ("S-1-5-20", "Network Service"),
    "CO": ("S-1-3-0", "Creator Owner"),
    "OW": ("S-1-3-4", "Owner Rights"),
    "AC": ("S-1-15-2-1", "All Application Packages"),
}
# Creator Owner only stands for whoever creates a child, which needs a write right of its own.
_TRUSTED = {"S-1-5-18", "S-1-5-32-544", "S-1-3-0"}
_ALLOW = {"A", "XA", "OA", "ZA"}
# Write data or add file, append or add subfolder, delete child, DELETE, WRITE_DAC, WRITE_OWNER, generic all/write.
_WRITE_MASK = 0x2 | 0x4 | 0x40 | 0x10000 | 0x40000 | 0x80000 | 0x10000000 | 0x40000000
# On a folder above the root: anything that lets someone rename it or the folder below it, or change its ACL.
_MOVE_MASK = 0x40 | 0x10000 | 0x40000 | 0x80000 | 0x10000000
# A drive root cannot be renamed, so DELETE on it does not matter (Authenticated Users have it on D:\ by default).
_DRIVE_MOVE_MASK = _MOVE_MASK & ~0x10000
_RIGHTS = {
    "GA": 0x10000000, "GR": 0x80000000, "GW": 0x40000000, "GX": 0x20000000,
    "FA": 0x1F01FF, "FR": 0x120089, "FW": 0x120116, "FX": 0x1200A0,
    "RC": 0x20000, "SD": 0x10000, "WD": 0x40000, "WO": 0x80000,
    "CC": 0x1, "DC": 0x2, "LC": 0x4, "SW": 0x8, "RP": 0x10, "WP": 0x20, "DT": 0x40, "LO": 0x80, "CR": 0x100,
}  # fmt: skip


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


def _check_pwsh(xml: dict[str, str | None]) -> Check:
    try:
        pwsh = jobs.find_pwsh()
    except ToolError as error:
        return Check("pwsh", False, error.message, "winget install Microsoft.PowerShell")
    bare = sorted(i for i, text in xml.items() if text and not _absolute(_tag(text, "Command")))
    if bare:
        detail = f"Task Scheduler cannot start pwsh without a full path: {', '.join(bare)}"
        return Check("pwsh", False, detail, REGISTER_FIX)
    return Check("pwsh", True, str(pwsh))


def _absolute(command: str | None) -> bool:
    return command is None or PureWindowsPath(command.strip('"')).is_absolute()


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
            continue
        try:
            jobs.check_via(registry.get(job.plugin), job)
        except ToolError:
            broken.append(f'{job.id} (via = "event" but {job.plugin} has events = false)')
    if broken:
        detail = "unknown plugin or operation, or events not enabled: " + ", ".join(broken)
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


def _system_tool(name: str) -> str:
    """Absolute path in System32, so a planted `icacls.exe` or `whoami.exe` on PATH is never run."""
    return str(PureWindowsPath(os.environ.get("SystemRoot") or r"C:\Windows", "System32", name))


def _current_sid() -> str:
    """The SID of the account running doctor, from `whoami /user /fo csv /nh`."""
    found = _SID.search(_run([_system_tool("whoami.exe"), "/user", "/fo", "csv", "/nh"]))
    if not found:
        raise ToolError("internal", "whoami did not print a SID")
    return found.group(0)


def _read_acl(root: Path) -> str:
    """The DACL of `root` in SDDL, written by `icacls <root> /save` into a temporary folder."""
    with tempfile.TemporaryDirectory(prefix="lfmap-acl-") as folder:
        saved = Path(folder) / "acl.txt"
        _run([_system_tool("icacls.exe"), str(root), "/save", str(saved)])
        text = saved.read_bytes().decode("utf-16-le", errors="replace")
    found = re.search(r"D:[^\r\n]*", text)
    if not found:
        raise ToolError("internal", "icacls /save wrote no DACL")
    return found.group(0)


def _aces(sddl: str) -> list[list[str]]:
    """Top-level `(type;flags;rights;object;inherited object;sid)` groups; nested conditions stay inside."""
    aces, depth, start = [], 0, 0
    for index, char in enumerate(sddl):
        if char == "(":
            depth += 1
            start = index + 1 if depth == 1 else start
        elif char == ")":
            depth -= 1
            if depth == 0:
                aces.append(sddl[start:index].split(";"))
    if depth != 0 or any(len(ace) < 6 for ace in aces):
        raise ToolError("internal", "icacls /save wrote an ACL that could not be read")
    return aces


def _mask(rights: str) -> int:
    """Access mask of an SDDL rights field; an unknown code counts as write."""
    if rights.lower().startswith("0x"):
        return int(rights, 16)
    codes = [rights[i : i + 2] for i in range(0, len(rights), 2)]
    mask = 0
    for code in codes:
        mask |= _RIGHTS.get(code, _WRITE_MASK)
    return mask


def other_writers(sddl: str, user_sid: str, mask: int = _WRITE_MASK, *, own_only: bool = False) -> list[str]:
    """Accounts other than you, SYSTEM and Administrators with a right in `mask` on the folder or, unless
    `own_only`, on what it inherits to.

    Deny ACEs are ignored, so this may warn about an account that a deny entry actually stops."""
    writers: list[str] = []
    for kind, flags, rights, _object, _inherited, sid, *_ in _aces(sddl):
        sid, name = _WELL_KNOWN.get(sid, (sid, ""))
        inherit_only = "IO" in [flags[i : i + 2] for i in range(0, len(flags), 2)]
        if kind not in _ALLOW or sid in _TRUSTED or sid == user_sid or not _mask(rights) & mask:
            continue
        if own_only and inherit_only:
            continue
        label = f"{name} ({sid})" if name else sid
        if label not in writers:
            writers.append(label)
    return writers


def _runtime_root(path: Path) -> Path | None:
    try:
        return jobs.runtime_root(jobs.load_jobs_file(path))
    except ToolError:
        return None


def _check_runtime_root(root: Path | None, xml: dict[str, str | None]) -> Check:
    if root is None:
        return Check("runtime_root", None, "jobs.toml could not be read")
    if not (root / "scripts" / "Invoke-LfmapJob.ps1").is_file():
        return Check("runtime_root", False, f"{root} has no scripts\\Invoke-LfmapJob.ps1", RUNTIME_FIX)
    expected = f'-RepoPath "{root}"'.lower()
    elsewhere = sorted(
        i for i, text in xml.items() if text and expected not in html.unescape(_tag(text, "Arguments") or "").lower()
    )
    if elsewhere:
        return Check("runtime_root", None, f"tasks not running from {root}: {', '.join(elsewhere)}", REGISTER_FIX)
    return Check("runtime_root", True, str(root))


def _acl_findings(root: Path, user_sid: str) -> list[str]:
    """`<folder>: <accounts>` for the root (any write) and each folder above it (rename, delete child, ACL change),
    since whoever can move a parent can put another tree at the root's path."""
    findings = []
    writers = other_writers(_read_acl(root), user_sid)
    if writers:
        findings.append(f"{root}: {', '.join(writers)}")
    for parent in root.parents:
        mask = _MOVE_MASK if parent.parent != parent else _DRIVE_MOVE_MASK
        movers = other_writers(_read_acl(parent), user_sid, mask, own_only=True)
        if movers:
            findings.append(f"{parent} (can move what is below): {', '.join(movers)}")
    return findings


def _check_runtime_acl(root: Path | None) -> Check:
    if root is None or not root.is_dir():
        return Check("runtime_acl", None, "no runtime root to inspect")
    try:
        findings = _acl_findings(root, _current_sid())
    except ToolError as error:
        return Check("runtime_acl", None, f"ACL of {root} could not be read: {error.message}")
    except OSError as error:
        return Check("runtime_acl", None, f"ACL of {root} could not be read: {error}")
    if findings:
        detail = f"other accounts can change {root}; code they change runs as you: {'; '.join(findings)}"
        return Check("runtime_acl", None, detail, RUNTIME_FIX)
    return Check("runtime_acl", True, f"only you, SYSTEM and Administrators can change {root} or the folders above it")


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
    root = _runtime_root(path)
    return [
        uv,
        _check_pwsh(xml),
        jobs_file,
        _check_tasks(enabled_ids, registered, error),
        _check_logon(xml),
        _check_wake(xml, seconds),
        _check_sleep(seconds, power_error),
        _check_ollama(registry, enabled),
        _check_runtime_root(root, xml),
        _check_runtime_acl(root),
    ]
