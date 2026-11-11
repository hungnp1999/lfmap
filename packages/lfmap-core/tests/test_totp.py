import base64

import pytest

from lfmap_core import totp

RFC_SECRET = b"12345678901234567890"
VECTORS = [
    (59, "287082"),
    (1111111109, "081804"),
    (1111111111, "050471"),
    (1234567890, "005924"),
    (2000000000, "279037"),
    (20000000000, "353130"),
]


@pytest.mark.parametrize(("now", "code"), VECTORS)
def test_totp_rfc6238_vectors(now, code):
    assert totp.code_at(RFC_SECRET, now) == code
    assert totp.verify(RFC_SECRET, code, now, 0) == now // 30


def test_totp_single_use():
    now = 1111111111
    step = totp.verify(RFC_SECRET, "050471", now, 0)
    assert step is not None
    assert totp.verify(RFC_SECRET, "050471", now, step) is None
    previous = totp.code_at(RFC_SECRET, now - 30)
    assert totp.verify(RFC_SECRET, previous, now, step) is None


def test_totp_window():
    now = 1111111111
    step = now // 30
    assert totp.verify(RFC_SECRET, totp.code_at(RFC_SECRET, now - 30), now, 0) == step - 1
    assert totp.verify(RFC_SECRET, totp.code_at(RFC_SECRET, now - 60), now, 0) is None
    assert totp.verify(RFC_SECRET, totp.code_at(RFC_SECRET, now + 30), now, 0) is None


@pytest.mark.parametrize("typed", ["05047", "0504711", "05047a", "٠٥٠٤٧١", "", "050 47"])
def test_totp_rejects_malformed_codes(typed):
    assert totp.verify(RFC_SECRET, typed, 1111111111, 0) is None


def test_totp_spaces_are_stripped():
    assert totp.verify(RFC_SECRET, " 050 471 ", 1111111111, 0) == 1111111111 // 30


def test_secret_and_uri():
    secret = totp.new_secret()
    assert len(secret) == 20 and secret != totp.new_secret()
    b32 = base64.b32encode(secret).decode()
    assert totp.provisioning_uri(secret) == (
        f"otpauth://totp/LFMAP:owner?secret={b32}&issuer=LFMAP&algorithm=SHA1&digits=6&period=30"
    )
