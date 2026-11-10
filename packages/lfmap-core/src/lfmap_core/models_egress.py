"""The `model_call` line in `audit.jsonl` for every call that reaches a cloud endpoint (spec section 6).

Only allow-listed fields are written (`AUDIT_FIELDS`): never message content, vectors or API keys.
"""

import re
from pathlib import Path
from typing import Any

from lfmap_core.approval import audit
from lfmap_core.errors import ToolError

_REASON = re.compile(r"^(unreachable|timeout|bad_response|http_\d{3})$")


def egress(fields: dict[str, Any], path: Path | None = None) -> None:
    audit({"event": "model_call", **fields}, path)


def failure_reason(error: ToolError) -> str:
    """The client's fixed `reason` code, or "error"; never the message or the response body."""
    reason = error.details.get("reason") if isinstance(error.details, dict) else None
    return reason if isinstance(reason, str) and _REASON.match(reason) else "error"
