"""The `web_fetch` line in `audit.jsonl` for each request of `web.fetch` (docs/specs/web-plugin.md section 8).

Only host, byte counts and a status: never the URL, page content, headers, cookies or resolved addresses.
"""

import re
from pathlib import Path
from typing import Any

from lfmap_core.approval import audit

_HOST = re.compile(r"^[a-z0-9.-]{1,253}$")


def web_audit(fields: dict[str, Any], path: Path | None = None) -> None:
    audit({"event": "web_fetch", **fields}, path)


def audit_host(host: Any) -> dict[str, str]:
    """`{"host": host}` when it is a plain host name, else nothing (a malformed host is never logged)."""
    return {"host": host} if isinstance(host, str) and _HOST.match(host) else {}
