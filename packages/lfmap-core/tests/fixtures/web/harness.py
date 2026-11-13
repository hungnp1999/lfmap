"""Offline harness for the web fetcher tests: fake HTTPS server, resolver stub, socket guard, fake clock.

Loaded by path from the `test_web_*.py` files (pytest runs with `--import-mode=importlib`).
"""

import json
import os
import socket
import ssl
import threading
import time
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from lfmap_core.permissions import PermissionManager
from lfmap_core.web import load_web_config
from lfmap_core.web_http import NetworkPolicy, WebFetcher

HERE = Path(__file__).parent
CERT = HERE / "cert.pem"
KEY = HERE / "key.pem"
LOOPBACK = "127.0.0.1"
TEST_HOSTS = ("fake.test", "other.test", "blocked.test")
HTML = (("Content-Type", "text/html; charset=utf-8"),)


@dataclass
class Route:
    status: int = 200
    headers: tuple[tuple[str, str], ...] = HTML
    body: bytes = b"<html>ok</html>"
    chunk: int = 65536
    delay: float = 0.0
    content_length: int | None = None
    omit_length: bool = False


@dataclass
class Seen:
    method: str
    path: str
    headers: list[tuple[str, str]]

    def header(self, name: str) -> str | None:
        return next((value for key, value in self.headers if key.lower() == name.lower()), None)


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - signature of the base class
        return

    def _serve(self) -> None:
        fake: FakeServer = self.server.fake  # type: ignore[attr-defined]
        path = self.path.split("?", 1)[0]
        fake.requests.append(Seen(self.command, self.path, list(self.headers.items())))
        route = fake.routes.get(path, Route(status=404, headers=(("Content-Type", "text/plain"),), body=b"nope"))
        self.send_response_only(route.status)
        for name, value in route.headers:
            self.send_header(name, value)
        if not route.omit_length:
            length = len(route.body) if route.content_length is None else route.content_length
            self.send_header("Content-Length", str(length))
        self.send_header("Connection", "close")
        self.close_connection = True
        try:
            self.end_headers()
            for start in range(0, len(route.body), route.chunk):
                piece = route.body[start : start + route.chunk]
                self.wfile.write(piece)
                fake.sent[path] += len(piece)
                if route.delay:
                    time.sleep(route.delay)
        except (OSError, ssl.SSLError):
            return

    do_GET = _serve
    do_HEAD = _serve
    do_POST = _serve


class _TLSServer(ThreadingHTTPServer):
    daemon_threads = True
    tls: ssl.SSLContext
    fake: "FakeServer"

    def finish_request(self, request: Any, client_address: Any) -> None:
        try:
            conn = self.tls.wrap_socket(request, server_side=True)
        except (OSError, ssl.SSLError):
            return
        try:
            self.RequestHandlerClass(conn, client_address, self)
        finally:
            conn.close()


class FakeServer:
    """HTTPS on 127.0.0.1:<random>, certificate for fake.test, other.test and blocked.test."""

    def __init__(self) -> None:
        self.routes: dict[str, Route] = {}
        self.requests: list[Seen] = []
        self.sent: defaultdict[str, int] = defaultdict(int)
        self._server = _TLSServer((LOOPBACK, 0), _Handler)
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(CERT, KEY)
        self._server.tls = tls
        self._server.fake = self
        self.port: int = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)

    def route(self, path: str, **kwargs: Any) -> None:
        self.routes[path] = Route(**kwargs)

    def start(self) -> "FakeServer":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()


Answer = list[str] | Callable[[int], list[str]] | BaseException


class StubResolver:
    """Maps a host to addresses (a list, a callable of the call number, or an exception); records each call."""

    def __init__(self, answers: dict[str, Answer] | None = None) -> None:
        self.answers: dict[str, Answer] = (
            {host: [LOOPBACK] for host in TEST_HOSTS} if answers is None else dict(answers)
        )
        self.calls: list[tuple[str, int]] = []

    def __call__(self, host: str, port: int) -> list[str]:
        self.calls.append((host, port))
        answer = self.answers.get(host)
        if answer is None:
            raise socket.gaierror(socket.EAI_NONAME, "unknown host")
        if isinstance(answer, BaseException):
            raise answer
        if callable(answer):
            return answer(sum(1 for name, _ in self.calls if name == host))
        return list(answer)

    def hosts(self) -> list[str]:
        return [host for host, _ in self.calls]


def hang(seconds: float) -> Callable[[int], list[str]]:
    def answer(_call: int) -> list[str]:
        time.sleep(seconds)
        return [LOOPBACK]

    return answer


class SocketGuard:
    """Counts `socket.connect` and `socket.getaddrinfo`; anything but the fake server is refused and a violation.

    `dns` answers `getaddrinfo` for a name (the OS resolver as the production fetcher sees it); `expect` lists
    addresses a test wants refused without failing (a simulated public address)."""

    def __init__(self, port: int) -> None:
        self.allowed = (LOOPBACK, port)
        self.connects: list[tuple[str, int]] = []
        self.lookups: list[tuple[Any, Any]] = []
        self.violations: list[str] = []
        self.dns: dict[str, list[str]] = {}
        self.expect: set[str] = set()

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        real_connect = socket.socket.connect
        guard = self

        def connect(sock: socket.socket, address: Any) -> None:
            target = (str(address[0]), int(address[1]))
            guard.connects.append(target)
            if target != guard.allowed:
                if target[0] not in guard.expect:
                    guard.violations.append(f"connect {target}")
                raise ConnectionRefusedError(f"socket guard refused {target}")
            real_connect(sock, address)

        def getaddrinfo(host: Any, port: Any, *args: Any, **kwargs: Any) -> list[Any]:
            guard.lookups.append((host, port))
            if host in guard.dns:
                return [
                    (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (addr, port))
                    for addr in guard.dns[host]
                ]
            guard.violations.append(f"getaddrinfo {host}")
            raise socket.gaierror(socket.EAI_NONAME, "socket guard: no DNS in tests")

        monkeypatch.setattr(socket.socket, "connect", connect)
        monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)

    def server_connects(self) -> int:
        return sum(1 for target in self.connects if target == self.allowed)


class FakeClock:
    def __init__(self, start: float = 1_800_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def trust_fixture() -> ssl.SSLContext:
    return ssl.create_default_context(cafile=str(CERT))


def make_fetcher(
    server: FakeServer,
    *,
    config: dict[str, Any] | None = None,
    hosts: Iterable[str] = TEST_HOSTS,
    resolver: StubResolver | None = None,
    ssl_context: ssl.SSLContext | None = None,
    clock: Callable[[], float] | None = None,
    allow_non_global: bool = True,
    network: bool = True,
    **web: Any,
) -> WebFetcher:
    table = {"web": {"allowed_hosts": list(hosts), **web}} if config is None else config
    return WebFetcher(
        load_web_config(table),
        plugin_id="web",
        channel="cli",
        operation="fetch",
        permissions=PermissionManager([], [], network),
        resolver=resolver if resolver is not None else StubResolver(),
        ssl_context=ssl_context if ssl_context is not None else trust_fixture(),
        clock=clock if clock is not None else FakeClock(),
        policy=NetworkPolicy(allow_non_global=allow_non_global),
        port=server.port,
    )


def audit_file() -> Path:
    return Path(os.environ["LOCALAPPDATA"]) / "lfmap" / "audit.jsonl"


def audit_lines() -> list[dict[str, Any]]:
    path = audit_file()
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def rate_db() -> Path:
    return Path(os.environ["LOCALAPPDATA"]) / "lfmap" / "web_rate.db"


@pytest.fixture
def server() -> Any:
    fake = FakeServer().start()
    yield fake
    fake.stop()


@pytest.fixture
def guard(server: FakeServer, monkeypatch: pytest.MonkeyPatch) -> Any:
    socket_guard = SocketGuard(server.port)
    socket_guard.install(monkeypatch)
    yield socket_guard
    assert socket_guard.violations == []
