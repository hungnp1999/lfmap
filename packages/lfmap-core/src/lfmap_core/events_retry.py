"""Retry policy for event deliveries: backoff, retry-or-dead and a short error text."""

import math
from typing import Literal

from lfmap_core.errors import ToolError

PERMANENT_CODES = frozenset({"invalid_input", "permission_denied", "not_found"})


def _is_count(value: object) -> bool:
    return type(value) is int and value >= 1


def _is_positive(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def backoff_seconds(attempt: int, base: float = 2.0, cap: float = 300.0) -> float:
    """Seconds to wait after failed attempt `attempt`: base * 2**(attempt - 1), never more than `cap`."""
    if not _is_count(attempt):
        raise ToolError("invalid_input", "attempt must be an int >= 1", {"attempt": repr(attempt)})
    if not (_is_positive(base) and _is_positive(cap) and cap >= base):
        raise ToolError(
            "invalid_input", "base and cap must be positive and cap >= base", {"base": repr(base), "cap": repr(cap)}
        )
    return float(min(cap, base * 2.0 ** min(attempt - 1, 1023)))


def after_failure(error: BaseException, attempt: int, max_attempts: int) -> Literal["retry", "dead"]:
    """Whether a failed delivery is tried again or goes to the dead letters."""
    if not (_is_count(attempt) and _is_count(max_attempts)):
        raise ToolError(
            "invalid_input",
            "attempt and max_attempts must be ints >= 1",
            {"attempt": repr(attempt), "max_attempts": repr(max_attempts)},
        )
    if isinstance(error, ToolError) and error.code in PERMANENT_CODES:
        return "dead"
    return "dead" if attempt >= max_attempts else "retry"


def describe_error(error: BaseException, limit: int = 500) -> str:
    """One line describing `error`, at most `limit` characters."""
    if type(limit) is not int or limit < 2:
        raise ToolError("invalid_input", "limit must be an int >= 2", {"limit": repr(limit)})
    if isinstance(error, ToolError):
        text = f"{error.code}: {error.message}"
    else:
        message = str(error)
        text = f"{type(error).__name__}: {message}" if message else type(error).__name__
    text = text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    return text if len(text) <= limit else text[: limit - 1] + "…"
