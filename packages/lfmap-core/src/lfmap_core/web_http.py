"""`WebFetcher`: HTTPS GET of one page from an owner-listed host (docs/specs/web-plugin.md sections 4 to 10).

Order of checks per request (spec section 5): network permission, per-run cap, URL syntax, allow-list, rate limit,
DNS and address check, `sent` audit line, connect to the checked address, TLS with host-name verification, bounded
read. Every redirect hop starts again at the URL check. One wall-clock deadline covers DNS, connect, TLS, headers,
body and every hop. Standard library only; the socket is opened here, so proxy variables have no path in, and
there is no cookie jar and no connection reuse. Only gzip and deflate bodies are decompressed, with `zlib`, in
bounded steps: the byte cap counts decompressed output (spec section 4, Compression).

The resolver, SSL context, clock, `NetworkPolicy` and `port` are keyword-only test seams. `runtime.py` builds the
fetcher with the defaults and hands the plugin a `WebAccess` that exposes `fetch` only.
"""

import codecs
import contextlib
import http.client
import ipaddress
import re
import socket
import ssl
import threading
import time
import urllib.parse
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, NoReturn

from lfmap_core import __version__
from lfmap_core.config import app_dir
from lfmap_core.errors import ErrorCode, ToolError
from lfmap_core.web import MAX_URL_CHARS, TEXT_TYPES, WebConfig, WebResult, check_url
from lfmap_core.web_egress import audit_host, web_audit
from lfmap_core.web_rate import RateLimiter

ERROR_BODY_CHARS = 500
READ_CHUNK = 65536
WIRE_SLACK = 65536
REDIRECTS = frozenset({301, 302, 303, 307, 308})
ACCEPT = "text/html,text/plain,text/xml,application/xml,application/xhtml+xml,application/json,text/csv;q=0.9,*/*;q=0.1"
_NAT64 = ipaddress.IPv6Network("64:ff9b::/96")
_STATUS = re.compile(r"^[a-z0-9_]{1,40}$")

Address = ipaddress.IPv4Address | ipaddress.IPv6Address
Resolver = Callable[[str, int], list[str]]


@dataclass(frozen=True)
class NetworkPolicy:
    """Tests on loopback set `allow_non_global`; production never does (runtime.py passes no policy)."""

    allow_non_global: bool = False


def system_resolver(host: str, port: int) -> list[str]:
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
    return [str(info[4][0]) for info in infos]


def is_public(address: Address) -> bool:
    """Globally routable, after unwrapping IPv4-mapped, NAT64 and 6to4 forms."""
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            return is_public(address.ipv4_mapped)
        if address in _NAT64:
            return is_public(ipaddress.IPv4Address(int(address) & 0xFFFFFFFF))
        if address.sixtofour is not None and not is_public(address.sixtofour):
            return False
        if address.is_site_local:
            return False
    special = (
        address.is_private,
        address.is_loopback,
        address.is_link_local,
        address.is_multicast,
        address.is_reserved,
        address.is_unspecified,
    )
    return address.is_global and not any(special)


def _error(code: ErrorCode, reason: str, message: str, **details: Any) -> ToolError:
    return ToolError(code, message, {"reason": reason, **details})


def _unavailable(reason: str, message: str, **details: Any) -> ToolError:
    return _error("backend_unavailable", reason, message, **details)


def _timeout() -> ToolError:
    return _unavailable("timeout", "The page did not answer within timeout_s")


def _remaining(deadline: float) -> float:
    left = deadline - time.monotonic()
    if left <= 0:
        raise _timeout()
    return left


def _reason(error: ToolError) -> str:
    reason = error.details.get("reason") if isinstance(error.details, dict) else None
    return reason if isinstance(reason, str) and _STATUS.match(reason) else "error"


def _host_of(url: Any) -> str | None:
    try:
        return urllib.parse.urlsplit(url).hostname if isinstance(url, str) else None
    except ValueError:
        return None


def _media_type(value: str | None) -> str:
    return (value or "").split(";", 1)[0].strip().lower()


def _charset(value: str | None) -> str:
    for param in (value or "").split(";")[1:]:
        name, _, charset = param.partition("=")
        if name.strip().lower() == "charset":
            return charset.strip().strip("\"'") or "utf-8"
    return "utf-8"


def _decode(body: bytes, content_type: str | None, truncated: bool) -> str:
    """Charset from the header, else UTF-8; an unknown or non-text codec falls back to UTF-8. Never sniffs."""
    try:
        text = codecs.getincrementaldecoder(_charset(content_type))(errors="replace").decode(body, final=not truncated)
    except (LookupError, TypeError, ValueError):
        text = None
    if isinstance(text, str):
        return text
    return codecs.getincrementaldecoder("utf-8")(errors="replace").decode(body, final=not truncated)


def _printable(value: str, limit: int = 50) -> str:
    return "".join(char if " " <= char <= "~" else "?" for char in value[:limit])


def _refused(header: str, value: str) -> ToolError:
    return _unavailable("bad_response", f"Unsupported {header} from the page: {_printable(value)}")


def _coding(response: http.client.HTTPResponse) -> str:
    """`identity`, `gzip` or `deflate` for an accepted pair of headers; otherwise the refusal (spec section 4)."""
    transfer = (response.getheader("Transfer-Encoding") or "").strip()
    if transfer.lower() not in ("", "identity", "chunked"):
        raise _refused("Transfer-Encoding", transfer)
    content = (response.getheader("Content-Encoding") or "").strip()
    token = content.lower()
    if token in ("", "identity"):
        return "identity"
    if token in ("gzip", "x-gzip"):
        return "gzip"
    if token == "deflate":
        return "deflate"
    raise _refused("Content-Encoding", content)


class _Inflater:
    """Incremental gzip or deflate decoder; output per call is bounded by `room`, however small the input."""

    def __init__(self, coding: str) -> None:
        self._coding = coding
        self._head = b""
        self._z: Any = None
        self.eof = False

    def feed(self, data: bytes, room: int) -> bytes:
        if self._z is None:
            self._head += data
            if len(self._head) < 2:
                return b""
            self._z = zlib.decompressobj(self._wbits(self._head))
            data, self._head = self._head, b""
        out: list[bytes] = []
        while data and room > 0 and not self._z.eof:
            piece = self._z.decompress(data, min(room, READ_CHUNK))
            out.append(piece)
            room -= len(piece)
            if len(self._z.unconsumed_tail) >= len(data) and not piece:
                break  # no progress: cannot happen with a positive max_length, so never spin
            data = self._z.unconsumed_tail
        self.eof = self._z.eof
        return b"".join(out)

    def _wbits(self, head: bytes) -> int:
        if self._coding == "gzip":
            return 31
        zlib_header = head[0] & 0x0F == 8 and head[0] >> 4 <= 7 and (head[0] * 256 + head[1]) % 31 == 0
        return 15 if zlib_header else -15  # deflate: zlib-wrapped, else a raw stream


def _request(host: str, target: str) -> bytes:
    lines = (
        f"GET {target} HTTP/1.1",
        f"Host: {host}",
        f"User-Agent: lfmap-web/{__version__}",
        f"Accept: {ACCEPT}",
        "Accept-Encoding: gzip, deflate",
        "Connection: close",
    )
    return ("\r\n".join(lines) + "\r\n\r\n").encode("ascii")


class _Watchdog:
    """Shuts the current socket down at the deadline, so no slow read can outlive `timeout_s`."""

    def __init__(self, deadline: float) -> None:
        self.fired = False
        self._sock: socket.socket | None = None
        self._lock = threading.Lock()
        self._timer = threading.Timer(max(0.0, deadline - time.monotonic()), self._fire)
        self._timer.daemon = True

    def __enter__(self) -> "_Watchdog":
        self._timer.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._timer.cancel()

    def arm(self, sock: socket.socket) -> None:
        with self._lock:
            self._sock = sock
            if self.fired:
                self._shut()

    def _fire(self) -> None:
        with self._lock:
            self.fired = True
            self._shut()

    def _shut(self) -> None:
        if self._sock is not None:
            with contextlib.suppress(OSError):
                socket.socket.shutdown(self._sock, socket.SHUT_RDWR)


@dataclass
class _Progress:
    bytes_in: int = 0


class WebFetcher:
    def __init__(
        self,
        config: WebConfig,
        *,
        plugin_id: str,
        channel: str,
        permissions: Any,
        operation: str = "",
        resolver: Resolver | None = None,
        ssl_context: ssl.SSLContext | None = None,
        clock: Callable[[], float] | None = None,
        policy: NetworkPolicy | None = None,
        port: int = 443,
    ) -> None:
        context = ssl_context if ssl_context is not None else ssl.create_default_context()
        if context.verify_mode != ssl.CERT_REQUIRED or not context.check_hostname:
            raise ValueError("The web fetcher needs certificate and host-name verification")
        if context.minimum_version < ssl.TLSVersion.TLSv1_2:
            context.minimum_version = ssl.TLSVersion.TLSv1_2
        self._config = config
        self._allowed = frozenset(config.allowed_hosts)
        self._line = {"channel": channel, "plugin": plugin_id, **({"operation": operation} if operation else {})}
        self._permissions = permissions
        self._resolver = resolver if resolver is not None else system_resolver
        self._ssl = context
        self._clock = clock if clock is not None else time.time
        self._policy = policy if policy is not None else NetworkPolicy()
        self._port = port
        self._rate = RateLimiter(app_dir() / "web_rate.db", config.rate_limit_per_host, self._clock)
        self._calls = 0

    def fetch(self, url: str, *, max_bytes: int | None = None) -> WebResult:
        """GET `url` and return its text; ToolError with a `reason` of spec section 10 otherwise."""
        self._permissions.require_network()
        cap = self._cap(max_bytes)
        if self._calls >= self._config.max_calls_per_run:
            self._note({"bytes_in": 0, "status": "run_limit"})
            raise _unavailable("run_limit", "max_calls_per_run reached for this run")
        self._calls += 1
        deadline = time.monotonic() + self._config.timeout_s
        current: Any = url
        hops = self._config.max_redirects
        for hop in range(hops + 1):
            outcome = self._hop(current, cap, deadline, redirect=hop > 0, last=hop == hops)
            if isinstance(outcome, WebResult):
                return outcome
            current = outcome
        raise _unavailable("too_many_redirects", "Too many redirects")  # not reached: the last hop raises

    def _cap(self, max_bytes: Any) -> int:
        if max_bytes is None:
            return self._config.max_bytes
        if type(max_bytes) is not int or not 1024 <= max_bytes <= self._config.max_bytes:
            raise _error("invalid_input", "max_bytes", f"max_bytes must be 1024 to {self._config.max_bytes}")
        return max_bytes

    def _hop(self, url: Any, cap: int, deadline: float, *, redirect: bool, last: bool) -> WebResult | str:
        try:
            checked = check_url(url)
        except ToolError:
            if not redirect:
                raise  # a malformed URL from the caller writes no audit line
            self._refuse("redirect_not_allowed", _host_of(url), "The redirect target is not allowed")
        if checked.host not in self._allowed:
            reason = "redirect_not_allowed" if redirect else "host_not_allowed"
            self._refuse(reason, checked.host, f"{checked.host} is not in [web] allowed_hosts")
        try:
            self._rate.acquire(checked.host)
            addresses = self._addresses(checked.host, deadline)
        except ToolError as error:
            self._note({**audit_host(checked.host), "bytes_in": 0, "status": _reason(error)})
            raise
        request = _request(checked.host, checked.target)
        line = {"host": checked.host, "bytes_out": len(request)}
        try:
            web_audit({**self._line, **line, "status": "sent"})
        except OSError:
            raise _unavailable("audit_failed", "The egress record could not be written") from None
        progress = _Progress()
        try:
            outcome = self._exchange(checked.url, addresses, request, cap, deadline, last, progress)
        except ToolError as error:
            self._note({**line, "bytes_in": progress.bytes_in, "status": _reason(error)})
            raise
        if isinstance(outcome, str):
            self._note({**line, "bytes_in": 0, "status": "redirect"})
        else:
            self._note({**line, "bytes_in": outcome.bytes, "status": "ok"})
        return outcome

    def _refuse(self, reason: str, host: Any, message: str) -> NoReturn:
        self._note({**audit_host(host), "bytes_in": 0, "status": reason})
        raise _error("permission_denied", reason, message)

    def _note(self, fields: dict[str, Any]) -> None:
        with contextlib.suppress(OSError):  # a refusal or a result: the call's outcome does not depend on it
            web_audit({**self._line, **fields})

    def _addresses(self, host: str, deadline: float) -> list[Address]:
        """Spec step 6: resolve once under the deadline; every address must be globally routable."""
        addresses: list[Address] = []
        for text in self._resolve(host, deadline):
            try:
                address = ipaddress.ip_address(text)
            except ValueError:
                raise _unavailable("unreachable", f"{host} did not resolve to an address") from None
            if not self._policy.allow_non_global and not is_public(address):
                raise _error("permission_denied", "blocked_address", f"{host} resolves to a non-public address")
            addresses.append(address)
        return addresses

    def _resolve(self, host: str, deadline: float) -> list[str]:
        box: dict[str, Any] = {}

        def work() -> None:
            try:
                box["answer"] = list(self._resolver(host, self._port))
            except Exception as error:  # noqa: BLE001 - reported as unreachable below
                box["error"] = error

        worker = threading.Thread(target=work, name="lfmap-web-dns", daemon=True)
        worker.start()
        worker.join(max(0.0, deadline - time.monotonic()))
        if worker.is_alive():
            raise _timeout()  # the thread is abandoned; getaddrinfo cannot be cancelled
        answer = box.get("answer")
        if not answer or "error" in box:
            raise _unavailable("unreachable", f"{host} could not be resolved")
        return answer

    def _exchange(
        self,
        url: str,
        addresses: list[Address],
        request: bytes,
        cap: int,
        deadline: float,
        last: bool,
        progress: _Progress,
    ) -> WebResult | str:
        tls: ssl.SSLSocket | None = None
        with _Watchdog(deadline) as watch:
            try:
                tls = self._connect(url, addresses, deadline, watch)
                return self._respond(tls, url, request, cap, deadline, last, progress, watch)
            except ToolError as error:
                if watch.fired and _reason(error) in ("unreachable", "tls", "bad_response"):
                    raise _timeout() from None
                raise
            except TimeoutError:
                raise _timeout() from None
            except http.client.HTTPException:
                raise (_timeout() if watch.fired else _unavailable("bad_response", "Malformed response")) from None
            except ssl.SSLError:
                raise (_timeout() if watch.fired else _unavailable("tls", "TLS failed")) from None
            except OSError:
                raise (_timeout() if watch.fired else _unavailable("unreachable", "Connection failed")) from None
            finally:
                if tls is not None:
                    with contextlib.suppress(OSError):
                        tls.close()

    def _connect(self, url: str, addresses: list[Address], deadline: float, watch: _Watchdog) -> ssl.SSLSocket:
        """Spec step 7: connect to an address checked in step 6, never to the name; TLS for the allowed host."""
        # Repeated inline on the variable that reaches the socket (CLAUDE.md): https, no userinfo, port 443, listed.
        parts = urllib.parse.urlsplit(url)
        host = parts.hostname or ""
        if parts.scheme != "https" or "@" in parts.netloc or parts.port not in (None, 443) or host not in self._allowed:
            raise _error("permission_denied", "host_not_allowed", "The URL is not allowed")
        for address in addresses:
            if not self._policy.allow_non_global and not is_public(address):
                raise _error("permission_denied", "blocked_address", f"{host} resolves to a non-public address")
            family = socket.AF_INET6 if address.version == 6 else socket.AF_INET
            sock = socket.socket(family, socket.SOCK_STREAM)
            watch.arm(sock)
            try:
                sock.settimeout(_remaining(deadline))
                sock.connect((str(address), self._port))
            except (OSError, ToolError):
                sock.close()
                if time.monotonic() >= deadline:
                    raise _timeout() from None
                continue
            try:
                tls = self._ssl.wrap_socket(sock, server_hostname=host)
            except TimeoutError:
                sock.close()
                raise _timeout() from None
            except ssl.SSLError:
                sock.close()
                failure = _timeout() if watch.fired else _unavailable("tls", f"TLS verification failed for {host}")
                raise failure from None
            watch.arm(tls)
            return tls
        raise _unavailable("unreachable", f"No address of {host} accepted a connection")

    def _respond(
        self,
        tls: ssl.SSLSocket,
        url: str,
        request: bytes,
        cap: int,
        deadline: float,
        last: bool,
        progress: _Progress,
        watch: _Watchdog,
    ) -> WebResult | str:
        tls.settimeout(_remaining(deadline))
        tls.sendall(request)
        response = http.client.HTTPResponse(tls, method="GET")
        response.begin()
        if watch.fired:
            raise _timeout()
        status = response.status
        if status in REDIRECTS:
            return self._location(response, url, last)
        content_type = response.getheader("Content-Type")
        media = _media_type(content_type)
        try:
            coding: str | None = _coding(response)
            refusal = None
        except ToolError as error:
            coding, refusal = None, error
        if not 200 <= status <= 299:
            body = b""
            if coding is not None and media in TEXT_TYPES:
                try:
                    body, _ = self._read(tls, response, ERROR_BODY_CHARS, deadline, progress, watch, coding)
                except ToolError as error:
                    if _reason(error) != "bad_response" or watch.fired:
                        raise
            text = body.decode("utf-8", errors="replace")[:ERROR_BODY_CHARS]
            raise _unavailable(f"http_{status}", f"The page answered HTTP {status}", status=status, body=text)
        if coding is None:
            raise refusal  # type: ignore[misc]
        if media not in TEXT_TYPES:
            raise _unavailable("unsupported_content_type", "Only text pages are fetched", content_type=media[:100])
        body, truncated = self._read(tls, response, cap, deadline, progress, watch, coding)
        return WebResult(
            url_final=url,
            status=status,
            content_type=media,
            text=_decode(body, content_type, truncated),
            bytes=len(body),
            truncated=truncated,
            fetched_at=datetime.fromtimestamp(self._clock(), UTC).isoformat(timespec="seconds"),
        )

    @staticmethod
    def _location(response: http.client.HTTPResponse, url: str, last: bool) -> str:
        if last:
            raise _unavailable("too_many_redirects", "Too many redirects")
        location = response.getheader("Location")
        if not location or len(location) > MAX_URL_CHARS:
            raise _unavailable("bad_response", "The redirect has no usable Location")
        try:
            return urllib.parse.urljoin(url, location.strip())
        except ValueError:
            raise _unavailable("bad_response", "The redirect has no usable Location") from None

    @staticmethod
    def _read(
        tls: ssl.SSLSocket,
        response: http.client.HTTPResponse,
        cap: int,
        deadline: float,
        progress: _Progress,
        watch: _Watchdog,
        coding: str = "identity",
    ) -> tuple[bytes, bool]:
        """At most `cap` body bytes (decompressed), and True when more was on offer. Stops at the cap whatever
        Content-Length says. A compressed body is decoded in bounded steps; wire bytes are bounded by cap + 64 KiB."""
        if coding != "identity":
            return WebFetcher._read_compressed(tls, response, cap, deadline, progress, watch, coding)
        chunks: list[bytes] = []
        size = 0
        more = False
        while size < cap:
            tls.settimeout(_remaining(deadline))
            data = response.read1(min(READ_CHUNK, cap - size))
            if not data:
                break
            chunks.append(data)
            size += len(data)
            progress.bytes_in = size
        else:
            if response.length != 0:
                tls.settimeout(_remaining(deadline))
                more = bool(response.read1(1))
        if watch.fired:
            raise _timeout()
        return b"".join(chunks), more

    @staticmethod
    def _read_compressed(
        tls: ssl.SSLSocket,
        response: http.client.HTTPResponse,
        cap: int,
        deadline: float,
        progress: _Progress,
        watch: _Watchdog,
        coding: str,
    ) -> tuple[bytes, bool]:
        corrupt = "The compressed page is corrupt or ended early"
        inflater = _Inflater(coding)
        limit = cap + WIRE_SLACK
        out = bytearray()
        wire = 0
        try:
            while len(out) <= cap:  # one byte past the cap shows there was more
                tls.settimeout(_remaining(deadline))
                data = response.read1(min(READ_CHUNK, limit - wire + 1))
                if not data:
                    if inflater.eof:
                        break
                    raise _unavailable("bad_response", corrupt)
                wire += len(data)
                if wire > limit:
                    raise _unavailable("bad_response", "The compressed page is too large for max_bytes")
                out += inflater.feed(data, cap + 1 - len(out))
                progress.bytes_in = min(len(out), cap)
                if inflater.eof and len(out) <= cap:
                    break
        except zlib.error:
            raise _unavailable("bad_response", corrupt) from None
        if watch.fired:
            raise _timeout()
        more = len(out) > cap
        del out[cap:]
        return bytes(out), more


class WebAccess:
    """What a plugin gets as `ctx.web`: `fetch` only, read-only, nothing that reaches the fetcher's settings."""

    __slots__ = ("fetch",)
    fetch: Callable[..., WebResult]

    def __init__(self, fetch: Callable[..., WebResult]) -> None:
        object.__setattr__(self, "fetch", fetch)

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("ctx.web is read-only")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("ctx.web is read-only")


def web_access(factory: Callable[[], WebFetcher]) -> WebAccess:
    """Wrap a fetcher factory; the fetcher (and the `[web]` config check) is built on the first fetch."""
    built: list[WebFetcher] = []
    lock = threading.Lock()

    def fetch(url: str, *, max_bytes: int | None = None) -> WebResult:
        with lock:
            if not built:
                built.append(factory())
        return built[0].fetch(url, max_bytes=max_bytes)

    return WebAccess(fetch)
