import base64
import json
import re

import pytest

from lfmap_core import auth, totp
from lfmap_core.approval import audit_path
from lfmap_core.errors import ToolError

SECRET = b"12345678901234567890"
T0 = 1_000_000.0


class FakeProtector:
    def protect(self, data: bytes) -> bytes:
        return b"FAKE" + data[::-1]

    def unprotect(self, blob: bytes) -> bytes:
        if not blob.startswith(b"FAKE"):
            raise OSError("not ours")
        return blob[4:][::-1]


@pytest.fixture
def protector(monkeypatch):
    fake = FakeProtector()
    monkeypatch.setattr(auth, "default_protector", lambda: fake)
    return fake


@pytest.fixture
def enrolled(protector):
    auth.enroll(SECRET, totp.code_at(SECRET, T0), protector, at=T0)


def audit_text() -> str:
    return audit_path().read_text(encoding="utf-8") if audit_path().exists() else ""


def test_not_enrolled_without_a_file(protector):
    assert auth.enrolled() is False
    assert auth.status()["enrolled"] is False


def test_enroll_stores_a_protected_secret_and_the_confirming_step(enrolled):
    data = json.loads(auth.auth_path().read_text(encoding="utf-8"))
    assert data["version"] == 1 and data["failures"] == 0 and data["locked_until"] is None
    assert data["last_step"] == int(T0) // 30
    assert base64.b64decode(data["secret"]) == FakeProtector().protect(SECRET)
    assert SECRET.decode() not in json.dumps(data)


def test_enroll_with_a_wrong_code_stores_nothing(protector):
    with pytest.raises(ToolError) as error:
        auth.enroll(SECRET, "000000", protector, at=T0)
    assert error.value.code == "permission_denied"
    assert not auth.auth_path().exists()


def test_check_accepts_once(enrolled):
    code = totp.code_at(SECRET, T0 + 60)
    auth.check(code, at=T0 + 60)
    with pytest.raises(ToolError):
        auth.check(code, at=T0 + 61)
    assert json.loads(auth.auth_path().read_text(encoding="utf-8"))["last_step"] == int(T0 + 60) // 30


def test_last_step_is_written_before_check_returns(enrolled, monkeypatch):
    seen = {}
    real = auth.os.replace

    def spy(src, dst):
        real(src, dst)
        seen["last_step"] = json.loads(auth.auth_path().read_text(encoding="utf-8"))["last_step"]

    monkeypatch.setattr(auth.os, "replace", spy)
    auth.check(totp.code_at(SECRET, T0 + 90), at=T0 + 90)
    assert seen["last_step"] == int(T0 + 90) // 30


def test_auth_lockout(enrolled):
    for i in range(5):
        with pytest.raises(ToolError) as error:
            auth.check("000000", at=T0 + 60 + i)
        assert error.value.code == "permission_denied"
    assert audit_text().count("auth locked") == 1
    good = totp.code_at(SECRET, T0 + 120)
    with pytest.raises(ToolError) as locked:
        auth.check(good, at=T0 + 120)
    assert "locked" in locked.value.message
    assert audit_text().count("auth locked") == 1
    later = T0 + 60 + 4 + 301
    auth.check(totp.code_at(SECRET, later), at=later)
    assert auth.status(later)["locked"] is False


def test_failures_below_five_do_not_lock(enrolled):
    for _ in range(4):
        with pytest.raises(ToolError):
            auth.check("000000", at=T0 + 60)
    auth.check(totp.code_at(SECRET, T0 + 60), at=T0 + 60)
    assert json.loads(auth.auth_path().read_text(encoding="utf-8"))["failures"] == 0


@pytest.mark.parametrize(
    "content",
    [
        "{not json",
        "[]",
        '{"version": 2}',
        '{"version": 1, "secret": "!!", "enrolled_at": "x", "last_step": 0, "failures": 0, "locked_until": null}',
        '{"version": 1, "secret": "AAAA", "enrolled_at": "x", "last_step": "0", "failures": 0, "locked_until": null}',
        "",
    ],
)
def test_auth_corrupt_fails_closed(protector, content):
    auth.auth_path().parent.mkdir(parents=True, exist_ok=True)
    auth.auth_path().write_text(content, encoding="utf-8")
    for call in (auth.enrolled, auth.status, lambda: auth.check("123456", at=T0)):
        with pytest.raises(ToolError) as error:
            call()
        assert error.value.code == "permission_denied"
        assert error.value.details["hint"] == "lfmap auth reset"
    assert auth.reset() is True
    assert auth.enrolled() is False


def test_auth_wrong_secret_length_fails_closed_on_check(protector):
    auth.auth_path().parent.mkdir(parents=True, exist_ok=True)
    auth.auth_path().write_text(
        '{"version": 1, "secret": "RkFLRQ==", "enrolled_at": "x", "last_step": 0, "failures": 0, "locked_until": null}',
        encoding="utf-8",
    )
    with pytest.raises(ToolError) as error:
        auth.check("123456", at=T0)
    assert error.value.code == "permission_denied" and error.value.details["hint"] == "lfmap auth reset"


def test_auth_never_logged(protector, monkeypatch, capsys):
    from typer.testing import CliRunner

    from lfmap_core import cli
    from lfmap_core.registry import Registry

    monkeypatch.setattr(cli, "_interactive", lambda: True)
    monkeypatch.setattr(auth, "now", lambda: T0)
    monkeypatch.setattr(totp, "new_secret", lambda: SECRET)
    b32 = base64.b32encode(SECRET).decode()
    runner = CliRunner()
    app = cli.build_app(Registry())
    result = runner.invoke(app, ["auth", "enroll"], input=totp.code_at(SECRET, T0) + "\n")
    assert result.exit_code == 0, result.output
    assert result.output.count("otpauth://") == 1 and result.output.count(b32) == 2  # the URI and the plain secret
    status = runner.invoke(app, ["auth", "status"])
    assert b32 not in status.output and "otpauth" not in status.output
    with pytest.raises(ToolError) as error:
        auth.check("000000", at=T0 + 60)
    assert b32 not in str(error.value) and b32 not in json.dumps(error.value.to_dict())
    text = audit_text()
    assert b32 not in text and "otpauth" not in text and not re.search(r"secret", text, re.IGNORECASE)
    assert "enrol" in text


def test_reset_removes_the_file(enrolled):
    assert auth.reset() is True and not auth.auth_path().exists()
    assert auth.reset() is False


def test_default_protector_refuses_off_windows(monkeypatch):
    monkeypatch.setattr(auth, "_WINDOWS", False)
    with pytest.raises(ToolError) as error:
        auth.default_protector()
    assert error.value.code == "backend_unavailable"
