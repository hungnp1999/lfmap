"""Dot-separated event topics and subscription patterns with `*` (one token) and a final `>` (one or more)."""

import re

from lfmap_core.errors import ToolError

MAX_TOKENS = 8
MAX_LENGTH = 200
_TOKEN = re.compile(r"[a-z0-9_-]+", re.ASCII)


def _tokens(value: object, key: str, wildcards: bool) -> list[str]:
    if not isinstance(value, str):
        raise ToolError("invalid_input", f"Invalid {key}", {key: repr(value)})
    tokens = value.split(".")
    valid = 0 < len(value) <= MAX_LENGTH and len(tokens) <= MAX_TOKENS
    for index, token in enumerate(tokens):
        wild = wildcards and (token == "*" or (token == ">" and index == len(tokens) - 1))
        valid = valid and (wild or _TOKEN.fullmatch(token) is not None)
    if not valid:
        raise ToolError("invalid_input", f"Invalid {key}: {value!r}", {key: value})
    return tokens


def validate_topic(topic: str) -> str:
    """Return `topic` when it is a valid concrete topic."""
    _tokens(topic, "topic", wildcards=False)
    return topic


def validate_pattern(pattern: str) -> str:
    """Return `pattern` when it is a valid subscription pattern."""
    _tokens(pattern, "pattern", wildcards=True)
    return pattern


def topic_matches(pattern: str, topic: str) -> bool:
    """Whether `topic` matches `pattern`, compared token by token."""
    wanted = _tokens(pattern, "pattern", wildcards=True)
    tokens = _tokens(topic, "topic", wildcards=False)
    if wanted[-1] == ">":
        head = wanted[:-1]
        if len(tokens) <= len(head):
            return False
        tokens = tokens[: len(head)]
        wanted = head
    if len(wanted) != len(tokens):
        return False
    return all(want in ("*", token) for want, token in zip(wanted, tokens, strict=True))
