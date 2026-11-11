"""`ModelRouter`: what a plugin gets as `ctx.models` (docs/specs/model-client.md sections 4 to 6).

A plugin names a task, never a URL or an endpoint. The router resolves the task through `[models]`, applies the
data-class rule, the manifest permissions and the T3 gate before any socket is opened, and writes the egress
lines around a cloud call. There is no fallback from one endpoint to another.
"""

import contextlib
import json
import urllib.parse
from collections.abc import Callable
from typing import Any

from lfmap_core.approval import DATA_LEVELS
from lfmap_core.errors import ToolError
from lfmap_core.models import ChatMessage, ChatResult, ModelClient, ModelEndpoint, ModelsConfig, load_models_config
from lfmap_core.models_egress import egress, failure_reason
from lfmap_core.models_http import build_client

ClientFactory = Callable[[ModelEndpoint], ModelClient]


def _size(text: str) -> int:
    return len(text.encode("utf-8"))


class ModelRouter:
    def __init__(
        self,
        config: dict[str, Any],
        *,
        plugin_id: str,
        channel: str,
        permissions: Any,
        cloud_ai: bool,
        approve: Callable[..., None],
        operation: str = "",
        client_factory: ClientFactory = build_client,
    ) -> None:
        self._config = config
        self._plugin_id = plugin_id
        self._channel = channel
        self._operation = operation
        self._permissions = permissions
        self._cloud_ai = cloud_ai
        self._approve = approve
        self._factory = client_factory
        self._models: ModelsConfig | None = None

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        task: str,
        data: str = "normal",
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        json_mode: bool = False,
    ) -> ChatResult:
        def send(client: ModelClient) -> ChatResult:
            return client.chat(
                messages, model=model, temperature=temperature, max_tokens=max_tokens, json_mode=json_mode
            )

        out = sum(_size(message.content) for message in messages)
        return self._call(
            task, data, out, send, lambda r: _size(r.text), lambda r: r.model, lambda e: model or e.chat_model
        )

    def embed(
        self, texts: list[str], *, task: str, data: str = "normal", model: str | None = None
    ) -> list[list[float]]:
        if not texts:
            return []

        def send(client: ModelClient) -> list[list[float]]:
            return client.embed(texts, model=model)

        out = sum(_size(text) for text in texts)
        return self._call(
            task, data, out, send, lambda v: _size(json.dumps(v)), lambda v: None, lambda e: model or e.embed_model
        )

    def _call(self, task, data, bytes_out, send, bytes_in, model_of, default_model):  # noqa: ANN001, ANN202
        if data not in DATA_LEVELS:
            raise ToolError("invalid_input", f"data must be one of {', '.join(DATA_LEVELS)}")
        if not isinstance(task, str) or not task:
            raise ToolError("invalid_input", "task must be a non-empty string")
        if self._models is None:
            self._models = load_models_config(self._config)
        name, endpoint = self._models.route(task)
        if endpoint.kind == "local":
            self._permissions.require_network()
            return send(self._factory(endpoint))
        if task == "embed":
            raise ToolError("invalid_input", "Embeddings stay local: the embed task cannot use a cloud endpoint")
        if data == "secret":
            raise ToolError(
                "permission_denied", "Secret data is never sent to a cloud endpoint", {"task": task, "data": data}
            )
        if not self._cloud_ai:
            raise ToolError(
                "permission_denied",
                "This plugin cannot use cloud models; set [permissions] cloud_ai = true in its manifest",
                {"plugin": self._plugin_id},
            )
        self._permissions.require_network()
        client = self._factory(endpoint)  # a missing API key fails here, before anyone is asked
        host = (urllib.parse.urlsplit(endpoint.base_url).hostname or "").lower()
        self._approve(
            "external",
            f"{self._plugin_id} sends text to a cloud model (task {task})",
            destination=host,
            data=data,
        )
        line = {
            "channel": self._channel,
            "plugin": self._plugin_id,
            **({"operation": self._operation} if self._operation else {}),
            "endpoint": name,
            "host": host,
            "data": data,
            "bytes_out": bytes_out,
        }
        model = default_model(endpoint)
        try:
            egress({**line, **({"model": model} if model else {}), "status": "sent"})
        except OSError:
            raise ToolError(
                "backend_unavailable", "The egress record could not be written", {"reason": "audit_failed"}
            ) from None
        try:
            result = send(client)
        except ToolError as error:
            self._finish({**line, "status": "error", "reason": failure_reason(error), **_opt(model)})
            raise
        answered = model_of(result) or model
        self._finish({**line, "status": "ok", "bytes_in": bytes_in(result), **_opt(answered)})
        return result

    @staticmethod
    def _finish(fields: dict[str, Any]) -> None:
        with contextlib.suppress(OSError):  # the response is in hand; the `sent` line already records the call
            egress(fields)


def _opt(model: str | None) -> dict[str, str]:
    return {"model": model} if model else {}
