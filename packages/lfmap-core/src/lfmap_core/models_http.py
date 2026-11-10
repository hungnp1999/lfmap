"""OpenAI-compatible HTTP implementation of `ModelClient` on the standard library.

Proxy environment variables are ignored and redirects are refused: a redirect could move the request, and the API
key, to another host. https verifies certificates with the default context. Errors are `ToolError` only and never
carry the request or the API key.
"""

import json
import math
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from lfmap_core.errors import ToolError
from lfmap_core.models import (
    MAX_CONTENT_CHARS,
    MAX_EMBED_BATCH,
    MAX_TOKENS_LIMIT,
    TIMEOUT_SECONDS,
    ChatMessage,
    ChatResult,
    ModelEndpoint,
)

ERROR_BODY_CHARS = 500
MAX_RESPONSE_BYTES = 64 * 1024 * 1024


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001, ANN201
        return None


def _bad_response(message: str = "The model endpoint returned an unexpected response") -> ToolError:
    return ToolError("backend_unavailable", message, {"reason": "bad_response"})


def _is_timeout(error: BaseException) -> bool:
    reason = error.reason if isinstance(error, urllib.error.URLError) else error
    return isinstance(reason, TimeoutError)


class OpenAICompatibleClient:
    """`POST {base_url}/chat/completions` and `/embeddings`."""

    def __init__(
        self,
        base_url: str,
        *,
        chat_model: str | None = None,
        embed_model: str | None = None,
        api_key: str | None = None,
        timeout: float = TIMEOUT_SECONDS,
    ) -> None:
        parts = urllib.parse.urlsplit(base_url)
        if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
            raise ToolError("invalid_input", "Model endpoint must be an http(s) URL without user info")
        self.base_url = base_url.rstrip("/")
        self.chat_model = chat_model
        self.embed_model = embed_model
        self.timeout = timeout
        self._api_key = api_key or None
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        json_mode: bool = False,
    ) -> ChatResult:
        name = model or self.chat_model
        if not name:
            raise ToolError("invalid_input", "No chat model is configured for this endpoint")
        if not messages:
            raise ToolError("invalid_input", "messages must not be empty")
        if sum(len(message.content) for message in messages) > MAX_CONTENT_CHARS:
            raise ToolError("invalid_input", f"Message content is limited to {MAX_CONTENT_CHARS} characters")
        if isinstance(max_tokens, bool) or not 1 <= max_tokens <= MAX_TOKENS_LIMIT:
            raise ToolError("invalid_input", f"max_tokens must be an integer from 1 to {MAX_TOKENS_LIMIT}")
        if not isinstance(temperature, int | float) or isinstance(temperature, bool) or not 0 <= temperature <= 2:
            raise ToolError("invalid_input", "temperature must be a number from 0 to 2")
        body: dict[str, Any] = {
            "model": name,
            "messages": [message.model_dump() for message in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        data = self._post("/chat/completions", body)
        return _parse_chat(data, name)

    def embed(self, texts: list[str], *, model: str | None = None) -> list[list[float]]:
        if not texts:
            return []
        name = model or self.embed_model
        if not name:
            raise ToolError("invalid_input", "No embedding model is configured for this endpoint")
        if len(texts) > MAX_EMBED_BATCH:
            raise ToolError("invalid_input", f"At most {MAX_EMBED_BATCH} texts per embed call")
        if sum(len(text) for text in texts) > MAX_CONTENT_CHARS:
            raise ToolError("invalid_input", f"Text is limited to {MAX_CONTENT_CHARS} characters per call")
        data = self._post("/embeddings", {"model": name, "input": texts})
        return _parse_embeddings(data, len(texts))

    def _post(self, path: str, body: dict[str, Any]) -> Any:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        request = urllib.request.Request(
            self.base_url + path, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST"
        )
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as error:
            raise ToolError(
                "backend_unavailable",
                f"The model endpoint answered HTTP {error.code}",
                {"reason": f"http_{error.code}", "body": self._error_body(error)},
            ) from None
        except (OSError, ValueError) as error:  # URLError and TimeoutError are OSError
            reason = "timeout" if _is_timeout(error) else "unreachable"
            raise ToolError(
                "backend_unavailable", f"The model endpoint is not reachable ({reason})", {"reason": reason}
            ) from None
        if len(raw) > MAX_RESPONSE_BYTES:
            raise _bad_response("The model endpoint response is too large")
        try:
            return json.loads(raw)
        except ValueError:
            raise _bad_response() from None

    def _error_body(self, error: urllib.error.HTTPError) -> str:
        try:
            text = error.read(ERROR_BODY_CHARS * 4).decode("utf-8", "replace")
        except OSError:
            return ""
        if self._api_key:
            text = text.replace(self._api_key, "***")
        return text[:ERROR_BODY_CHARS]


def _parse_chat(data: Any, requested_model: str) -> ChatResult:
    try:
        choice = data["choices"][0]
        text = choice["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise _bad_response() from None
    if not isinstance(text, str):
        raise _bad_response()
    reason = choice.get("finish_reason")
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    model = data.get("model")
    return ChatResult(
        text=text,
        model=model if isinstance(model, str) and model else requested_model,
        finish_reason=reason if reason in ("stop", "length") else "other",
        prompt_tokens=_count(usage.get("prompt_tokens")),
        completion_tokens=_count(usage.get("completion_tokens")),
    )


def _count(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _parse_embeddings(data: Any, expected: int) -> list[list[float]]:
    items = data.get("data") if isinstance(data, dict) else None
    if not isinstance(items, list) or len(items) != expected or not all(isinstance(item, dict) for item in items):
        raise _bad_response()
    if all(isinstance(item.get("index"), int) for item in items):
        items = sorted(items, key=lambda item: item["index"])
        if [item["index"] for item in items] != list(range(expected)):
            raise _bad_response()
    vectors = [item.get("embedding") for item in items]
    for vector in vectors:
        if not isinstance(vector, list) or not vector:
            raise _bad_response()
        if not all(isinstance(x, int | float) and not isinstance(x, bool) and math.isfinite(x) for x in vector):
            raise _bad_response()
    return vectors


def build_client(endpoint: ModelEndpoint, environ: dict[str, str] | None = None) -> OpenAICompatibleClient:
    """Client for one configured endpoint; the key comes from the environment variable the config names."""
    key = None
    if endpoint.api_key_env:
        key = (environ if environ is not None else os.environ).get(endpoint.api_key_env)
        if not key:
            raise ToolError(
                "invalid_input",
                f"Environment variable {endpoint.api_key_env} is not set",
                {"variable": endpoint.api_key_env},
            )
    return OpenAICompatibleClient(
        endpoint.base_url, chat_model=endpoint.chat_model, embed_model=endpoint.embed_model, api_key=key
    )
