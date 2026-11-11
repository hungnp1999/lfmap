"""Model access: the `ModelClient` Protocol, endpoint configuration and the routing table.

`[models]` in `config.toml` is routing policy as data (docs/specs/model-client.md §4). A `local` endpoint must be
loopback; a `cloud` endpoint must be https and is reachable only through a route that names it. The owner edits the
file by hand; no operation writes it.
"""

import ipaddress
import re
import urllib.parse
from typing import Any, Literal, Protocol, Self, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from lfmap_core.errors import ToolError

MAX_CONTENT_CHARS = 200_000
MAX_TOKENS_LIMIT = 8192
MAX_EMBED_BATCH = 1024
TIMEOUT_SECONDS = 120
DEFAULT_LOCAL_URL = "http://127.0.0.1:11434/v1"
DEFAULT_EMBED_MODEL = "bge-m3"

_NAME = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatResult(BaseModel):
    text: str
    model: str
    finish_reason: Literal["stop", "length", "other"]
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


@runtime_checkable
class ModelClient(Protocol):
    def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        json_mode: bool = False,
    ) -> ChatResult: ...

    def embed(self, texts: list[str], *, model: str | None = None) -> list[list[float]]: ...


def is_loopback_url(url: str) -> bool:
    """True for http(s) to `localhost` or a loopback IP, with no user info."""
    try:
        parts = urllib.parse.urlsplit(url)
        host = parts.hostname or ""
    except ValueError:
        return False
    if parts.scheme not in ("http", "https") or parts.username or parts.password:
        return False
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class ModelEndpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["local", "cloud"]
    base_url: str
    chat_model: str | None = None
    embed_model: str | None = None
    api_key_env: str | None = None

    @model_validator(mode="after")
    def _check(self) -> Self:
        parts = urllib.parse.urlsplit(self.base_url)
        if self.kind == "local" and not is_loopback_url(self.base_url):
            raise ValueError("a local endpoint must be http(s) to localhost or a loopback IP")
        if self.kind == "cloud" and (parts.scheme != "https" or not parts.hostname or parts.username or parts.password):
            raise ValueError("a cloud endpoint must be an https URL without user info")
        if parts.query or parts.fragment:
            raise ValueError("base_url must not contain a query or fragment")
        if self.api_key_env is not None and not _ENV_NAME.match(self.api_key_env):
            raise ValueError("api_key_env is the name of an environment variable, never the key itself")
        return self


class ModelsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    endpoints: dict[str, ModelEndpoint]
    routes: dict[str, str] = Field(default_factory=dict)
    allow_cloud_unlabelled: bool = False

    @model_validator(mode="after")
    def _check(self) -> Self:
        for name in (*self.endpoints, *self.routes):
            if not _NAME.match(name):
                raise ValueError(f"{name!r} must be lowercase letters, digits and underscore")
        for task, endpoint in self.routes.items():
            if endpoint not in self.endpoints:
                raise ValueError(f"route {task!r} names unknown endpoint {endpoint!r}")
            if self.endpoints[endpoint].kind != "cloud":
                continue
            if task == "embed":
                raise ValueError("embeddings stay local: route 'embed' to a local endpoint")
            if not self.allow_cloud_unlabelled:
                raise ValueError(
                    f"route {task!r} to a cloud endpoint is refused until data labels travel with data;"
                    " the owner may set allow_cloud_unlabelled = true knowingly"
                )
        return self

    def route(self, task: str) -> tuple[str, ModelEndpoint]:
        """Endpoint name and endpoint for `task`; falls back to `routes.default`, never to another endpoint."""
        name = self.routes.get(task) or self.routes.get("default")
        if name is None:
            raise ToolError("invalid_input", f"No model route for task {task!r} and no default route", {"task": task})
        return name, self.endpoints[name]


def default_models_config() -> ModelsConfig:
    """What a user who writes no `[models]` table gets: one local endpoint, embeddings only."""
    endpoint = ModelEndpoint(kind="local", base_url=DEFAULT_LOCAL_URL, embed_model=DEFAULT_EMBED_MODEL)
    return ModelsConfig(endpoints={"local": endpoint}, routes={"default": "local"})


def load_models_config(config: dict[str, Any]) -> ModelsConfig:
    """Validate the `[models]` table of a loaded `config.toml`; invalid_input names the first problem."""
    table = config.get("models")
    if not table:
        return default_models_config()
    if not isinstance(table, dict):
        raise ToolError("invalid_input", "[models] must be a table")
    try:
        return ModelsConfig.model_validate(table)
    except ValidationError as error:
        first = error.errors()[0]
        where = ".".join(str(part) for part in first["loc"])
        raise ToolError(
            "invalid_input",
            f"Invalid [models] configuration{f' at {where}' if where else ''}: {first['msg']}",
            {"location": where},
        ) from None
