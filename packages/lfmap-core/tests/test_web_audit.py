"""`web_fetch` lines in `audit.jsonl`: host and byte counts only (docs/specs/web-plugin.md section 8)."""

import importlib.util
import sys
from pathlib import Path

import pytest

from lfmap_core import ToolError, __version__
from lfmap_core.approval import AUDIT_FIELDS


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

MARKER = b"<p>PAGE-MARKER-TEXT</p>"
REQUEST = (
    "GET /secret-path?q=zzz HTTP/1.1\r\n"
    "Host: fake.test\r\n"
    f"User-Agent: lfmap-web/{__version__}\r\n"
    "Accept: text/html,text/plain,text/xml,application/xml,application/xhtml+xml,application/json,"
    "text/csv;q=0.9,*/*;q=0.1\r\n"
    "Accept-Encoding: identity\r\n"
    "Connection: close\r\n"
    "\r\n"
)


def test_audit_line_host_bytes_in(server, guard):
    body = MARKER + b"x" * (1234 - len(MARKER))
    assert len(body) == 1234
    headers = (("Content-Type", "text/html"), ("Set-Cookie", "sid=cookievalue42"))
    server.route("/secret-path", headers=headers, body=body)
    result = h.make_fetcher(server).fetch("https://fake.test/secret-path?q=zzz")
    assert result.bytes == 1234

    lines = h.audit_lines()
    assert len(lines) == 2
    sent, done = lines
    for line in lines:
        assert set(line) <= AUDIT_FIELDS
        assert line["plugin"] == "web"
        assert line["operation"] == "fetch"
        assert line["event"] == "web_fetch"
        assert line["host"] == "fake.test"
        assert line["channel"] == "cli"
        assert line["bytes_out"] == len(REQUEST.encode("ascii"))
    assert sent["status"] == "sent"
    assert "bytes_in" not in sent
    assert done["status"] == "ok"
    assert done["bytes_in"] == 1234
    assert done["bytes_out"] > 0

    text = h.audit_file().read_text(encoding="utf-8")
    for leak in ("secret-path", "q=zzz", "zzz", "PAGE-MARKER", "cookievalue42", "127.0.0.1", "https://"):
        assert leak not in text

    with pytest.raises(ToolError) as info:
        h.make_fetcher(server).fetch("https://fake.test/missing")
    assert info.value.details["reason"] == "http_404"
    assert info.value.details["status"] == 404
    assert h.audit_lines()[-1]["status"] == "http_404"
    assert h.audit_lines()[-1]["host"] == "fake.test"

    requests = len(server.requests)
    connects = guard.server_connects()
    h.audit_file().unlink()
    h.audit_file().mkdir()
    with pytest.raises(ToolError) as info:
        h.make_fetcher(server).fetch("https://fake.test/secret-path")
    assert info.value.code == "backend_unavailable"
    assert info.value.details["reason"] == "audit_failed"
    assert len(server.requests) == requests
    assert guard.server_connects() == connects
