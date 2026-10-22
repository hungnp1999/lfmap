import json
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from lfmap_core import ToolError
from lfmap_core.permissions import PermissionManager
from lfmap_knowledge.embed import BATCH_SIZE, OllamaEmbedder, check_loopback


class _Ollama(BaseHTTPRequestHandler):
    def _reply(self, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        self.server.requests.append(("GET", self.path, None))
        self._reply({"models": []})

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.requests.append(("POST", self.path, body))
        if self.server.barrier is not None:
            self.server.barrier.wait()  # every request of the call must be in flight at once
            if body["input"][0].endswith(" 0"):
                time.sleep(0.2)  # the first batch answers last
        self._reply({"embeddings": [[float(text.split()[-1]), 0.5] for text in body["input"]]})

    def log_message(self, *args) -> None:
        pass


class _Server:
    def __init__(self) -> None:
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Ollama)
        self.httpd.requests = []
        self.httpd.barrier = None
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    @property
    def requests(self) -> list:
        return self.httpd.requests

    def stop(self) -> None:
        if self.thread.is_alive():
            self.httpd.shutdown()
            self.httpd.server_close()
            self.thread.join()


@pytest.fixture
def server() -> Iterator[_Server]:
    running = _Server()
    yield running
    running.stop()


@pytest.fixture
def net() -> PermissionManager:
    return PermissionManager([], [], network=True)


def _embedder(server: _Server, perms: PermissionManager) -> OllamaEmbedder:
    return OllamaEmbedder(server.url, "nomic-embed-text", perms, timeout=5)


@pytest.mark.parametrize(
    "url", ["http://10.0.0.5:11434", "http://example.com", "ftp://127.0.0.1", "http://u:p@127.0.0.1"]
)
def test_non_loopback_is_refused(url: str, net: PermissionManager):
    with pytest.raises(ToolError) as caught:
        check_loopback(url)
    assert caught.value.code == "invalid_input"
    with pytest.raises(ToolError):
        OllamaEmbedder(url, "m", net)


def test_loopback_is_accepted(net: PermissionManager):
    assert check_loopback("http://127.0.0.1:11434/") == "http://127.0.0.1:11434"
    assert check_loopback("http://localhost:1") == "http://localhost:1"
    assert check_loopback("http://[::1]:1") == "http://[::1]:1"
    assert OllamaEmbedder("http://localhost:1", "m", net).model == "m"


def test_embed_in_batches(server: _Server, net: PermissionManager):
    texts = [f"câu {i}" for i in range(300)]
    vectors = _embedder(server, net).embed(texts)
    assert vectors == [[float(i), 0.5] for i in range(300)]
    assert BATCH_SIZE == 128
    assert [len(body["input"]) for _, _, body in server.requests] == [128, 128, 44]
    assert all(method == "POST" and path == "/api/embed" for method, path, _ in server.requests)
    assert all(body["model"] == "nomic-embed-text" for _, _, body in server.requests)


def test_empty_list_makes_no_request(server: _Server, net: PermissionManager):
    assert _embedder(server, net).embed([]) == []
    assert server.requests == []


def test_server_down(server: _Server, net: PermissionManager):
    embedder = _embedder(server, net)
    server.stop()
    with pytest.raises(ToolError) as caught:
        embedder.embed(["câu 1"])
    assert caught.value.code == "backend_unavailable"
    assert caught.value.details["reason"] == "ollama_unreachable"


def test_network_permission_required(server: _Server):
    with pytest.raises(ToolError) as caught:
        _embedder(server, PermissionManager([], [])).embed(["câu 1"])
    assert caught.value.code == "permission_denied"
    assert server.requests == []


def test_ping(server: _Server, net: PermissionManager):
    embedder = _embedder(server, net)
    assert embedder.ping() is True
    assert server.requests[0][:2] == ("GET", "/api/tags")
    server.stop()
    assert embedder.ping() is False


def test_proxy_variables_are_ignored(server: _Server, net: PermissionManager, monkeypatch: pytest.MonkeyPatch):
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.delenv(name, raising=False)
    for name in ("HTTP_PROXY", "http_proxy"):
        monkeypatch.setenv(name, "http://203.0.113.1:9")
    assert _embedder(server, net).embed(["câu 7"]) == [[7.0, 0.5]]
    assert len(server.requests) == 1


def test_wrong_vector_count_is_an_error(server: _Server, net: PermissionManager, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(_Ollama, "do_POST", lambda self: self._reply({"embeddings": [[1.0]]}))
    with pytest.raises(ToolError) as caught:
        _embedder(server, net).embed(["a", "b"])
    assert caught.value.code == "backend_unavailable"
    assert caught.value.details["reason"] == "ollama_bad_response"


def test_ping_without_network_permission_makes_no_request(server: _Server):
    assert _embedder(server, PermissionManager([], [])).ping() is False
    assert server.requests == []


def test_batch_size_can_be_set(server: _Server, net: PermissionManager):
    embedder = OllamaEmbedder(server.url, "nomic-embed-text", net, timeout=5, batch_size=2)
    assert embedder.embed(["t 1", "t 2", "t 3"]) == [[1.0, 0.5], [2.0, 0.5], [3.0, 0.5]]
    assert [len(body["input"]) for _, _, body in server.requests] == [2, 1]


@pytest.mark.parametrize("size", [0, 1025, "64", 2.0, True])
def test_bad_batch_size_is_invalid_input(net: PermissionManager, size):
    with pytest.raises(ToolError) as err:
        OllamaEmbedder("http://localhost:1", "m", net, batch_size=size)
    assert err.value.code == "invalid_input"


def test_concurrent_requests_keep_the_input_order(server: _Server, net: PermissionManager):
    server.httpd.barrier = threading.Barrier(3, timeout=5)
    embedder = OllamaEmbedder(server.url, "nomic-embed-text", net, timeout=10, batch_size=2, concurrency=3)
    assert embedder.embed([f"t {i}" for i in range(6)]) == [[float(i), 0.5] for i in range(6)]
    assert sorted(body["input"][0] for _, _, body in server.requests) == ["t 0", "t 2", "t 4"]


def test_concurrent_failure_is_backend_unavailable(net: PermissionManager):
    embedder = OllamaEmbedder("http://127.0.0.1:1", "m", net, timeout=2, batch_size=1, concurrency=2)
    with pytest.raises(ToolError) as err:
        embedder.embed(["t 0", "t 1", "t 2"])
    assert err.value.details["reason"] == "ollama_unreachable"


@pytest.mark.parametrize("value", [0, 5, "2", True])
def test_bad_concurrency_is_invalid_input(net: PermissionManager, value):
    with pytest.raises(ToolError) as err:
        OllamaEmbedder("http://localhost:1", "m", net, concurrency=value)
    assert err.value.code == "invalid_input"


def test_http_error_is_reported_with_its_code_and_body(server: _Server, net: PermissionManager, monkeypatch):
    def refuse(self) -> None:
        self.rfile.read(int(self.headers["Content-Length"]))
        data = json.dumps({"error": "input too long " + "x" * 2000}).encode()
        self.send_response(400)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    monkeypatch.setattr(_Ollama, "do_POST", refuse)
    with pytest.raises(ToolError) as err:
        _embedder(server, net).embed(["t 1"])
    assert err.value.code == "backend_unavailable"
    assert err.value.details["reason"] == "ollama_http_400"
    assert err.value.details["body"].startswith('{"error": "input too long')
    assert len(err.value.details["body"]) == 500


def test_concurrency_above_one_warns(net: PermissionManager, caplog):
    with caplog.at_level("WARNING", logger="lfmap_knowledge.embed"):
        OllamaEmbedder("http://localhost:1", "m", net)
        assert caplog.records == []
        OllamaEmbedder("http://localhost:1", "m", net, concurrency=2)
    assert "one slot" in caplog.text
