"""`WebFetcher`: gzip and deflate pages, bounded decompression, refused encodings (web-plugin spec s. 4, 5, 11)."""

import gzip
import importlib.util
import sys
import time
import tracemalloc
import zlib
from pathlib import Path

import pytest

from lfmap_core import ToolError


def _harness():  # noqa: ANN202
    name = "lfmap_web_test_harness"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, Path(__file__).parent / "fixtures" / "web" / "harness.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


h = _harness()
server = h.server
guard = h.guard

MIB = 1_048_576
GIB = 1_073_741_824
PAGE = "<html><body>Dau thau 2026: goi thau so 1, Ha Noi.</body></html>"
PAGE_BYTES = 63
HTML = (("Content-Type", "text/html; charset=utf-8"),)


def _raw_deflate(data: bytes) -> bytes:
    compressor = zlib.compressobj(9, zlib.DEFLATED, -15)
    return compressor.compress(data) + compressor.flush()


def _chunked(data: bytes, size: int = 7) -> bytes:
    frames = [b"%x\r\n%s\r\n" % (len(data[i : i + size]), data[i : i + size]) for i in range(0, len(data), size)]
    return b"".join(frames) + b"0\r\n\r\n"


def _gzip_zeros(total: int) -> bytes:
    compressor = zlib.compressobj(9, zlib.DEFLATED, 31)
    zeros = bytes(MIB)
    parts = [compressor.compress(zeros) for _ in range(total // MIB)]
    return b"".join(parts) + compressor.flush()


def _empty_blocks(count: int) -> bytes:
    """Raw deflate: `count` empty stored blocks, then an empty final block. Wire size grows, output stays zero."""
    return b"\x00\x00\x00\xff\xff" * count + b"\x01\x00\x00\xff\xff"


def _raises(fetcher, url: str, reason: str, **kwargs) -> ToolError:  # noqa: ANN001, ANN003
    with pytest.raises(ToolError) as info:
        fetcher.fetch(url, **kwargs)
    assert info.value.code == "backend_unavailable"
    assert info.value.details.get("reason") == reason
    return info.value


def test_gzip_and_deflate_decoded(server, guard):
    body = PAGE.encode()
    assert len(body) == PAGE_BYTES
    variants = {
        "gzip": ("gzip", gzip.compress(body, mtime=0)),
        "xgzip": ("x-gzip", gzip.compress(body, mtime=0)),
        "GZIP": ("GZIP", gzip.compress(body, mtime=0)),
        "deflate": ("deflate", zlib.compress(body)),
        "raw": ("deflate", _raw_deflate(body)),
    }
    for name, (coding, packed) in variants.items():
        server.route(f"/{name}", headers=(*HTML, ("Content-Encoding", coding)), body=packed)
        server.route(
            f"/{name}-chunked",
            headers=(*HTML, ("Content-Encoding", coding), ("Transfer-Encoding", "chunked")),
            body=_chunked(packed),
            omit_length=True,
        )
    server.route("/identity", headers=(*HTML, ("Content-Encoding", "identity")), body=body)
    server.route("/plain", headers=HTML, body=body)
    fetcher = h.make_fetcher(server, rate_limit_per_host=120)

    for path in [*variants, *(f"{name}-chunked" for name in variants), "identity", "plain"]:
        result = fetcher.fetch(f"https://fake.test/{path}")
        assert result.text == PAGE, path
        assert result.bytes == PAGE_BYTES, path
        assert result.truncated is False, path
        assert result.status == 200
        assert h.audit_lines()[-1]["status"] == "ok"
        assert h.audit_lines()[-1]["bytes_in"] == PAGE_BYTES, path
    assert {seen.header("Accept-Encoding") for seen in server.requests} == {"gzip, deflate"}
    assert len(server.requests) == 12

    # A gzip body whose wire size is smaller than its text: `bytes` is the decompressed length.
    long_page = b"<p>" + b"abcdefgh" * 1000 + b"</p>"
    server.route("/long", headers=(*HTML, ("Content-Encoding", "gzip")), body=gzip.compress(long_page, mtime=0))
    result = fetcher.fetch("https://fake.test/long")
    assert (result.bytes, len(result.text), result.truncated) == (8007, 8007, False)
    assert server.sent["/long"] < 200


def test_zip_bomb_stops_at_cap(server, guard):
    bomb = _gzip_zeros(GIB)  # about 1 MiB on the wire: deflate cannot go beyond roughly 1000 to 1
    assert len(bomb) < 2 * MIB
    server.route("/bomb", headers=(*HTML, ("Content-Encoding", "gzip")), body=bomb, chunk=16384, delay=0.002)
    server.route("/exact", headers=(*HTML, ("Content-Encoding", "gzip")), body=gzip.compress(b"b" * MIB, mtime=0))
    server.route("/over", headers=(*HTML, ("Content-Encoding", "gzip")), body=gzip.compress(b"c" * (MIB + 1), mtime=0))
    server.route("/exact-deflate", headers=(*HTML, ("Content-Encoding", "deflate")), body=zlib.compress(b"d" * MIB))
    fetcher = h.make_fetcher(server, max_bytes=MIB, timeout_s=20, rate_limit_per_host=120)

    tracemalloc.start()
    started = time.monotonic()
    try:
        result = fetcher.fetch("https://fake.test/bomb")
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert time.monotonic() - started < 5
    assert result.truncated is True
    assert result.bytes == 1_048_576
    assert result.text == "\x00" * 1_048_576
    assert peak < 8 * MIB
    assert server.sent["/bomb"] < len(bomb)  # the reader stopped; the rest of the bomb was never pulled
    assert h.audit_lines()[-1]["bytes_in"] == 1_048_576

    exact = fetcher.fetch("https://fake.test/exact")
    assert (exact.truncated, exact.bytes, exact.text) == (False, 1_048_576, "b" * 1_048_576)
    over = fetcher.fetch("https://fake.test/over")
    assert (over.truncated, over.bytes, over.text) == (True, 1_048_576, "c" * 1_048_576)
    exact_deflate = fetcher.fetch("https://fake.test/exact-deflate")
    assert (exact_deflate.truncated, exact_deflate.bytes) == (False, 1_048_576)

    lowered = fetcher.fetch("https://fake.test/exact", max_bytes=2048)
    assert (lowered.truncated, lowered.bytes, lowered.text) == (True, 2048, "b" * 2048)

    # Wire bound: more than cap + 64 KiB of compressed bytes with no output is refused, not read to the end.
    wire = 1024 + 65536
    count = 15_000  # 75 005 wire bytes of empty blocks, zero output
    gz = b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\xff" + _empty_blocks(count) + bytes(8)
    zl = b"\x78\x9c" + _empty_blocks(count) + (1).to_bytes(4, "big")
    assert len(gz) > wire
    assert len(zl) > wire
    small = gzip.compress(b"", mtime=0)
    assert gzip.decompress(gz) == b"" and zlib.decompress(zl) == b""  # both are valid streams of nothing
    assert len(small) < wire
    server.route("/wire-gzip", headers=(*HTML, ("Content-Encoding", "gzip")), body=gz, chunk=4096, delay=0.005)
    server.route("/wire-deflate", headers=(*HTML, ("Content-Encoding", "deflate")), body=zl, chunk=4096, delay=0.005)
    server.route("/empty", headers=(*HTML, ("Content-Encoding", "gzip")), body=small)
    capped = h.make_fetcher(server, max_bytes=1024, rate_limit_per_host=120)
    for path in ("wire-gzip", "wire-deflate"):
        _raises(capped, f"https://fake.test/{path}", "bad_response")
        assert server.sent[f"/{path}"] < len(gz)
        assert h.audit_lines()[-1]["status"] == "bad_response"
    assert capped.fetch("https://fake.test/empty").text == ""


@pytest.mark.parametrize(
    ("header", "value", "shown"),
    [
        ("Content-Encoding", "br", "br"),
        ("Content-Encoding", "zstd", "zstd"),
        ("Content-Encoding", "compress", "compress"),
        ("Content-Encoding", "gzip, gzip", "gzip, gzip"),
        ("Content-Encoding", "gzip, br", "gzip, br"),
        ("Content-Encoding", "foo", "foo"),
        ("Content-Encoding", "x" * 80, "x" * 50),
        ("Content-Encoding", "caf\xe9", "caf?"),
        ("Transfer-Encoding", "gzip", "gzip"),
        ("Transfer-Encoding", "chunked, gzip", "chunked, gzip"),
    ],
)
def test_unsupported_encoding_refused(header, value, shown, server, guard):
    body = b"z" * MIB
    server.route("/ok", headers=HTML, body=b"fine")
    server.route("/enc", headers=(*HTML, (header, value)), body=body, chunk=16384, delay=0.002)
    server.route("/gone", status=404, headers=(*HTML, (header, value)), body=body, chunk=16384, delay=0.002)
    fetcher = h.make_fetcher(server, rate_limit_per_host=120)

    error = _raises(fetcher, "https://fake.test/enc", "bad_response")
    assert header in error.message
    assert shown in error.message
    assert "x" * 51 not in error.message
    assert "\xe9" not in error.message
    assert server.sent["/enc"] < MIB  # the body was not read
    assert h.audit_lines()[-1]["status"] == "bad_response"
    assert h.audit_lines()[-1]["bytes_in"] == 0

    gone = _raises(fetcher, "https://fake.test/gone", "http_404")
    assert gone.details["status"] == 404
    assert gone.details["body"] == ""
    assert server.sent["/gone"] < MIB
    assert fetcher.fetch("https://fake.test/ok").text == "fine"


def test_error_status_with_accepted_encoding_keeps_body(server, guard):
    page = gzip.compress(b"<h1>Not found here</h1>", mtime=0)
    server.route("/gone", status=404, headers=(*HTML, ("Content-Encoding", "gzip")), body=page)
    server.route("/broken", status=500, headers=(*HTML, ("Content-Encoding", "gzip")), body=b"not gzip at all")
    fetcher = h.make_fetcher(server, rate_limit_per_host=120)
    gone = _raises(fetcher, "https://fake.test/gone", "http_404")
    assert gone.details["body"] == "<h1>Not found here</h1>"
    broken = _raises(fetcher, "https://fake.test/broken", "http_500")  # a corrupt error body does not hide the status
    assert broken.details["body"] == ""


def test_corrupt_compressed_stream(server, guard):
    body = (b"<tr><td>Goi thau so 1</td></tr>\n" * 400) + b"END"
    good = gzip.compress(body, mtime=0)
    cut = good[: len(good) // 2]
    bad_crc = good[:-8] + bytes([good[-8] ^ 0xFF]) + good[-7:]
    bad_size = good[:-1] + bytes([good[-1] ^ 0xFF])
    zgood = zlib.compress(body)
    gz = (*HTML, ("Content-Encoding", "gzip"))
    df = (*HTML, ("Content-Encoding", "deflate"))
    cases = {
        "not-gzip": (gz, b"<html>this is not gzip</html>"),
        "empty-gzip": (gz, b""),
        "one-byte": (gz, b"\x1f"),
        "cut": (gz, cut),
        "cut-header": (gz, good[:6]),
        "cut-trailer": (gz, good[:-4]),
        "bad-crc": (gz, bad_crc),
        "bad-size": (gz, bad_size),
        "gzip-as-deflate": (df, good),
        "not-deflate": (df, b"\xff\xfe\xfd\xfc\xfb"),
        "cut-deflate": (df, zgood[: len(zgood) // 2]),
        "bad-adler": (df, zgood[:-1] + bytes([zgood[-1] ^ 0xFF])),
        "cut-raw": (df, _raw_deflate(body)[:20]),
    }
    for name, (headers, payload) in cases.items():
        server.route(f"/{name}", headers=headers, body=payload)
    server.route("/good", headers=gz, body=good)
    fetcher = h.make_fetcher(server, rate_limit_per_host=120)

    for name in cases:
        error = _raises(fetcher, f"https://fake.test/{name}", "bad_response")
        assert "END" not in error.message and "Goi thau" not in error.message, name
        assert h.audit_lines()[-1]["status"] == "bad_response", name
    result = fetcher.fetch("https://fake.test/good")
    assert result.text == body.decode()
    assert (result.bytes, result.truncated) == (len(body), False)
