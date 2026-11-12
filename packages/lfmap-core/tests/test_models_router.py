import json
import socket
import threading
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from lfmap_core import ToolError
from lfmap_core.approval import Gate, Policy, audit_path
from lfmap_core.manifest import parse_manifest
from lfmap_core.models import ChatMessage
from lfmap_core.models_http import OpenAICompatibleClient
from lfmap_core.models_router import ModelRouter
from lfmap_core.permissions import PermissionManager
from lfmap_core.registry import PluginEntry
from lfmap_core.runtime import build_tool
from lfmap_core.tool import Tool, ToolContext

API_KEY = "sk-test-secret-key-123"
PROMPT = "highly confidential prompt text"
CONFIG = {
    "models": {
        "endpoints": {
            "local": {"kind": "local", "base_url": "http://127.0.0.1:11434/v1", "chat_model": "l", "embed_model": "e"},
            "cloud": {
                "kind": "cloud",
                "base_url": "https://api.example.com/v1",
                "chat_model": "big",
                "api_key_env": "LFMAP_TEST_KEY",
            },
        },
        "routes": {"default": "local", "review": "cloud", "extract": "cloud"},
        "allow_cloud_unlabelled": True,
    }
}


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args: object) -> None:
        pass

    def do_POST(self) -> None:
        server: FakeServer = self.server  # type: ignore[assignment]
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        server.seen.append({"path": self.path, "body": body, "auth": self.headers.get("Authorization")})
        if server.fixed:
            status, payload = server.fixed
        elif self.path.endswith("/chat/completions"):
            status, payload = 200, {"choices": [{"message": {"content": "hello"}, "finish_reason": "stop"}]}
        else:
            status, payload = 200, {"data": [{"index": i, "embedding": [0.1]} for i in range(len(body["input"]))]}
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class FakeServer(HTTPServer):
    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.seen: list[dict] = []
        self.fixed: tuple[int, object] | None = None
        threading.Thread(target=self.serve_forever, daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}/v1"


@pytest.fixture(autouse=True)
def user_dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    monkeypatch.setenv("LFMAP_CONFIG", str(tmp_path / "config.toml"))
    return tmp_path


@pytest.fixture
def connects(monkeypatch) -> list:
    """Socket guard: records every connect and refuses anything but the loopback fake server."""
    seen: list = []
    real = socket.socket.connect

    def guard(self, address, *args):
        seen.append(address)
        if not (isinstance(address, tuple) and address[0] == "127.0.0.1"):
            raise AssertionError(f"unexpected connect to {address}")
        return real(self, address, *args)

    monkeypatch.setattr(socket.socket, "connect", guard)
    return seen


@pytest.fixture
def server(connects):
    fake = FakeServer()
    yield fake
    fake.shutdown()
    fake.server_close()


def _policy(data: str = "normal") -> Policy:
    expires = date.today() + timedelta(days=30)
    return Policy.from_config({"approval": {"destinations": {"api.example.com": {"data": data, "expires": expires}}}})


def _router(server, *, channel="cli", policy=None, ask=None, cloud_ai=True, network=True, config=None):
    gate = Gate("llm", "summarise", channel, policy or _policy(), ask=ask)
    ctx = ToolContext(
        plugin_id="llm", permissions=PermissionManager([], [], network=network), channel=channel, approver=gate
    )

    def factory(endpoint):
        key = API_KEY if endpoint.kind == "cloud" else None
        return OpenAICompatibleClient(
            server.url, chat_model=endpoint.chat_model, embed_model=endpoint.embed_model, api_key=key, timeout=5
        )

    return ModelRouter(
        config or CONFIG,
        plugin_id="llm",
        operation="summarise",
        channel=channel,
        permissions=ctx.permissions,
        cloud_ai=cloud_ai,
        approve=ctx.require_approval,
        client_factory=factory,
    )


def _say(text: str = PROMPT) -> list[ChatMessage]:
    return [ChatMessage(role="user", content=text)]


def _audit() -> list[dict]:
    path = audit_path()
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def _model_calls() -> list[dict]:
    return [line for line in _audit() if line.get("event") == "model_call"]


@pytest.mark.parametrize("channel", ["mcp", "job", "flow"])
def test_non_loopback_refused_without_approval(server, connects, channel):
    router = _router(server, channel=channel, policy=Policy())
    with pytest.raises(ToolError) as denied:
        router.chat(_say(), task="review")
    assert denied.value.code == "permission_denied"
    assert connects == []
    assert server.seen == []
    assert _model_calls() == []


def test_model_call_audit_line_per_cloud_call(server):
    router = _router(server)
    router.chat(_say(), task="review")
    router.chat(_say(), task="extract", json_mode=True)
    router.embed([PROMPT], task="embed")  # embeddings are routed local: nothing leaves the machine
    router.chat(_say(), task="summarise")  # local route: nothing leaves the machine

    calls = _model_calls()
    assert [c["status"] for c in calls] == ["sent", "ok", "sent", "ok"]
    allowed = {"time", "principal", "channel", "plugin", "operation", "event", "endpoint", "host", "model"}
    allowed |= {"data", "bytes_out", "bytes_in", "status", "reason"}
    for line in calls:
        assert set(line) <= allowed
        assert (line["endpoint"], line["host"], line["data"]) == ("cloud", "api.example.com", "normal")
        assert line["bytes_out"] > 0
    assert calls[1]["bytes_in"] > 0
    assert len(server.seen) == 4
    text = audit_path().read_text(encoding="utf-8")
    assert PROMPT not in text and API_KEY not in text and "hello" not in text


def test_secret_never_to_cloud(server, connects):
    router = _router(server, policy=_policy("private"))
    with pytest.raises(ToolError) as denied:
        router.chat(_say(), task="review", data="secret")
    assert denied.value.code == "permission_denied"
    assert connects == [] and server.seen == []
    assert _model_calls() == []
    # a secret call to a local endpoint is allowed
    assert router.chat(_say(), task="summarise", data="secret").text == "hello"


def test_private_needs_destination_level(server, connects):
    asked: list[str] = []
    router = _router(server, policy=_policy("normal"), ask=lambda question: asked.append(question) or False)
    router.chat(_say(), task="review", data="normal")
    assert asked == []
    with pytest.raises(ToolError) as denied:
        router.chat(_say(), task="review", data="private")
    assert denied.value.code == "permission_denied"
    assert len(asked) == 1 and "api.example.com (private)" in asked[0]
    assert len(server.seen) == 1  # only the normal call was sent

    covered = _router(server, policy=_policy("private"))
    covered.chat(_say(), task="review", data="private")
    assert len(server.seen) == 2
    assert _model_calls()[-2]["data"] == "private"


def test_cloud_requires_manifest_permissions(server, connects):
    for kwargs in ({"cloud_ai": False}, {"network": False}):
        router = _router(server, **kwargs)
        with pytest.raises(ToolError) as denied:
            router.chat(_say(), task="review")
        assert denied.value.code == "permission_denied"
    assert connects == [] and _model_calls() == []
    # local routes need network access too
    with pytest.raises(ToolError) as denied:
        _router(server, network=False).chat(_say(), task="summarise")
    assert denied.value.code == "permission_denied"
    assert connects == []


MODELS_MANIFEST = """
[plugin]
id = "uses-models"
name = "Uses models"
version = "0.1.0"
description = "Test."
license = "Apache-2.0"
[plugin.entrypoint]
module = "tests"
class = "Tool"
[permissions]
network = true
cloud_ai = true
[adapters]
models = {flag}
"""


def _entry(flag: str) -> PluginEntry:
    return PluginEntry("uses-models", Tool, parse_manifest(MODELS_MANIFEST.format(flag=flag)))


def test_ctx_models_gate(user_dirs):
    (user_dirs / "config.toml").write_text("", encoding="utf-8")
    off = build_tool(_entry("false"), channel="cli").ctx
    with pytest.raises(ToolError) as denied:
        off.models  # noqa: B018
    assert denied.value.code == "permission_denied"

    on = build_tool(_entry("true"), channel="cli").ctx
    router = on.models
    assert isinstance(router, ModelRouter)
    # the view takes a task, never a URL or endpoint
    with pytest.raises(TypeError):
        router.chat(_say(), url="http://example.com")  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        router.chat(_say(), task="review", endpoint="cloud")  # type: ignore[call-arg]


def test_embed_never_routed_to_cloud(server, connects):
    config = json.loads(json.dumps(CONFIG))
    config["models"]["routes"]["default"] = "cloud"
    with pytest.raises(ToolError) as refused:
        _router(server, config=config).embed(["x"], task="embed")
    assert refused.value.code == "invalid_input"
    assert connects == [] and _model_calls() == []


def test_failed_cloud_call_is_logged_without_body(server):
    server.fixed = (500, {"error": PROMPT})
    with pytest.raises(ToolError) as failed:
        _router(server).chat(_say(), task="review")
    assert failed.value.details["reason"] == "http_500"
    calls = _model_calls()
    assert [c["status"] for c in calls] == ["sent", "error"]
    assert calls[1]["reason"] == "http_500"
    assert PROMPT not in audit_path().read_text(encoding="utf-8")


def test_unreachable_local_does_not_fall_back_to_cloud(server, connects):
    server.shutdown()
    server.server_close()
    with pytest.raises(ToolError) as down:
        _router(server).chat(_say(), task="summarise")
    assert down.value.details["reason"] == "unreachable"
    assert _model_calls() == []
