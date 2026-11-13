"""Per-host rolling window in `web_rate.db` and the per-run call cap (docs/specs/web-plugin.md section 6)."""

import importlib.util
import sys
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

TEXT = (("Content-Type", "text/plain"),)


def _limited(fetcher, url: str) -> ToolError:  # noqa: ANN001
    with pytest.raises(ToolError) as info:
        fetcher.fetch(url)
    assert info.value.code == "backend_unavailable"
    assert info.value.details["reason"] == "rate_limited"
    return info.value


def test_rate_limit_per_host(server, guard):
    server.route("/", headers=TEXT, body=b"hello")
    clock = h.FakeClock()
    fetcher = h.make_fetcher(server, clock=clock, rate_limit_per_host=2)
    assert fetcher.fetch("https://fake.test/").text == "hello"
    assert fetcher.fetch("https://fake.test/").text == "hello"
    error = _limited(fetcher, "https://fake.test/")
    assert error.details["retry_after_s"] == 60
    assert len(server.requests) == 2

    assert fetcher.fetch("https://other.test/").text == "hello"
    assert len(server.requests) == 3

    second = h.make_fetcher(server, clock=clock, rate_limit_per_host=2)
    _limited(second, "https://fake.test/")
    clock.advance(30)
    assert _limited(second, "https://fake.test/").details["retry_after_s"] == 30
    clock.advance(31)
    assert second.fetch("https://fake.test/").text == "hello"
    assert second.fetch("https://fake.test/").text == "hello"
    _limited(second, "https://fake.test/")
    assert len(server.requests) == 5

    h.rate_db().unlink()
    assert second.fetch("https://fake.test/").text == "hello"
    assert len(server.requests) == 6

    h.rate_db().unlink()
    h.rate_db().mkdir()
    with pytest.raises(ToolError) as info:
        second.fetch("https://fake.test/")
    assert info.value.code == "backend_unavailable"
    assert info.value.details["reason"] == "rate_state"
    assert len(server.requests) == 6
    statuses = [line["status"] for line in h.audit_lines()]
    assert statuses.count("rate_limited") == 4
    assert statuses[-1] == "rate_state"


def test_per_run_call_cap(server, guard):
    server.route("/", headers=TEXT, body=b"hello")
    resolver = h.StubResolver()
    fetcher = h.make_fetcher(server, resolver=resolver, max_calls_per_run=3)
    for _ in range(3):
        fetcher.fetch("https://fake.test/")
    connects = guard.server_connects()
    with pytest.raises(ToolError) as info:
        fetcher.fetch("https://fake.test/")
    assert info.value.code == "backend_unavailable"
    assert info.value.details["reason"] == "run_limit"
    with pytest.raises(ToolError) as info:
        fetcher.fetch("https://other.test/")
    assert info.value.details["reason"] == "run_limit"
    assert len(server.requests) == 3
    assert guard.server_connects() == connects == 3
    assert len(resolver.calls) == 3

    fresh = h.make_fetcher(server, max_calls_per_run=3)
    assert fresh.fetch("https://fake.test/").text == "hello"
    assert len(server.requests) == 4
