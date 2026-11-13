"""`[web]` config, host normalisation and URL checks for `web.fetch` (docs/specs/web-plugin.md sections 3 to 5).

Pure: no socket, no file. `check_url` is the early refusal before any I/O; the fetcher repeats the scheme, userinfo,
port and allow-list checks inline where it connects.
"""

import ipaddress
import re
import urllib.parse
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from lfmap_core.errors import ToolError

MAX_URL_CHARS = 2048
QUERY_T3_LIMIT = 200
"""Owner decision 16.1: a URL whose query, as sent, is longer than this makes `web.fetch` a T3 call."""

TEXT_TYPES = frozenset(
    {
        "text/html",
        "text/plain",
        "text/xml",
        "text/csv",
        "text/markdown",
        "application/xml",
        "application/xhtml+xml",
        "application/json",
        "application/rss+xml",
        "application/atom+xml",
    }
)
_LABEL = r"(?!-)[a-z0-9-]{1,63}(?<!-)"
HOST_RE = re.compile(rf"^(?=.{{1,253}}$){_LABEL}(?:\.{_LABEL})+$")
_NUMERIC_TLD = re.compile(r"\.[0-9]+$")
_PATH_SAFE = "/%:@!$&'()*+,;=-._~"
_QUERY_SAFE = _PATH_SAFE + "?"


class WebConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    allowed_hosts: list[str] = Field(default_factory=list)
    rate_limit_per_host: int = Field(12, ge=1, le=120)
    max_bytes: int = Field(2_097_152, ge=1024, le=10_485_760)
    timeout_s: int = Field(20, ge=1, le=60)
    max_redirects: int = Field(3, ge=0, le=5)
    max_calls_per_run: int = Field(100, ge=1, le=1000)

    @field_validator("allowed_hosts")
    @classmethod
    def _hosts(cls, hosts: list[str]) -> list[str]:
        return [_config_host(entry) for entry in hosts]


def _config_host(entry: str) -> str:
    if entry != entry.lower() or entry.endswith("."):
        raise ValueError(f"{entry!r} must be a lower-case host name")
    try:
        host = normalize_host(entry)
    except ToolError:
        raise ValueError(f"{entry!r} is not an exact host name (no scheme, port, path, '*', IP or localhost)") from None
    return host


def load_web_config(config: dict[str, Any]) -> WebConfig:
    """Validate `[web]` of a loaded `config.toml`; no table allows no host. invalid_input names the key."""
    table = config.get("web", {})
    if not isinstance(table, dict):
        raise ToolError("invalid_input", "[web] must be a table", {"reason": "bad_config", "key": "web"})
    try:
        return WebConfig.model_validate(table)
    except ValidationError as error:
        first = error.errors()[0]
        key = str(first["loc"][0]) if first["loc"] else "web"
        message = f"Invalid [web] configuration at {key}: {first['msg']}"
        raise ToolError("invalid_input", message, {"reason": "bad_config", "key": key}) from None


def _bad(reason: str, message: str) -> ToolError:
    return ToolError("invalid_input", message, {"reason": reason})


def normalize_host(name: str) -> str:
    """Lower-case IDNA (punycode) host name; invalid_input `ip_literal` or `bad_url` for anything else."""
    if _is_ip(name) or name == "localhost" or name.endswith(".localhost"):
        raise _bad("ip_literal", "The URL host must be a DNS name, not an IP address or localhost")
    try:
        host = name.encode("idna").decode("ascii").lower()
    except UnicodeError:
        raise _bad("bad_url", "The URL host is not a valid host name") from None
    if _NUMERIC_TLD.search(host):
        raise _bad("ip_literal", "The URL host must be a DNS name, not an IP address")
    if not HOST_RE.match(host):
        raise _bad("bad_url", "The URL host is not a valid host name")
    return host


def _is_ip(name: str) -> bool:
    try:
        ipaddress.ip_address(name)
    except ValueError:
        return False
    return True


@dataclass(frozen=True)
class CheckedURL:
    url: str
    host: str
    target: str


def check_url(url: Any) -> CheckedURL:
    """Spec section 5 step 3, before any I/O: an absolute https URL to a DNS name on port 443, no userinfo.

    Returns the URL rebuilt from checked parts (fragment dropped, non-ASCII path and query percent-encoded)."""
    if not isinstance(url, str) or not url or len(url) > MAX_URL_CHARS:
        raise _bad("bad_url", f"The URL must be a string of at most {MAX_URL_CHARS} characters")
    if any(char.isspace() or ord(char) < 0x20 or ord(char) == 0x7F for char in url):
        raise _bad("bad_url", "The URL must not contain spaces or control characters")
    if "\\" in url or url.startswith("//"):
        raise _bad("bad_url", "Network, device and backslash paths are refused")
    try:
        parts = urllib.parse.urlsplit(url)
        port = parts.port
    except ValueError as error:
        reason = "port" if "port" in str(error).lower() else "bad_url"
        raise _bad(reason, "The URL could not be parsed") from None
    if parts.scheme != "https":
        raise _bad("scheme", "Only https URLs are fetched")
    if "@" in parts.netloc:
        raise _bad("userinfo", "The URL must not contain user information")
    if not parts.hostname:
        raise _bad("bad_url", "The URL has no host")
    if parts.netloc.startswith("["):
        raise _bad("ip_literal", "The URL host must be a DNS name, not an IP address")
    if port is not None and port != 443:
        raise _bad("port", "Only the default https port 443 is allowed")
    host = normalize_host(parts.hostname)
    path = urllib.parse.quote(parts.path or "/", safe=_PATH_SAFE)
    query = urllib.parse.quote(parts.query, safe=_QUERY_SAFE)
    target = path + (f"?{query}" if query else "")
    return CheckedURL(url=f"https://{host}{target}", host=host, target=target)


def sent_query(url: str) -> str:
    """The query string of `url` as the fetcher sends it (fragment dropped, non-ASCII percent-encoded)."""
    try:
        query = urllib.parse.urlsplit(url).query
    except ValueError:
        return ""
    return urllib.parse.quote(query, safe=_QUERY_SAFE)


def long_query(url: str) -> bool:
    """True when the query of `url`, as sent, is longer than `QUERY_T3_LIMIT` (the call is then T3). Pure."""
    return len(sent_query(url)) > QUERY_T3_LIMIT


class WebResult(BaseModel):
    url_final: str
    status: int
    content_type: str
    text: str
    bytes: int
    truncated: bool
    fetched_at: str
