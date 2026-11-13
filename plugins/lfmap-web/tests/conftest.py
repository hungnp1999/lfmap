import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest

from lfmap_core import web_http
from lfmap_core.registry import Registry, load_entry
from lfmap_web.tool import WebTool

HARNESS = Path(__file__).parents[3] / "packages" / "lfmap-core" / "tests" / "fixtures" / "web" / "harness.py"


def _load():  # noqa: ANN202
    name = "lfmap_web_test_harness"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, HARNESS)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


h = _load()
server = h.server
guard = h.guard


@pytest.fixture(autouse=True)
def user_dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    monkeypatch.setenv("LFMAP_CONFIG", str(tmp_path / "config.toml"))
    monkeypatch.setenv("LFMAP_FLOWS", str(tmp_path / "flows.toml"))
    return tmp_path


@pytest.fixture
def configure(user_dirs, server, guard, monkeypatch):
    """Allow fake.test in config.toml and point the runtime's fetcher at the offline fake server."""
    real = web_http.WebFetcher

    def seamed(config, **kwargs):  # noqa: ANN001, ANN003, ANN202
        return real(
            config,
            **kwargs,
            resolver=h.StubResolver(),
            ssl_context=h.trust_fixture(),
            clock=h.FakeClock(),
            policy=web_http.NetworkPolicy(allow_non_global=True),
            port=server.port,
        )

    monkeypatch.setattr(web_http, "WebFetcher", seamed)

    def _configure(hosts: str = '"fake.test"', extra: str = "") -> None:
        (user_dirs / "config.toml").write_text(f"[web]\nallowed_hosts = [{hosts}]\n{extra}", encoding="utf-8")

    _configure()
    return _configure


@pytest.fixture
def entry():
    return load_entry(WebTool)


@pytest.fixture
def registry(entry) -> Registry:
    reg = Registry()
    reg.register(entry)
    return reg


@pytest.fixture
def runner():
    """An event loop made before the socket guard is installed: on Windows a new loop opens a loopback socketpair."""
    with asyncio.Runner() as runner:
        yield runner
