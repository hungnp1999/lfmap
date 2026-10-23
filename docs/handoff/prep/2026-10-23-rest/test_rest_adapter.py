# Prepared for Roadmap 1.3 (docs/handoff/2026-10-23-rest-adapter.md).
# Copy to packages/lfmap-core/tests/test_rest_adapter.py and delete these two lines.
import json
import os
from datetime import timedelta

import pytest
from pydantic import BaseModel
from starlette.testclient import TestClient

from lfmap_core import Tool, grants, operation
from lfmap_core.approval import audit_path
from lfmap_core.manifest import parse_manifest
from lfmap_core.registry import PluginEntry, Registry
from lfmap_core.rest_adapter import MAX_BODY_BYTES, build_app, load_or_create_token, route

from .conftest import MANIFEST, FakeTool

TOKEN = "test-token-0123456789"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
BASE = "http://127.0.0.1:8765"


class ChannelInput(BaseModel):
    pass


class ChannelOutput(BaseModel):
    channel: str


class ChannelTool(Tool):
    @operation("where")
    def where(self, inp: ChannelInput) -> ChannelOutput:
        """Report the channel."""
        return ChannelOutput(channel=self.ctx.channel)


CHANNEL_MANIFEST = """
[plugin]
id = "channel"
name = "Channel"
version = "0.1.0"
description = "Test plugin."
license = "Apache-2.0"
[plugin.entrypoint]
module = "tests"
class = "ChannelTool"
[[operations]]
name = "where"
input = "x:ChannelInput"
output = "x:ChannelOutput"
"""

REST_ON = "\n[adapters]\nrest = true\n"


def _registry(side_effects: str = "local_write", fake_rest: bool = True) -> Registry:
    reg = Registry()
    manifest = MANIFEST.replace('side_effects = "local_write"', f'side_effects = "{side_effects}"')
    reg.register(PluginEntry("fake-plugin", FakeTool, parse_manifest(manifest + (REST_ON if fake_rest else ""))))
    reg.register(PluginEntry("channel", ChannelTool, parse_manifest(CHANNEL_MANIFEST + REST_ON)))
    return reg


def _client(registry: Registry | None = None, approve=(), plugins=None) -> TestClient:
    app = build_app(registry or _registry(), plugins or [], TOKEN, approve)
    return TestClient(app, base_url=BASE, raise_server_exceptions=False)


def _audit() -> list[dict]:
    path = audit_path()
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _assert_error(response, status: int, code: str) -> dict:
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == {"code", "message", "details"}
    assert body["code"] == code
    return body


# Routing and results


def test_route():
    assert route("fake-plugin", "greet") == "/tools/fake-plugin/greet"


def test_call_returns_output_model():
    response = _client().post("/tools/fake-plugin/greet", json={"name": "A", "times": 2}, headers=AUTH)
    assert response.status_code == 200
    assert response.json() == {"message": "Hello A Hello A"}


def test_channel_is_rest():
    response = _client().post("/tools/channel/where", json={}, headers=AUTH)
    assert response.json() == {"channel": "rest"}


def test_tool_error_maps_to_status_and_body():
    response = _client().post("/tools/fake-plugin/greet", json={"name": "error"}, headers=AUTH)
    body = _assert_error(response, 404, "not_found")
    assert body["message"] == "No such person"
    assert body["details"] == {"name": "error"}


def test_invalid_input_is_400_with_errors():
    response = _client().post("/tools/fake-plugin/greet", json={"times": "many"}, headers=AUTH)
    body = _assert_error(response, 400, "invalid_input")
    assert body["details"]["errors"]


def test_json_body_must_be_an_object():
    response = _client().post("/tools/fake-plugin/greet", json=["A"], headers=AUTH)
    _assert_error(response, 400, "invalid_input")


def test_malformed_json_is_400():
    headers = {**AUTH, "Content-Type": "application/json"}
    response = _client().post("/tools/fake-plugin/greet", content=b"{not json", headers=headers)
    _assert_error(response, 400, "invalid_input")


def test_unknown_operation_is_404():
    response = _client().post("/tools/fake-plugin/missing", json={}, headers=AUTH)
    _assert_error(response, 404, "not_found")


def test_get_on_operation_is_405():
    response = _client().get("/tools/fake-plugin/greet", headers=AUTH)
    _assert_error(response, 405, "invalid_input")


def test_plugin_without_rest_adapter_is_not_served():
    client = _client(_registry(fake_rest=False))
    response = client.post("/tools/fake-plugin/greet", json={"name": "A"}, headers=AUTH)
    _assert_error(response, 404, "not_found")
    assert "/tools/fake-plugin/greet" not in client.get("/openapi.json").json()["paths"]


def test_plugins_filter():
    client = _client(plugins=["channel"])
    _assert_error(client.post("/tools/fake-plugin/greet", json={"name": "A"}, headers=AUTH), 404, "not_found")
    assert client.post("/tools/channel/where", json={}, headers=AUTH).status_code == 200


def test_unexpected_exception_is_500_without_details(monkeypatch):
    from lfmap_core import rest_adapter

    def boom(*args, **kwargs):
        raise RuntimeError("secret detail C:\\Users\\x")

    monkeypatch.setattr(rest_adapter, "run_operation", boom)
    response = _client().post("/tools/fake-plugin/greet", json={"name": "A"}, headers=AUTH)
    body = _assert_error(response, 500, "internal")
    assert "secret detail" not in response.text
    assert body["details"] == {}


# Request checks: token, Host, Origin, content type, size


def test_build_app_requires_token():
    with pytest.raises(Exception, match="token"):
        build_app(_registry(), [], "")


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer wrong"}, {"Authorization": f"Basic {TOKEN}"}, {"Authorization": TOKEN}],
)
def test_token_required(headers):
    response = _client().post("/tools/fake-plugin/greet", json={"name": "A"}, headers=headers)
    _assert_error(response, 401, "permission_denied")
    assert response.headers["www-authenticate"] == "Bearer"


def test_token_checked_before_routing():
    # An unknown operation without a token must not reveal whether it exists.
    response = _client().post("/tools/fake-plugin/missing", json={})
    _assert_error(response, 401, "permission_denied")


@pytest.mark.parametrize("host", ["evil.example", "192.168.1.10:8765", "127.0.0.1.evil.example", ""])
def test_non_loopback_host_refused(host):
    response = _client().post("/tools/fake-plugin/greet", json={"name": "A"}, headers={**AUTH, "Host": host})
    body = _assert_error(response, 403, "permission_denied")
    assert body["details"]["reason"] == "host"


@pytest.mark.parametrize("host", ["127.0.0.1:8765", "localhost:8765", "[::1]:8765", "127.0.0.1"])
def test_loopback_host_accepted(host):
    response = _client().post("/tools/fake-plugin/greet", json={"name": "A"}, headers={**AUTH, "Host": host})
    assert response.status_code == 200


def test_host_checked_on_every_path():
    response = _client().get("/health", headers={"Host": "evil.example"})
    _assert_error(response, 403, "permission_denied")


def test_browser_origin_refused():
    headers = {**AUTH, "Origin": "http://evil.example"}
    response = _client().post("/tools/fake-plugin/greet", json={"name": "A"}, headers=headers)
    body = _assert_error(response, 403, "permission_denied")
    assert body["details"]["reason"] == "origin"


def test_no_cors_headers():
    response = _client().options("/tools/fake-plugin/greet", headers={"Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in response.headers


@pytest.mark.parametrize("content_type", ["text/plain", "application/x-www-form-urlencoded", "multipart/form-data"])
def test_json_content_type_required(content_type):
    headers = {**AUTH, "Content-Type": content_type}
    response = _client().post("/tools/fake-plugin/greet", content=b'{"name": "A"}', headers=headers)
    _assert_error(response, 415, "invalid_input")


def test_json_content_type_with_charset_accepted():
    headers = {**AUTH, "Content-Type": "application/json; charset=utf-8"}
    response = _client().post("/tools/fake-plugin/greet", content=b'{"name": "A"}', headers=headers)
    assert response.status_code == 200


def test_body_too_large():
    payload = {"name": "A" * (MAX_BODY_BYTES + 1)}
    response = _client().post("/tools/fake-plugin/greet", json=payload, headers=AUTH)
    _assert_error(response, 413, "invalid_input")


# Approval tiers on REST (ADR-017): nobody can be asked


def test_t1_runs_and_is_audited():
    response = _client().post("/tools/fake-plugin/write", json={"names": ["a"]}, headers=AUTH)
    assert response.status_code == 200
    assert {"channel": "rest", "plugin": "fake-plugin", "operation": "write", "tier": "T1"}.items() <= _audit()[
        -1
    ].items()


def test_t0_is_not_audited():
    _client().post("/tools/fake-plugin/greet", json={"name": "A"}, headers=AUTH)
    assert _audit() == []


def test_t2_denied_without_approval():
    response = _client().post("/tools/fake-plugin/write", json={"names": ["a"], "escalate": "overwrite"}, headers=AUTH)
    body = _assert_error(response, 403, "permission_denied")
    assert body["details"]["tier"] == "T2"
    assert "approvals grant fake-plugin.write" in body["details"]["hint"]
    assert _audit()[-1]["decision"] == "deny"


def test_t2_runs_with_serve_approve():
    client = _client(approve=["fake-plugin.write"])
    response = client.post("/tools/fake-plugin/write", json={"names": ["a"], "escalate": "overwrite"}, headers=AUTH)
    assert response.status_code == 200


def test_t2_runs_with_grant():
    grants.add("fake-plugin.write", "T2", timedelta(hours=1))
    response = _client().post("/tools/fake-plugin/write", json={"names": ["a"], "escalate": "overwrite"}, headers=AUTH)
    assert response.status_code == 200


def test_t3_denied_even_when_approved():
    client = _client(approve=["fake-plugin.write"])
    response = client.post("/tools/fake-plugin/write", json={"names": ["a"], "escalate": "external"}, headers=AUTH)
    body = _assert_error(response, 403, "permission_denied")
    assert body["details"]["tier"] == "T3"


def test_t3_runs_with_grant():
    grants.add("fake-plugin.write", "T3", timedelta(hours=1))
    response = _client().post("/tools/fake-plugin/write", json={"names": ["a"], "escalate": "external"}, headers=AUTH)
    assert response.status_code == 200


def test_external_operation_cannot_be_pre_approved():
    with pytest.raises(Exception, match="cannot be pre-approved"):
        build_app(_registry("external"), [], TOKEN, ["fake-plugin.write"])


def test_unknown_approve_refused():
    with pytest.raises(Exception, match="unknown operation"):
        build_app(_registry(), [], TOKEN, ["fake-plugin.nope"])


def test_approve_expires(monkeypatch):
    from lfmap_core import rest_adapter

    client = _client(approve=["fake-plugin.write"])
    real = rest_adapter.time.monotonic
    monkeypatch.setattr(rest_adapter.time, "monotonic", lambda: real() + rest_adapter.APPROVE_TTL_SECONDS + 1)
    response = client.post("/tools/fake-plugin/write", json={"names": ["a"], "escalate": "overwrite"}, headers=AUTH)
    _assert_error(response, 403, "permission_denied")


def test_policy_deny_from_config(user_dirs):
    (user_dirs / "config.toml").write_text('[approval.operations]\n"fake-plugin.write" = "deny"\n', encoding="utf-8")
    response = _client().post("/tools/fake-plugin/write", json={"names": ["a"]}, headers=AUTH)
    _assert_error(response, 403, "permission_denied")


# Health, OpenAPI and docs


def test_health_needs_no_token():
    response = _client().get("/health")
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_openapi_lists_operations_with_schemas_and_bearer():
    schema = _client().get("/openapi.json").json()
    post = schema["paths"]["/tools/fake-plugin/greet"]["post"]
    body = post["requestBody"]["content"]["application/json"]["schema"]
    assert body["$ref"].endswith("/GreetInput")
    assert set(schema["components"]["schemas"]["GreetInput"]["properties"]) == {"name", "times", "shout"}
    assert post["security"] == [{"bearer": []}]
    assert schema["components"]["securitySchemes"]["bearer"] == {"type": "http", "scheme": "bearer"}
    assert "tier T1" in schema["paths"]["/tools/fake-plugin/write"]["post"]["description"]


def test_docs_page_is_self_contained():
    response = _client().get("/docs")
    assert response.status_code == 200
    assert "/tools/fake-plugin/greet" in response.text
    assert "<script" not in response.text.lower()
    assert "http://" not in response.text and "https://" not in response.text
    assert "default-src 'none'" in response.headers["content-security-policy"]


# Token file


def test_token_file_created_once(tmp_path):
    path = tmp_path / "lfmap" / "rest_token"
    first = load_or_create_token(path)
    assert len(first) >= 32
    assert load_or_create_token(path) == first
    if os.name != "nt":
        assert path.stat().st_mode & 0o077 == 0


def test_token_rotates_when_file_deleted(tmp_path):
    path = tmp_path / "rest_token"
    first = load_or_create_token(path)
    path.unlink()
    assert load_or_create_token(path) != first


# `lfmap serve rest`


def test_serve_rest_binds_loopback_with_token(monkeypatch):
    import uvicorn
    from typer.testing import CliRunner

    from lfmap_core.cli import build_app as build_cli
    from lfmap_core.rest_adapter import token_path

    calls = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: calls.append(kwargs))
    result = CliRunner().invoke(build_cli(_registry()), ["serve", "rest", "--port", "9000"])
    assert result.exit_code == 0, result.output
    assert calls[0]["host"] == "127.0.0.1"
    assert calls[0]["port"] == 9000
    assert token_path().exists()
    assert load_or_create_token() not in result.output


def test_serve_rest_has_no_host_option():
    from typer.testing import CliRunner

    from lfmap_core.cli import build_app as build_cli

    result = CliRunner().invoke(build_cli(_registry()), ["serve", "rest", "--host", "0.0.0.0"])
    assert result.exit_code != 0
