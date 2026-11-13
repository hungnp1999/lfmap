"""Knowledge embeds through `ctx.models` (task `embed`); the Ollama settings stand in without a `[models]` route."""

import json
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from lfmap_core import ToolContext, ToolError
from lfmap_core.models_router import ModelRouter
from lfmap_core.permissions import PermissionManager
from lfmap_knowledge.indexer import BATCH_SIZE, ModelEmbedder
from lfmap_knowledge.tool import KnowledgeTool


def _number(text: str) -> float:
    last = text.split()[-1]
    return float(last) if last.isdigit() else 0.0


class _V1(BaseHTTPRequestHandler):
    def _reply(self, status: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.requests.append((self.path, body))
        if self.server.barrier is not None:
            self.server.barrier.wait()
            if body["input"][0].endswith(" 0"):
                time.sleep(0.2)  # the first batch answers last
        if self.server.status != 200:
            self._reply(self.server.status, {"error": "input too long " + "x" * 2000})
            return
        count = self.server.count or len(body["input"])
        texts = body["input"]
        data = [{"index": i, "embedding": [_number(texts[i % len(texts)]), 0.5]} for i in range(count)]
        self._reply(200, {"data": data})

    def log_message(self, *args) -> None:
        pass


class _Server:
    def __init__(self) -> None:
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _V1)
        self.httpd.requests, self.httpd.barrier, self.httpd.status, self.httpd.count = [], None, 200, 0
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


def _router(url: str, network: bool = True) -> ModelRouter:
    config = {
        "models": {"endpoints": {"local": {"kind": "local", "base_url": f"{url}/v1"}}, "routes": {"default": "local"}}
    }
    return ModelRouter(
        config,
        plugin_id="knowledge",
        channel="sdk",
        permissions=PermissionManager([], [], network=network),
        cloud_ai=False,
        approve=lambda *a, **k: None,
    )


def _embedder(server: _Server, **kwargs) -> ModelEmbedder:
    return ModelEmbedder(_router(server.url), "nomic-embed-text", **kwargs)


def test_embed_in_batches_through_v1_embeddings(server: _Server):
    vectors = _embedder(server, batch_size=2).embed(["t 1", "t 2", "t 3"])
    assert vectors == [[1.0, 0.5], [2.0, 0.5], [3.0, 0.5]]
    assert [len(body["input"]) for _, body in server.requests] == [2, 1]
    assert all(path == "/v1/embeddings" and body["model"] == "nomic-embed-text" for path, body in server.requests)


def test_empty_list_makes_no_request(server: _Server):
    assert _embedder(server).embed([]) == []
    assert server.requests == []


def test_server_down_keeps_the_reason(server: _Server):
    embedder = _embedder(server)
    server.stop()
    with pytest.raises(ToolError) as err:
        embedder.embed(["t 1"])
    assert (err.value.code, err.value.details["reason"]) == ("backend_unavailable", "ollama_unreachable")


def test_network_permission_required(server: _Server):
    with pytest.raises(ToolError) as err:
        ModelEmbedder(_router(server.url, network=False), "m").embed(["t 1"])
    assert err.value.code == "permission_denied"
    assert server.requests == []


def test_ping(server: _Server):
    embedder = _embedder(server)
    assert embedder.ping() is True
    server.stop()
    assert embedder.ping() is False


def test_ping_without_network_permission_makes_no_request(server: _Server):
    assert ModelEmbedder(_router(server.url, network=False), "m").ping() is False
    assert server.requests == []


def test_wrong_vector_count_is_an_error(server: _Server):
    server.httpd.count = 1
    with pytest.raises(ToolError) as err:
        _embedder(server).embed(["t 1", "t 2"])
    assert (err.value.code, err.value.details["reason"]) == ("backend_unavailable", "ollama_bad_response")


def test_http_error_is_reported_with_its_code_and_body(server: _Server):
    server.httpd.status = 400
    with pytest.raises(ToolError) as err:
        _embedder(server).embed(["t 1"])
    assert err.value.details["reason"] == "ollama_http_400"
    assert err.value.details["body"].startswith('{"error": "input too long')
    assert len(err.value.details["body"]) == 500


@pytest.mark.parametrize("size", [0, 1025, "64", 2.0, True])
def test_bad_batch_size_is_invalid_input(size):
    with pytest.raises(ToolError) as err:
        ModelEmbedder(None, "m", batch_size=size)
    assert err.value.code == "invalid_input"


@pytest.mark.parametrize("value", [0, 5, "2", True])
def test_bad_concurrency_is_invalid_input(value):
    with pytest.raises(ToolError) as err:
        ModelEmbedder(None, "m", concurrency=value)
    assert err.value.code == "invalid_input"


def test_concurrent_requests_keep_the_input_order(server: _Server):
    server.httpd.barrier = threading.Barrier(3, timeout=5)
    vectors = _embedder(server, batch_size=2, concurrency=3).embed([f"t {i}" for i in range(6)])
    assert vectors == [[float(i), 0.5] for i in range(6)]
    assert sorted(body["input"][0] for _, body in server.requests) == ["t 0", "t 2", "t 4"]


def test_concurrency_above_one_warns(caplog):
    with caplog.at_level("WARNING", logger="lfmap_knowledge.indexer"):
        ModelEmbedder(None, "m")
        assert caplog.records == []
        ModelEmbedder(None, "m", concurrency=2)
    assert "one slot" in caplog.text


class _Routed:
    """Stands for the runtime's `ctx.models`: records every call."""

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], str, str | None]] = []

    def embed(self, texts, *, task, model=None, data="normal"):
        self.calls.append((texts, task, model))
        return [[1.0] for _ in texts]


@pytest.fixture
def ctx(root: Path, data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ToolContext:
    monkeypatch.setenv("LFMAP_CONFIG", str(tmp_path / "config.toml"))
    return ToolContext(
        plugin_id="knowledge",
        permissions=PermissionManager([str(root)], [str(data_dir)], network=True),
        data_dir=data_dir,
    )


def test_default_settings_use_ctx_models_with_task_embed(ctx: ToolContext):
    ctx.model_router = _Routed()
    ctx.settings = {"embed_model": "other", "embed_batch": 2}
    embedder = KnowledgeTool(ctx)._embedder()
    assert embedder.embed(["a", "b", "c"]) == [[1.0], [1.0], [1.0]]
    assert ctx.model_router.calls == [(["a", "b"], "embed", "other"), (["c"], "embed", "other")]
    assert embedder.batch_size == 2 and BATCH_SIZE == 128


def test_ollama_url_setting_is_the_fallback_embed_route(ctx: ToolContext, server: _Server):
    ctx.model_router = _Routed()
    ctx.settings = {"ollama_url": server.url, "embed_model": "m"}
    assert KnowledgeTool(ctx)._embedder().embed(["t 5"]) == [[5.0, 0.5]]
    assert ctx.model_router.calls == []
    assert server.requests[0][0] == "/v1/embeddings"


def test_owner_models_table_wins_over_the_settings(ctx: ToolContext, tmp_path: Path, server: _Server):
    (tmp_path / "config.toml").write_text(
        '[models.endpoints.local]\nkind = "local"\nbase_url = "http://127.0.0.1:9/v1"\n'
        '[models.routes]\ndefault = "local"\n',
        encoding="utf-8",
    )
    ctx.model_router = _Routed()
    ctx.settings = {"ollama_url": server.url}
    KnowledgeTool(ctx)._embedder().embed(["t 1"])
    assert ctx.model_router.calls and server.requests == []


@pytest.mark.parametrize(
    "url", ["http://10.0.0.5:11434", "http://example.com", "ftp://127.0.0.1", "http://u:p@127.0.0.1"]
)
def test_non_loopback_ollama_url_is_refused(ctx: ToolContext, url: str):
    ctx.settings = {"ollama_url": url}
    with pytest.raises(ToolError) as err:
        KnowledgeTool(ctx)._embedder()
    assert err.value.code == "invalid_input"


def test_embedder_down_gives_keyword_search(ctx: ToolContext, root: Path):
    from lfmap_knowledge.schemas import ReindexInput, SearchInput

    (root / "a.md").write_text("# Alpha\n\nkangaroo\n", encoding="utf-8")
    ctx.settings = {"ollama_url": "http://127.0.0.1:1"}
    tool = KnowledgeTool(ctx)
    assert tool.reindex(ReindexInput()).embed_skipped_reason == "ollama_unreachable"
    hits = tool.search(SearchInput(query="kangaroo")).hits
    assert hits and {h.mode_used for h in hits} == {"keyword"}
