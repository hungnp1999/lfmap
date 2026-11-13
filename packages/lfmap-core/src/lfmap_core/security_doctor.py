"""Read-only Windows Security checks for `lfmap doctor` (#198).

One fixed PowerShell script (no user data in it) runs from System32 with a timeout; it only reads Defender status,
preferences and the registered antivirus products. Every finding is a warning (`ok` is `True` or `None`), never a
failure, so the exit code of `lfmap doctor` does not depend on this group. Outside Windows `run_checks` returns
`None` (skipped).
"""

import json
import ntpath
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath
from typing import Any

from lfmap_core import config as config_module
from lfmap_core.errors import ToolError
from lfmap_core.jobs_doctor import Check, _system_tool

TIMEOUT_SECONDS = 20
MAX_ERROR = 200
SCRIPT = (
    "$ErrorActionPreference = 'Stop'; $r = @{Status = $null; Preference = $null; Products = $null; Errors = @{}}; "
    "try { $r.Status = Get-MpComputerStatus | Select-Object RealTimeProtectionEnabled, AMServiceEnabled } "
    "catch { $r.Errors.Status = $_.Exception.Message }; "
    "try { $r.Preference = Get-MpPreference | "
    "Select-Object EnableControlledFolderAccess, ControlledFolderAccessProtectedFolders } "
    "catch { $r.Errors.Preference = $_.Exception.Message }; "
    "try { $r.Products = @(Get-CimInstance -Namespace root/SecurityCenter2 -ClassName AntiVirusProduct | "
    "Select-Object displayName, productState) } catch { $r.Errors.Products = $_.Exception.Message }; "
    "$r | ConvertTo-Json -Depth 4 -Compress"
)
# Assumption (not checked against Microsoft documentation): a product is on when the 0xF000 nibble of its
# `productState` is 1. Inferred from real values: ESET 0x41000 (on) and Windows Defender 0x62100 (not on).
PRODUCT_STATE_MASK = 0xF000
PRODUCT_STATE_ON = 0x1000
NO_DEFENDER_SERVICE = "0x800106ba"
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
    am_service: bool | None = None
    products: tuple[tuple[str, int], ...] | None = None
    errors: dict[str, str] = field(default_factory=dict)


def _first_line(value: object) -> str:
    return value.strip().partition("\n")[0].strip()[:MAX_ERROR] if isinstance(value, str) else ""


def _products(value: object) -> tuple[tuple[str, int], ...] | None:
    if value is None:
        return None
    items = [value] if isinstance(value, dict) else value if isinstance(value, list) else []
    pairs = [(i.get("displayName"), i.get("productState")) for i in items if isinstance(i, dict)]
    return tuple((n, s) for n, s in pairs if isinstance(n, str) and isinstance(s, int) and not isinstance(s, bool))


def _flag(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def parse_status(text: str) -> Status:
    """Read the script's JSON; a missing or failed part is `None`. Raises `ValueError` for any other shape."""
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("the PowerShell output is not a JSON object")
    status, preference = data.get("Status") or {}, data.get("Preference") or {}
    cfa = preference.get("EnableControlledFolderAccess")
    listed = preference.get("ControlledFolderAccessProtectedFolders") or []
    listed = [listed] if isinstance(listed, str) else listed
    raw = data.get("Errors") if isinstance(data.get("Errors"), dict) else {}
    return Status(
        _flag(status.get("RealTimeProtectionEnabled")),
        cfa if isinstance(cfa, int) and not isinstance(cfa, bool) else None,
        tuple(item for item in listed if isinstance(item, str)),
        _flag(status.get("AMServiceEnabled")),
        _products(data.get("Products")),
        {key: line for key, value in raw.items() if (line := _first_line(value))},
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


def active_antivirus(status: Status) -> list[str]:
    """Names of products other than Defender whose `productState` says they are on."""
    return [
        name
        for name, state in status.products or ()
        if state & PRODUCT_STATE_MASK == PRODUCT_STATE_ON and "defender" not in name.casefold()
    ]


def _defender(status: Status) -> Check:
    name = _NAMES[0]
    if status.realtime:
        return Check(name, True, "Defender real-time protection is on")
    if status.realtime is None:
        error = status.errors.get("Status")
        return Check(
            name, None, f"unknown: {error}" if error else "real-time protection could not be read", DEFENDER_FIX
        )
    if others := active_antivirus(status):
        return Check(name, True, f"Defender real-time is off; {', '.join(others)} is the active antivirus")
    detail = "Defender real-time protection is off (may be intended when another antivirus is installed)"
    return Check(name, None, detail, DEFENDER_FIX)


def _cfa(status: Status) -> Check:
    name, error = _NAMES[1], status.errors.get("Preference")
    if status.cfa == 1:
        return Check(name, True, "Controlled folder access is on")
    if status.cfa is None and error:
        if status.am_service is False or NO_DEFENDER_SERVICE in error.casefold():
            detail = "n/a: Defender is not the active antivirus, Controlled folder access is a Defender feature"
            return Check(name, None, detail)
        return Check(name, None, f"unknown: {error}", CFA_FIX)
    if status.cfa is None:
        return Check(name, None, "Controlled folder access could not be read", CFA_FIX)
    state = _CFA_STATES.get(status.cfa, "unknown")
    return Check(name, None, f"Controlled folder access is {state} ({status.cfa})", CFA_FIX)


def evaluate(status: Status, folders: list[str], profile: str) -> list[Check]:
    defender, cfa = _defender(status), _cfa(status)
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
        reason = _first_line(f"unknown: {type(error).__name__}: {error}")
        return [Check(name, None, reason, "run `Get-MpComputerStatus` in PowerShell to see why") for name in _NAMES]
    found = _config_folders() if folders is None else folders
    return evaluate(status, found, profile or os.environ.get("USERPROFILE") or str(Path.home()))
