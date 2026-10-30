"""Event payloads: small JSON objects with string keys."""

import json
from typing import Any

from lfmap_core.errors import ToolError

MAX_PAYLOAD_BYTES = 65536


def _keys_are_strings(value: Any) -> bool:
    stack, seen = [value], set()
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            if id(item) in seen:
                return False
            seen.add(id(item))
            if not all(isinstance(key, str) for key in item):
                return False
            stack.extend(item.values())
        elif isinstance(item, list | tuple):
            if id(item) in seen:
                return False
            seen.add(id(item))
            stack.extend(item)
    return True


def encode_payload(payload: object) -> str:
    """Compact, key-sorted JSON text of `payload`, at most MAX_PAYLOAD_BYTES UTF-8 bytes."""
    if not isinstance(payload, dict):
        raise ToolError("invalid_input", "Event payload must be a JSON object", {"reason": "not_object"})
    if not _keys_are_strings(payload):
        raise ToolError("invalid_input", "Event payload is not JSON", {"reason": "not_json"})
    try:
        text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ToolError("invalid_input", "Event payload is not JSON", {"reason": "not_json"}) from error
    size = len(text.encode("utf-8"))
    if size > MAX_PAYLOAD_BYTES:
        raise ToolError(
            "invalid_input",
            "Event payload is too large",
            {"reason": "too_large", "bytes": size, "limit": MAX_PAYLOAD_BYTES},
        )
    return text


def _no_constant(name: str) -> Any:
    raise ValueError(name)


def decode_payload(text: str) -> dict[str, Any]:
    """The object stored by `encode_payload`."""
    if not isinstance(text, str):
        raise ToolError("invalid_input", "Event payload is not JSON", {"reason": "not_json"})
    try:
        value = json.loads(text, parse_constant=_no_constant)
    except ValueError as error:
        raise ToolError("invalid_input", "Event payload is not JSON", {"reason": "not_json"}) from error
    if not isinstance(value, dict):
        raise ToolError("invalid_input", "Event payload must be a JSON object", {"reason": "not_object"})
    return value
