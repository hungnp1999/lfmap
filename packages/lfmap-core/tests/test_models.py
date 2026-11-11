import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from lfmap_core import ToolError
from lfmap_core.models import ChatMessage, ModelClient, load_models_config
from lfmap_core.models_http import OpenAICompatibleClient, build_client


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args: object) -> None:
        pass

    def do_POST(self) -> None:
        server: FakeServer = self.server  # type: ignore[assignment]
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))
        server.seen.append({"path": self.path, "body": body, "auth": self.headers.get("Authorization")})
        status, payload = server.reply(self.path, body)
        if status in (301, 302):
            self.send_response(status)
            self.send_header("Location", "http://127.0.0.1:1/elsewhere")
            self.end_headers()
            return
        data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class FakeServer(HTTPServer):
    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.seen: list[dict] = []
        self.vectors_extra = 0
        self.fixed: tuple[int, object] | None = None
        self.thread = threading.Thread(target=self.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}/v1"

    def reply(self, path: str, body: dict) -> tuple[int, object]:
        if self.fixed:
            return self.fixed
        if path.endswith("/chat/completions"):
            return 200, {
                "model": body["model"],
                "choices": [{"message": {"role": "assistant", "content": "hello"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 1},
            }
        count = len(body["input"]) + self.vectors_extra
        # out of order on purpose: the client must sort by index
        data = [{"index": i, "embedding": [float(i), 0.5]} for i in range(count)]
        return 200, {"data": list(reversed(data))}


@pytest.fixture
def server():
    fake = FakeServer()
    yield fake
    fake.shutdown()
    fake.server_close()


def _client(server: FakeServer, **kwargs) -> OpenAICompatibleClient:
    return OpenAICompatibleClient(server.url, chat_model="chat-m", embed_model="embed-m", timeout=5, **kwargs)


def test_protocol_conformance_fake_server(server):
    client = _client(server)
    assert isinstance(client, ModelClient)

    result = client.chat([ChatMessage(role="user", content="hi")], max_tokens=50, json_mode=True)
    assert (result.text, result.model, result.finish_reason) == ("hello", "chat-m", "stop")
    assert (result.prompt_tokens, result.completion_tokens) == (3, 1)
    sent = server.seen[-1]
    assert sent["path"] == "/v1/chat/completions"
    assert sent["body"] == {
        "model": "chat-m",
        "messages": [{"role": "user", "content": "hi"}],
        "temperature": 0.0,
        "max_tokens": 50,
        "response_format": {"type": "json_object"},
    }
    assert sent["auth"] is None

    vectors = client.embed(["a", "b", "c"])
    assert vectors == [[0.0, 0.5], [1.0, 0.5], [2.0, 0.5]]
    assert server.seen[-1]["body"] == {"model": "embed-m", "input": ["a", "b", "c"]}

    server.vectors_extra = 1
    with pytest.raises(ToolError) as bad:
        client.embed(["a", "b"])
    assert bad.value.code == "backend_unavailable"
    assert bad.value.details["reason"] == "bad_response"

    server.shutdown()
    server.server_close()
    with pytest.raises(ToolError) as down:
        client.chat([ChatMessage(role="user", content="hi")])
    assert down.value.details["reason"] == "unreachable"


@pytest.mark.parametrize(
    "url", ["http://10.0.0.5:11434/v1", "https://api.example.com/v1", "http://user:pw@127.0.0.1/v1"]
)
def test_non_loopback_local_endpoint_refused_at_load(url):
    config = {"models": {"endpoints": {"local": {"kind": "local", "base_url": url}}, "routes": {"default": "local"}}}
    with pytest.raises(ToolError) as error:
        load_models_config(config)
    assert error.value.code == "invalid_input"


def test_cloud_endpoint_rules():
    cloud = {"kind": "cloud", "base_url": "https://api.example.com/v1", "api_key_env": "LFMAP_CLOUD_API_KEY"}
    local = {"kind": "local", "base_url": "http://localhost:11434/v1"}

    with pytest.raises(ToolError, match="https"):
        load_models_config({"models": {"endpoints": {"cloud": {**cloud, "base_url": "http://api.example.com/v1"}}}})
    with pytest.raises(ToolError, match="environment variable"):
        load_models_config({"models": {"endpoints": {"cloud": {**cloud, "api_key_env": "sk-abc def"}}}})
    # a cloud endpoint that no route names is harmless
    assert load_models_config(
        {"models": {"endpoints": {"local": local, "cloud": cloud}, "routes": {"default": "local"}}}
    )
    # a cloud route is refused until labels travel with data; embeddings stay local even then
    config = {
        "models": {"endpoints": {"local": local, "cloud": cloud}, "routes": {"default": "local", "review": "cloud"}}
    }
    with pytest.raises(ToolError, match="allow_cloud_unlabelled"):
        load_models_config(config)
    config["models"]["allow_cloud_unlabelled"] = True
    assert load_models_config(config).route("review")[1].kind == "cloud"
    config["models"]["routes"]["embed"] = "cloud"
    with pytest.raises(ToolError, match="embeddings stay local"):
        load_models_config(config)


def test_routing_by_config():
    local = {"kind": "local", "base_url": "http://127.0.0.1:11434/v1"}
    other = {"kind": "local", "base_url": "http://127.0.0.1:8080/v1"}
    models = load_models_config(
        {"models": {"endpoints": {"local": local, "big": other}, "routes": {"default": "local", "summarise": "big"}}}
    )
    assert models.route("summarise")[0] == "big"
    assert models.route("classify")[0] == "local"

    default = load_models_config({})
    name, endpoint = default.route("embed")
    assert (name, endpoint.base_url, endpoint.embed_model) == ("local", "http://127.0.0.1:11434/v1", "bge-m3")
    assert endpoint.chat_model is None

    with pytest.raises(ToolError, match="unknown endpoint"):
        load_models_config({"models": {"endpoints": {"local": local}, "routes": {"default": "nope"}}})
    no_default = load_models_config({"models": {"endpoints": {"local": local}, "routes": {"embed": "local"}}})
    with pytest.raises(ToolError, match="no default route"):
        no_default.route("summarise")
    with pytest.raises(ToolError):
        load_models_config({"models": {"endpoints": {"local": {**local, "surprise": 1}}}})


def test_no_redirect_no_proxy(server, monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:1")
    client = _client(server)
    assert client.embed(["a"]) == [[0.0, 0.5]]  # the proxy variable is ignored

    server.fixed = (302, b"")
    with pytest.raises(ToolError) as error:
        client.chat([ChatMessage(role="user", content="hi")])
    assert error.value.code == "backend_unavailable"
    assert error.value.details["reason"] == "http_302"
    assert len(server.seen) == 2  # the Location was not followed


def test_api_key_only_in_header(server, monkeypatch):
    monkeypatch.setenv("LFMAP_TEST_KEY", "sk-secret-123")
    endpoint = load_models_config(
        {
            "models": {
                "endpoints": {
                    "e": {"kind": "local", "base_url": server.url, "chat_model": "m", "api_key_env": "LFMAP_TEST_KEY"}
                }
            }
        }
    ).endpoints["e"]
    client = build_client(endpoint)
    client.chat([ChatMessage(role="user", content="hi")])
    assert server.seen[-1]["auth"] == "Bearer sk-secret-123"
    assert "sk-secret-123" not in json.dumps(server.seen[-1]["body"])

    server.fixed = (401, {"error": "bad key sk-secret-123"})
    with pytest.raises(ToolError) as error:
        client.chat([ChatMessage(role="user", content="hi")])
    assert "sk-secret-123" not in json.dumps(error.value.to_dict())
    assert error.value.details["reason"] == "http_401"

    monkeypatch.delenv("LFMAP_TEST_KEY")
    with pytest.raises(ToolError) as missing:
        build_client(endpoint)
    assert missing.value.code == "invalid_input"
    assert missing.value.details["variable"] == "LFMAP_TEST_KEY"


def test_limits_and_batching(server):
    client = _client(server)
    user = ChatMessage(role="user", content="x")
    with pytest.raises(ToolError) as error:
        client.chat([ChatMessage(role="user", content="x" * 200_001)])
    assert error.value.code == "invalid_input"
    for kwargs in ({"max_tokens": 8193}, {"max_tokens": 0}, {"temperature": 3}):
        with pytest.raises(ToolError):
            client.chat([user], **kwargs)
    with pytest.raises(ToolError):
        client.chat([])
    with pytest.raises(ToolError):
        client.embed(["a"] * 1025)
    assert client.embed([]) == []
    assert server.seen == []  # nothing reached the server


def test_missing_model_is_invalid_input(server):
    client = OpenAICompatibleClient(server.url)
    with pytest.raises(ToolError, match="No chat model"):
        client.chat([ChatMessage(role="user", content="hi")])
    with pytest.raises(ToolError, match="No embedding model"):
        client.embed(["a"])


@pytest.mark.parametrize(
    "payload",
    [b"not json", {"choices": []}, {"choices": [{"message": {"content": None}}]}, {"data": "x"}],
)
def test_malformed_response_is_bad_response(server, payload):
    server.fixed = (200, payload)
    client = _client(server)
    with pytest.raises(ToolError) as error:
        client.chat([ChatMessage(role="user", content="hi")])
    assert error.value.details["reason"] == "bad_response"
    with pytest.raises(ToolError) as error:
        client.embed(["a"])
    assert error.value.details["reason"] == "bad_response"
