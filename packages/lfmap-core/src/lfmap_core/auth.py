"""Owner TOTP enrolment in `%LOCALAPPDATA%\\lfmap\\auth.json` (docs/specs/data-classes.md section 9).

The secret is encrypted with Windows DPAPI for the current user and never written to the audit log, to other
files or into an exception. A missing file means "not enrolled"; an invalid one fails closed.
"""

import base64
import binascii
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from lfmap_core import totp
from lfmap_core.approval import audit
from lfmap_core.config import app_dir
from lfmap_core.errors import ToolError

_WINDOWS = sys.platform == "win32"
MAX_FAILURES = 5
LOCK_SECONDS = 300
CRYPTPROTECT_UI_FORBIDDEN = 0x01


class Protector(Protocol):
    def protect(self, data: bytes) -> bytes: ...

    def unprotect(self, blob: bytes) -> bytes: ...


class DpapiProtector:
    """`CryptProtectData` / `CryptUnprotectData` for the current user, never showing a dialog."""

    def protect(self, data: bytes) -> bytes:
        return self._call(data, protect=True)

    def unprotect(self, blob: bytes) -> bytes:
        return self._call(blob, protect=False)

    @staticmethod
    def _call(data: bytes, protect: bool) -> bytes:  # pragma: no cover - Windows only, checked on the owner's PC
        import ctypes
        from ctypes import wintypes

        class Blob(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.c_void_p)]

        crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        buffer = ctypes.create_string_buffer(data, len(data))
        source, result = Blob(len(data), ctypes.cast(buffer, ctypes.c_void_p)), Blob()
        function = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
        if not function(ctypes.byref(source), None, None, None, None, CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(result)):
            raise OSError("DPAPI call failed")
        try:
            return ctypes.string_at(result.pbData, result.cbData)
        finally:
            kernel32.LocalFree(result.pbData)


def default_protector() -> Protector:
    if not _WINDOWS:
        raise ToolError("backend_unavailable", "TOTP needs Windows DPAPI; the typed code stays in use")
    return DpapiProtector()


def now() -> float:
    return time.time()


def auth_path() -> Path:
    return app_dir() / "auth.json"


def _invalid() -> ToolError:
    return ToolError(
        "permission_denied",
        "auth.json is unreadable or invalid, so the owner code cannot be checked",
        {"hint": "lfmap auth reset"},
    )


def _iso(at: float) -> str:
    return datetime.fromtimestamp(at, UTC).isoformat(timespec="seconds")


def _timestamp(value: Any) -> float:
    return datetime.fromisoformat(value).timestamp()


def _load() -> dict[str, Any] | None:
    try:
        text = auth_path().read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError):
        raise _invalid() from None
    try:
        data = json.loads(text)
        ok = (
            isinstance(data, dict)
            and data.get("version") == 1
            and isinstance(data.get("secret"), str)
            and isinstance(data.get("enrolled_at"), str)
            and all(type(data.get(k)) is int and data[k] >= 0 for k in ("last_step", "failures"))
        )
        if ok:
            base64.b64decode(data["secret"], validate=True)
            if data.get("locked_until") is not None:
                _timestamp(data["locked_until"])
    except (ValueError, TypeError, binascii.Error):
        ok = False
    if not ok:
        raise _invalid()
    return data


def _write(data: dict[str, Any]) -> None:
    path = auth_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(data, file, indent=2)
        file.flush()
        os.fsync(file.fileno())
    os.replace(tmp, path)


def _secret(data: dict[str, Any], protector: Protector | None) -> bytes:
    try:
        secret = (protector or default_protector()).unprotect(base64.b64decode(data["secret"], validate=True))
    except ToolError:
        raise
    except (OSError, ValueError, binascii.Error):
        raise _invalid() from None
    if len(secret) != totp.SECRET_BYTES:
        raise _invalid()
    return secret


def enrolled() -> bool:
    return _load() is not None


def status(at: float | None = None) -> dict[str, Any]:
    at = now() if at is None else at
    data = _load()
    if data is None:
        return {"enrolled": False}
    until = _timestamp(data["locked_until"]) if data["locked_until"] else 0.0
    return {"enrolled": True, "enrolled_at": data["enrolled_at"], "locked": until > at}


def enroll(secret: bytes, code: str, protector: Protector | None = None, at: float | None = None) -> None:
    """Store `secret` only once `code` proves the app has it; the confirming step counts as used."""
    at = now() if at is None else at
    step = totp.verify(secret, code, at, 0)
    if step is None:
        raise ToolError("permission_denied", "The code did not match; nothing was stored")
    blob = (protector or default_protector()).protect(secret)
    _write(
        {
            "version": 1,
            "secret": base64.b64encode(blob).decode("ascii"),
            "enrolled_at": _iso(at),
            "last_step": step,
            "failures": 0,
            "locked_until": None,
        }
    )


def check(code: str, protector: Protector | None = None, at: float | None = None) -> None:
    """Return when `code` is a fresh valid code; raise `permission_denied` otherwise."""
    at = now() if at is None else at
    data = _load()
    if data is None:
        raise ToolError("not_found", "No authenticator is enrolled")
    if data["locked_until"] and _timestamp(data["locked_until"]) > at:
        raise ToolError("permission_denied", "Too many wrong codes: authenticator locked for a few minutes")
    if data["locked_until"]:
        data.update(locked_until=None, failures=0)
    step = totp.verify(_secret(data, protector), code, at, data["last_step"])
    if step is not None:
        data.update(last_step=step, failures=0)
        _write(data)  # before returning, so a crash cannot allow a replay
        return
    data["failures"] += 1
    locked = data["failures"] >= MAX_FAILURES
    if locked:
        data.update(failures=0, locked_until=_iso(at + LOCK_SECONDS))
    _write(data)
    if locked:
        audit({"channel": "cli", "decision": "deny", "reason": "auth locked"})
    raise ToolError(
        "permission_denied", "Too many wrong codes: locked for 5 minutes" if locked else "The code was not accepted"
    )


def reset() -> bool:
    try:
        auth_path().unlink()
    except FileNotFoundError:
        return False
    return True
