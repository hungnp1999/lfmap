You are a careful Python 3.12 developer. Write ONE new module in the `lfmap` monorepo: `packages/lfmap-knowledge/src/lfmap_knowledge/embed.py`. Code, comments and docstrings in English. Standard library plus `lfmap_core` only (`urllib.request`, `json`, `ipaddress`; no requests/httpx). Small functions, type hints everywhere, an English docstring on every public function and class.

RULES
- Do NOT edit the tests or conftest.py and do NOT define pytest fixtures.
- Reply with the line `FILE: packages/lfmap-knowledge/src/lfmap_knowledge/embed.py`, then ONE ```python block with the COMPLETE module (imports, constants and everything in the API section, fully implemented). Never answer with an empty block.

API
```python
BATCH_SIZE = 32


def check_loopback(
    url: str,
) -> str: ...  # returns url without trailing "/"; not loopback -> ToolError("invalid_input", ..., {"url": url})


class OllamaEmbedder:
    def __init__(self, url: str, model: str, perms: PermissionManager, timeout: float = 120) -> None: ...

    model: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...
    def ping(self) -> bool: ...
```

check_loopback
- Parse with `urllib.parse.urlsplit`. Accept only scheme `http` or `https`, no username or password, and host `localhost` or an IP where `ipaddress.ip_address(host).is_loopback` (`ValueError` -> refuse). `[::1]` gives hostname `::1`.
- Otherwise raise `ToolError("invalid_input", "Ollama URL must be a loopback address", {"url": url})`.
- `__init__` calls it and stores the cleaned url, `model`, `perms` and `timeout`.

No proxy (required: with proxy variables set, data would leave the machine)
- Make every request through `urllib.request.build_opener(urllib.request.ProxyHandler({}))`, never `urlopen`.

embed
- Call `perms.require_network()` first (it raises `ToolError("permission_denied", ...)`).
- Empty list -> return `[]` with no request.
- Batches of `BATCH_SIZE`: `POST {url}/api/embed`, JSON body `{"model": model, "input": batch}`, header `Content-Type: application/json`; read `"embeddings"` from the JSON reply. Return all vectors in input order.
- `urllib.error.URLError`, `OSError` or a timeout -> `ToolError("backend_unavailable", "Ollama is not reachable", {"reason": "ollama_unreachable"})`.

ping
- `GET {url}/api/tags`; `True` when the status is 200, `False` on any error.

Imports available:
- `from lfmap_core import ToolError` (`ToolError(code, message, details=None)`, attributes `.code`, `.details`).
- `from lfmap_core.permissions import PermissionManager` (`.require_network()`).

CONFTEST (already in packages/lfmap-knowledge/tests/conftest.py; use these fixtures, do not redefine):
```python
import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from lfmap_core.permissions import PermissionManager


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "data"
    folder.mkdir()
    return Path(os.path.realpath(folder))


@pytest.fixture
def root(tmp_path: Path) -> Path:
    folder = tmp_path / "docs"
    folder.mkdir()
    return Path(os.path.realpath(folder))


@pytest.fixture
def perms(root: Path, data_dir: Path) -> PermissionManager:
    return PermissionManager([str(root)], [str(data_dir)])


@pytest.fixture
def db(data_dir: Path) -> Iterator:
    from lfmap_knowledge.store import connect, migrate

    conn = connect(data_dir / "catalog.db")
    migrate(conn)
    yield conn
    conn.close()
```

TESTS (already written, packages/lfmap-knowledge/tests/test_embed.py; make them pass):
```python
import json
import threading
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
        self._reply({"embeddings": [[float(text.split()[-1]), 0.5] for text in body["input"]]})

    def log_message(self, *args) -> None:
        pass


class _Server:
    def __init__(self) -> None:
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Ollama)
        self.httpd.requests = []
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
    texts = [f"câu {i}" for i in range(70)]
    vectors = _embedder(server, net).embed(texts)
    assert vectors == [[float(i), 0.5] for i in range(70)]
    assert BATCH_SIZE == 32
    assert [len(body["input"]) for _, _, body in server.requests] == [32, 32, 6]
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
```

NOW WRITE THE COMPLETE `embed.py`. Start with the FILE line, then the code block containing the whole module.
