"""F7 probes for packages/lfmap-knowledge/src/lfmap_knowledge/embed.py (card TC-K7).

The card says "return all vectors in input order"; the frozen tests never send a reply with the wrong count.
"""

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from lfmap_core import ToolError
from lfmap_core.permissions import PermissionManager
from lfmap_knowledge.embed import OllamaEmbedder


class _ShortOllama(BaseHTTPRequestHandler):
    """Replies with one vector fewer than the inputs."""

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        data = json.dumps({"embeddings": [[0.1, 0.2] for _ in body["input"][1:]]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args) -> None:
        pass


@pytest.fixture
def short_url() -> Iterator[str]:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _ShortOllama)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()
    thread.join()


def test_probe_vector_count_is_checked(short_url: str):
    """A reply with fewer vectors than inputs is an error, not a silently shorter list."""
    embedder = OllamaEmbedder(short_url, "bge-m3", PermissionManager([], [], network=True), timeout=5)
    with pytest.raises(ToolError):
        embedder.embed(["một", "hai", "ba"])
