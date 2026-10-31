"""Ollama chat client on loopback (handoff D4), standard library only; environment proxies are ignored."""

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from ipaddress import ip_address

from common.models import Models

URL = "http://127.0.0.1:11434"
LEADING = "qwen3.8:27b"
WORKING = "qwen2.5-coder:14b"
NUM_CTX = 16384
NUM_PREDICT = 8192
KEEP_ALIVE = "30m"
TIMEOUT = 3600


def check_loopback(url: str) -> str:
    """url without a trailing slash if it is http to localhost or a loopback IP; ValueError otherwise."""
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname or ""
    if parts.scheme == "http" and not parts.username and not parts.password:
        if host == "localhost" or _is_loopback_ip(host):
            return url.rstrip("/")
    raise ValueError(f"Ollama URL must be a loopback http URL: {url}")


def _is_loopback_ip(host: str) -> bool:
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


@dataclass
class OllamaModel:
    """One Ollama model behind POST /api/chat; temperature 0, num_ctx 16384, JSON schema via `format`."""

    name: str
    url: str = URL
    think: bool | str | None = None
    options: dict = field(default_factory=lambda: {"temperature": 0, "num_ctx": NUM_CTX, "num_predict": NUM_PREDICT})

    def __post_init__(self) -> None:
        self.url = check_loopback(self.url)
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def body(self, system: str, user: str, schema: dict | None) -> dict:
        """Request body of one chat call."""
        body: dict = {
            "model": self.name,
            "stream": False,
            "keep_alive": KEEP_ALIVE,
            "options": dict(self.options),
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        if schema is not None:
            body["format"] = schema
        if self.think is not None:
            body["think"] = self.think
        return body

    def chat(self, system: str, user: str, schema: dict | None = None) -> str:
        """Reply text of one non-streaming chat call."""
        data = json.dumps(self.body(system, user, schema)).encode("utf-8")
        request = urllib.request.Request(
            f"{self.url}/api/chat", data=data, headers={"Content-Type": "application/json"}
        )
        with self._opener.open(request, timeout=TIMEOUT) as response:
            reply = json.loads(response.read())
        return reply.get("message", {}).get("content", "")


def default_models(url: str = URL, think: bool | str | None = None) -> Models:
    """Leading qwen3.8:27b and Working qwen2.5-coder:14b on one local Ollama."""
    return Models(leading=OllamaModel(LEADING, url, think), working=OllamaModel(WORKING, url))
