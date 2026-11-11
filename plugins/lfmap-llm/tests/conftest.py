import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from lfmap_core.registry import Registry, load_entry
from lfmap_llm.tool import LlmTool


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args: object) -> None:
        pass

    def do_POST(self) -> None:
        server: FakeServer = self.server  # type: ignore[assignment]
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        server.seen.append(body)
        payload = {
            "model": body["model"],
            "choices": [{"message": {"content": server.reply}, "finish_reason": "stop"}],
        }
        data = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class FakeServer(HTTPServer):
    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.seen: list[dict] = []
        self.reply = "ok"
        threading.Thread(target=self.serve_forever, daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}/v1"


@pytest.fixture(autouse=True)
def user_dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    monkeypatch.setenv("LFMAP_CONFIG", str(tmp_path / "config.toml"))
    return tmp_path


@pytest.fixture(autouse=True)
def connects(monkeypatch) -> list:
    """Socket guard: CI stays offline, only the loopback fake server may be reached."""
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
def server():
    fake = FakeServer()
    yield fake
    fake.shutdown()
    fake.server_close()


@pytest.fixture(autouse=True)
def configure(user_dirs, server):
    """Write config.toml with a local endpoint on the fake server and a cloud endpoint nothing may reach."""

    def _configure(**routes: str) -> None:
        lines = "\n".join(f'{task} = "{endpoint}"' for task, endpoint in routes.items())
        (user_dirs / "config.toml").write_text(
            f"""[models]
allow_cloud_unlabelled = true
[models.endpoints.local]
kind = "local"
base_url = "{server.url}"
chat_model = "local-model"
[models.endpoints.cloud]
kind = "cloud"
base_url = "https://api.example.com/v1"
chat_model = "big-model"
api_key_env = "LFMAP_TEST_KEY"
[models.routes]
default = "local"
{lines}
""",
            encoding="utf-8",
        )

    _configure()
    return _configure


@pytest.fixture
def entry():
    return load_entry(LlmTool)


@pytest.fixture
def registry(entry) -> Registry:
    reg = Registry()
    reg.register(entry)
    return reg
