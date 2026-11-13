"""`[web]` config, URL checks before any I/O and the T3 query bound (docs/specs/web-plugin.md sections 3, 5, 16)."""

import importlib.util
import sys
from pathlib import Path

import pytest

from lfmap_core import Tool, ToolError
from lfmap_core.manifest import parse_manifest
from lfmap_core.registry import PluginEntry
from lfmap_core.runtime import build_tool
from lfmap_core.web import QUERY_T3_LIMIT, load_web_config, long_query


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

WEB_MANIFEST = """
[plugin]
id = "webby"
name = "Webby"
version = "0.1.0"
description = "Test plugin."
license = "Apache-2.0"
[plugin.entrypoint]
module = "tests"
class = "WebbyTool"
[permissions]
network = true
[adapters]
web = true
"""


class WebbyTool(Tool):
    pass


def _reason(info: pytest.ExceptionInfo[ToolError]) -> str | None:
    return info.value.details.get("reason")


@pytest.mark.parametrize(
    ("table", "key"),
    [
        ({"allowed_hosts": ["a.com"], "colour": "blue"}, "colour"),
        ({"allowed_hosts": ["*.example.com"]}, "allowed_hosts"),
        ({"allowed_hosts": ["http://a.com"]}, "allowed_hosts"),
        ({"allowed_hosts": ["a.com/path"]}, "allowed_hosts"),
        ({"allowed_hosts": ["127.0.0.1"]}, "allowed_hosts"),
        ({"allowed_hosts": ["localhost"]}, "allowed_hosts"),
        ({"allowed_hosts": ["a.com:443"]}, "allowed_hosts"),
        ({"allowed_hosts": ["A.com"]}, "allowed_hosts"),
        ({"allowed_hosts": ["nodot"]}, "allowed_hosts"),
        ({"allowed_hosts": "a.com"}, "allowed_hosts"),
        ({"rate_limit_per_host": 0}, "rate_limit_per_host"),
        ({"rate_limit_per_host": 121}, "rate_limit_per_host"),
        ({"max_bytes": 10**9}, "max_bytes"),
        ({"max_bytes": 1023}, "max_bytes"),
        ({"timeout_s": 0}, "timeout_s"),
        ({"timeout_s": 61}, "timeout_s"),
        ({"max_redirects": 6}, "max_redirects"),
        ({"max_calls_per_run": 0}, "max_calls_per_run"),
        ({"timeout_s": True}, "timeout_s"),
        ({"allow_non_global": True}, "allow_non_global"),
        ({"port": 8443}, "port"),
        ({"resolver": "x"}, "resolver"),
    ],
)
def test_config_validation(table, key):
    with pytest.raises(ToolError) as info:
        load_web_config({"web": table})
    assert info.value.code == "invalid_input"
    assert _reason(info) == "bad_config"
    assert info.value.details["key"] == key
    assert key in info.value.message

    with pytest.raises(ToolError) as info:
        load_web_config({"web": ["a.com"]})
    assert _reason(info) == "bad_config"

    config = load_web_config({"web": {"allowed_hosts": ["baodauthau.vn", "muasamcong.mof.gov.vn"]}})
    assert config.allowed_hosts == ["baodauthau.vn", "muasamcong.mof.gov.vn"]
    assert (config.rate_limit_per_host, config.max_bytes, config.timeout_s) == (12, 2097152, 20)
    assert (config.max_redirects, config.max_calls_per_run) == (3, 100)
    assert load_web_config({"web": {"allowed_hosts": ["bücher.example"]}}).allowed_hosts == ["xn--bcher-kva.example"]


@pytest.mark.parametrize("config", [{}, {"web": {}}, {"web": {"allowed_hosts": []}}])
def test_no_config_denies_all(config, server, guard):
    server.route("/")
    resolver = h.StubResolver()
    fetcher = h.make_fetcher(server, config=config, resolver=resolver)
    for url in ("https://fake.test/", "https://other.test/page", "https://example.com/"):
        with pytest.raises(ToolError) as info:
            fetcher.fetch(url)
        assert info.value.code == "permission_denied"
        assert _reason(info) == "host_not_allowed"
    assert guard.connects == []
    assert guard.lookups == []
    assert resolver.calls == []
    assert server.requests == []
    assert load_web_config({}).allowed_hosts == []

    entry = PluginEntry("webby", WebbyTool, parse_manifest(WEB_MANIFEST.replace("web = true", "web = false")))
    tool = build_tool(entry, config=config)
    with pytest.raises(ToolError) as info:
        tool.ctx.web  # noqa: B018 - the property raises
    assert info.value.code == "permission_denied"

    no_network = h.make_fetcher(server, hosts=["fake.test"], network=False)
    with pytest.raises(ToolError) as info:
        no_network.fetch("https://fake.test/")
    assert info.value.code == "permission_denied"
    assert server.requests == []


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("https://user@fake.test/", "userinfo"),
        ("https://user:pw@fake.test/", "userinfo"),
        ("https://fake.test@other.test/", "userinfo"),
        ("http://fake.test/", "scheme"),
        ("ftp://fake.test/", "scheme"),
        ("file:///etc/passwd", "scheme"),
        ("fake.test/x", "scheme"),
        ("https://fake.test:8443/", "port"),
        ("https://fake.test:0/", "port"),
        ("https://127.0.0.1/", "ip_literal"),
        ("https://[::1]/", "ip_literal"),
        ("https://localhost/", "ip_literal"),
        ("https://127.1/", "ip_literal"),
        ("https://fake.test/" + "a" * 2031, "bad_url"),  # 2049 characters
        ("\\\\server\\share", "bad_url"),
        ("\\\\?\\C:\\x", "bad_url"),
        ("//fake.test/x", "bad_url"),
        ("https://fake.test/a b", "bad_url"),
        ("https://fake.test/a\nb", "bad_url"),
        ("https://fake.test/a\\b", "bad_url"),
        ("https:///path", "bad_url"),
        ("https://fake..test/", "bad_url"),
    ],
)
def test_url_userinfo_refused(url, reason, server, guard):
    resolver = h.StubResolver()
    fetcher = h.make_fetcher(server, resolver=resolver)
    with pytest.raises(ToolError) as info:
        fetcher.fetch(url)
    assert info.value.code == "invalid_input"
    assert _reason(info) == reason
    assert resolver.calls == []
    assert guard.connects == []
    assert guard.lookups == []
    assert h.audit_lines() == []
    with pytest.raises(ToolError) as info:
        fetcher.fetch(None)  # type: ignore[arg-type]
    assert _reason(info) == "bad_url"


def test_long_query_is_t3():
    assert QUERY_T3_LIMIT == 200
    base = "https://fake.test/search"
    assert long_query(base + "?" + "q" * 200) is False
    assert long_query(base + "?" + "q" * 201) is True
    assert long_query(base) is False
    assert long_query(base + "?") is False
    assert long_query("https://fake.test/" + "p" * 1500 + "?" + "q" * 200) is False
    assert long_query(base + "?" + "q" * 200 + "#" + "f" * 500) is False
    assert long_query(base + "#" + "f" * 500) is False
    # counted as sent: "ă" is "%C4%83", six characters
    assert long_query(base + "?" + "ă" * 33) is False
    assert long_query(base + "?" + "ă" * 34) is True
