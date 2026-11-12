"""RFC 6238 time-based one-time passwords (HMAC-SHA-1, 30 s step, 6 digits). Pure: no files, no clock."""

import base64
import hashlib
import hmac
import secrets
import struct

STEP_SECONDS = 30
DIGITS = 6
SECRET_BYTES = 20


def new_secret() -> bytes:
    return secrets.token_bytes(SECRET_BYTES)


def provisioning_uri(secret: bytes, account: str = "owner", issuer: str = "LFMAP") -> str:
    b32 = base64.b32encode(secret).decode("ascii")
    return (
        f"otpauth://totp/{issuer}:{account}?secret={b32}&issuer={issuer}"
        f"&algorithm=SHA1&digits={DIGITS}&period={STEP_SECONDS}"
    )


def _hotp(secret: bytes, counter: int) -> str:
    mac = hmac.new(secret, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    value = struct.unpack(">I", mac[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{value % 10**DIGITS:0{DIGITS}d}"


def code_at(secret: bytes, now: float) -> str:
    return _hotp(secret, int(now) // STEP_SECONDS)


def verify(secret: bytes, code: str, now: float, last_step: int) -> int | None:
    """The step `code` belongs to, or None. Accepts the current and the previous step, never one `<= last_step`."""
    typed = code.replace(" ", "")
    if len(typed) != DIGITS or not typed.isascii() or not typed.isdigit():
        return None
    current = int(now) // STEP_SECONDS
    accepted: int | None = None
    for step in (current - 1, current):  # both are always compared, so timing does not show which matched
        if hmac.compare_digest(_hotp(secret, step), typed) and step > last_step:
            accepted = step
    return accepted
