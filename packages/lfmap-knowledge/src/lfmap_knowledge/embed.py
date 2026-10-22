"""Embed chunk texts with a local Ollama server; only loopback URLs are accepted."""

import json
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from ipaddress import ip_address

from lfmap_core import ToolError
from lfmap_core.permissions import PermissionManager

BATCH_SIZE = 128  # texts per /api/embed request; setting embed_batch overrides
MAX_BATCH_SIZE = 1024
MAX_CONCURRENCY = 4  # parallel /api/embed requests; setting embed_concurrency, useful with OLLAMA_NUM_PARALLEL


def check_loopback(url: str) -> str:
    """Return url without a trailing slash if it is http(s) to localhost or a loopback IP, else invalid_input."""
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname or ""
    if parts.scheme in ("http", "https") and not parts.username and not parts.password:
        if host == "localhost" or _is_loopback_ip(host):
            return url.rstrip("/")
    raise ToolError("invalid_input", "Ollama URL must be a loopback address", {"url": url})


def _bounded(name: str, value: object, high: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= high:
        raise ToolError("invalid_input", f"{name} must be an integer from 1 to {high}", {name: value})
    return value


def _is_loopback_ip(host: str) -> bool:
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


class OllamaEmbedder:
    """Embedder for POST {url}/api/embed; proxies from the environment are ignored so data stays local."""

    def __init__(
        self,
        url: str,
        model: str,
        perms: PermissionManager,
        timeout: float = 120,
        batch_size: int = BATCH_SIZE,
        concurrency: int = 1,
    ) -> None:
        self.batch_size = _bounded("embed_batch", batch_size, MAX_BATCH_SIZE)
        self.concurrency = _bounded("embed_concurrency", concurrency, MAX_CONCURRENCY)
        self.url = check_loopback(url)
        self.model = model
        self.perms = perms
        self.timeout = timeout
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def embed(self, texts: list[str]) -> list[list[float]]:
        """One vector per text, in input order; batches of batch_size, up to concurrency requests at once.

        Needs network permission.
        """
        if not texts:
            return []
        self.perms.require_network()
        batches = [texts[start : start + self.batch_size] for start in range(0, len(texts), self.batch_size)]
        if self.concurrency == 1 or len(batches) == 1:
            results = map(self._embed_batch, batches)
        else:
            with ThreadPoolExecutor(min(self.concurrency, len(batches)), thread_name_prefix="lfmap-ollama") as pool:
                results = list(pool.map(self._embed_batch, batches))
        return [vector for batch in results for vector in batch]

    def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        body = json.dumps({"model": self.model, "input": batch}).encode("utf-8")
        request = urllib.request.Request(
            f"{self.url}/api/embed", data=body, headers={"Content-Type": "application/json"}
        )
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                data = json.load(response)
        except (OSError, ValueError) as exc:  # URLError and TimeoutError are OSError
            raise ToolError("backend_unavailable", "Ollama is not reachable", {"reason": "ollama_unreachable"}) from exc
        embeddings = data.get("embeddings") if isinstance(data, dict) else None
        if not isinstance(embeddings, list) or len(embeddings) != len(batch):
            raise ToolError(
                "backend_unavailable", "Ollama returned an unexpected embed response", {"reason": "ollama_bad_response"}
            )
        return embeddings

    def ping(self) -> bool:
        """True if GET {url}/api/tags answers 200; False without network permission or when Ollama is down."""
        if not self.perms.network:
            return False
        try:
            with self._opener.open(urllib.request.Request(f"{self.url}/api/tags"), timeout=self.timeout) as response:
                return response.status == 200
        except OSError:
            return False
