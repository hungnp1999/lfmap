"""Socket guard for exclusion criterion E2: only loopback connections; anything else is recorded and refused."""

import socket
from dataclasses import dataclass, field
from ipaddress import ip_address

LOOPBACK_NAMES = {"localhost", "localhost.localdomain", "ip6-localhost"}


def is_loopback(address: object) -> bool:
    """True for AF_UNIX paths, localhost names and loopback IPs; False for every other address."""
    if isinstance(address, str | bytes):
        return True
    if not isinstance(address, tuple) or not address:
        return False
    host = str(address[0]).strip("[]").split("%")[0]
    if host.lower() in LOOPBACK_NAMES:
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


@dataclass
class SocketGuard:
    """Context manager patching socket.socket.connect / connect_ex; `blocked` lists refused addresses."""

    blocked: list[str] = field(default_factory=list)
    allowed: list[str] = field(default_factory=list)

    def __enter__(self) -> "SocketGuard":
        self._connect = socket.socket.connect
        self._connect_ex = socket.socket.connect_ex
        guard = self

        def connect(sock: socket.socket, address: object) -> None:
            guard.check(address)
            return guard._connect(sock, address)

        def connect_ex(sock: socket.socket, address: object) -> int:
            guard.check(address)
            return guard._connect_ex(sock, address)

        socket.socket.connect = connect  # type: ignore[method-assign]
        socket.socket.connect_ex = connect_ex  # type: ignore[method-assign]
        return self

    def __exit__(self, *exc: object) -> None:
        socket.socket.connect = self._connect  # type: ignore[method-assign]
        socket.socket.connect_ex = self._connect_ex  # type: ignore[method-assign]

    def check(self, address: object) -> None:
        """Record address; raise ConnectionRefusedError unless it is loopback."""
        if is_loopback(address):
            self.allowed.append(repr(address))
            return
        self.blocked.append(repr(address))
        raise ConnectionRefusedError(f"socket guard: non-loopback connection refused: {address!r}")
