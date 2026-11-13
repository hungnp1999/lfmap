"""Read-only Windows Security checks for `lfmap doctor` (#198).

One fixed PowerShell script (no user data in it) runs from System32 with a timeout; it only reads Defender status
and preferences. Every finding is a warning (`ok` is `True` or `None`), never a failure, so the exit code of
`lfmap doctor` does not depend on this group. Outside Windows `run_checks` returns `None` (skipped).
"""

import json
import ntpath
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any

from lfmap_core import config as config_module
from lfmap_core.errors import ToolError
from lfmap_core.jobs_doctor import Check, _system_tool

TIMEOUT_SECONDS = 20
SCRIPT = (
    "$ErrorActionPreference = 'Stop'; "
    "[pscustomobject]@{"
    "Status = (Get-MpComputerStatus | Select-Object RealTimeProtectionEnabled); "
    "Preference = (Get-MpPreference | "
    "Select-Object EnableControlledFolderAccess, ControlledFolderAccessProtectedFolders)"
    "} | ConvertTo-Json -Depth 4 -Compress"
)
DEFENDER_FIX = "Windows Security > Virus & threat protection > Manage settings"
CFA_FIX = "Windows Security > Ransomware protection > Controlled folder access"
PROTECTED_FIX = "Windows Security > Ransomware protection > Controlled folder access > Protected folders"
DEFAULT_PROTECTED = ("Documents", "Pictures", "Videos", "Music", "Favorites", "Desktop")
_CFA_STATES = {0: "off", 2: "audit only", 3: "blocks disk sector writes only", 4: "audit of disk sector writes only"}
_NAMES = ("defender_realtime", "cfa_enabled", "cfa_covers")


@dataclass(frozen=True)
class Status:
    realtime: bool | None
    cfa: int | None
    protected: tuple[str, ...]


def parse_status(text: str) -> Status:
    """Read the script's JSON; a missing field is `None`. Raises `ValueError` when it is not the expected JSON."""
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("the PowerShell output is not a JSON object")
    status, preference = data.get("Status") or {}, data.get("Preference") or {}
    realtime = status.get("RealTimeProtectionEnabled")
    cfa = preference.get("EnableControlledFolderAccess")
    listed = preference.get("ControlledFolderAccessProtectedFolders") or []
    listed = [listed] if isinstance(listed, str) else listed
    return Status(
        realtime if isinstance(realtime, bool) else None,
        cfa if isinstance(cfa, int) and not isinstance(cfa, bool) else None,
        tuple(item for item in listed if isinstance(item, str)),
    )


def default_protected(profile: str) -> list[str]:
    return [ntpath.join(profile, name) for name in DEFAULT_PROTECTED]


def _parts(folder: str) -> tuple[str, ...]:
    return tuple(part.casefold() for part in PureWindowsPath(ntpath.normpath(folder)).parts)


def covered(folder: str, protected: list[str]) -> bool:
    """True when `folder` is, or is inside, one of `protected`; compared by path components, not string prefix."""
    parts = _parts(folder)
    return any(parts[: len(base)] == base for base in map(_parts, protected) if base)


def declared_folders(config: dict[str, Any], app_dir: str) -> list[str]:
    """Folders from `[paths]` and `[backup] folder` (raw strings), then the app folder; anything else is skipped."""
    found: list[str] = []
    for value in (config.get("paths") or {}).values():
        values = [value] if isinstance(value, str) else value if isinstance(value, list) else []
        found += [item for item in values if isinstance(item, str)]
    backup = (config.get("backup") or {}).get("folder")
    return found + ([backup] if isinstance(backup, str) else []) + [app_dir]


def evaluate(status: Status, folders: list[str], profile: str) -> list[Check]:
    if status.realtime:
        defender = Check(_NAMES[0], True, "Defender real-time protection is on")
    elif status.realtime is None:
        defender = Check(_NAMES[0], None, "real-time protection could not be read", DEFENDER_FIX)
    else:
        detail = "Defender real-time protection is off (may be intended when another antivirus is installed)"
        defender = Check(_NAMES[0], None, detail, DEFENDER_FIX)
    if status.cfa == 1:
        cfa = Check(_NAMES[1], True, "Controlled folder access is on")
    elif status.cfa is None:
        cfa = Check(_NAMES[1], None, "Controlled folder access could not be read", CFA_FIX)
    else:
        state = _CFA_STATES.get(status.cfa, "unknown")
        cfa = Check(_NAMES[1], None, f"Controlled folder access is {state} ({status.cfa})", CFA_FIX)
    if status.cfa != 1:
        return [defender, cfa, Check(_NAMES[2], None, "n/a: Controlled folder access is not on")]
    protected = [*status.protected, *default_protected(profile)]
    missing = [folder for folder in folders if not covered(folder, protected)]
    if missing:
        return [defender, cfa, Check(_NAMES[2], None, "not covered: " + ", ".join(missing), PROTECTED_FIX)]
    return [defender, cfa, Check(_NAMES[2], True, f"{len(folders)} declared folder(s) covered")]


def _run_powershell(command: list[str]) -> str:
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
        timeout=TIMEOUT_SECONDS,
        stdin=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, command[0], result.stdout, result.stderr)
    return result.stdout


def _config_folders() -> list[str]:
    app = str(config_module.app_dir())
    try:
        return declared_folders(config_module.load_config(), app)
    except ToolError:
        return [app]


def run_checks(
    runner: Callable[[list[str]], str] = _run_powershell,
    folders: list[str] | None = None,
    profile: str | None = None,
    platform: str = sys.platform,
) -> list[Check] | None:
    """The security checks, or `None` when not on Windows. `runner` takes the full command line."""
    if platform != "win32":
        return None
    command = [
        _system_tool(r"WindowsPowerShell\v1.0\powershell.exe"),
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        SCRIPT,
    ]
    try:
        status = parse_status(runner(command))
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        reason = f"unknown: {type(error).__name__}: {error}"
        return [Check(name, None, reason, "run `Get-MpComputerStatus` in PowerShell to see why") for name in _NAMES]
    found = _config_folders() if folders is None else folders
    return evaluate(status, found, profile or os.environ.get("USERPROFILE") or str(Path.home()))
