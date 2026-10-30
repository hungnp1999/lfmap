import pytest

from lfmap_core import ToolError
from lfmap_core.events_retry import PERMANENT_CODES, after_failure, backoff_seconds, describe_error


@pytest.mark.parametrize(
    ("attempt", "expected"),
    [(1, 2.0), (2, 4.0), (3, 8.0), (5, 32.0), (8, 256.0), (9, 300.0), (50, 300.0), (10_000, 300.0)],
)
def test_backoff_defaults(attempt, expected):
    assert backoff_seconds(attempt) == expected


def test_backoff_returns_float():
    assert type(backoff_seconds(1)) is float
    assert type(backoff_seconds(1, base=1, cap=10)) is float


@pytest.mark.parametrize(
    ("attempt", "base", "cap", "expected"),
    [(1, 0.5, 10.0, 0.5), (4, 0.5, 10.0, 4.0), (6, 0.5, 10.0, 10.0), (3, 1, 3, 3.0), (2, 5.0, 5.0, 5.0)],
)
def test_backoff_custom(attempt, base, cap, expected):
    assert backoff_seconds(attempt, base=base, cap=cap) == expected


@pytest.mark.parametrize("attempt", [0, -1, 1.0, "1", None, True, False])
def test_backoff_rejects_attempt(attempt):
    with pytest.raises(ToolError) as caught:
        backoff_seconds(attempt)
    assert caught.value.code == "invalid_input"
    assert caught.value.details == {"attempt": repr(attempt)}


@pytest.mark.parametrize(
    ("base", "cap"),
    [(0, 10.0), (-1.0, 10.0), (2.0, 0), (2.0, 1.0), (True, 10.0), ("2", 10.0), (2.0, None), (float("nan"), 10.0)],
)
def test_backoff_rejects_base_and_cap(base, cap):
    with pytest.raises(ToolError) as caught:
        backoff_seconds(1, base=base, cap=cap)
    assert caught.value.code == "invalid_input"
    assert caught.value.details == {"base": repr(base), "cap": repr(cap)}


def test_permanent_codes():
    assert PERMANENT_CODES == frozenset({"invalid_input", "permission_denied", "not_found"})


@pytest.mark.parametrize("code", ["invalid_input", "permission_denied", "not_found"])
def test_permanent_tool_error_is_dead_at_once(code):
    assert after_failure(ToolError(code, "no"), 1, 5) == "dead"


@pytest.mark.parametrize("code", ["backend_unavailable", "timeout", "internal"])
def test_transient_tool_error_retries(code):
    assert after_failure(ToolError(code, "later"), 1, 5) == "retry"


@pytest.mark.parametrize(
    ("attempt", "max_attempts", "expected"),
    [(1, 5, "retry"), (4, 5, "retry"), (5, 5, "dead"), (6, 5, "dead"), (1, 1, "dead"), (1, 2, "retry")],
)
def test_after_failure_counts_attempts(attempt, max_attempts, expected):
    assert after_failure(ValueError("boom"), attempt, max_attempts) == expected


def test_after_failure_any_exception_type():
    assert after_failure(KeyError("x"), 1, 3) == "retry"
    assert after_failure(OSError(5, "io"), 3, 3) == "dead"


@pytest.mark.parametrize(("attempt", "max_attempts"), [(0, 5), (1, 0), (True, 5), (1, 2.0), ("1", 5), (1, None)])
def test_after_failure_rejects_counts(attempt, max_attempts):
    with pytest.raises(ToolError) as caught:
        after_failure(ValueError("boom"), attempt, max_attempts)
    assert caught.value.code == "invalid_input"
    assert caught.value.details == {"attempt": repr(attempt), "max_attempts": repr(max_attempts)}


def test_describe_tool_error():
    assert describe_error(ToolError("timeout", "Ollama did not answer")) == "timeout: Ollama did not answer"


def test_describe_other_error():
    assert describe_error(ValueError("bad value")) == "ValueError: bad value"


def test_describe_error_without_message():
    assert describe_error(KeyboardInterrupt()) == "KeyboardInterrupt"
    assert describe_error(RuntimeError("")) == "RuntimeError"


def test_describe_error_flattens_newlines():
    assert describe_error(ValueError("a\r\nb\nc\rd")) == "ValueError: a b c d"


def test_describe_error_truncates():
    text = describe_error(ValueError("x" * 1000))
    assert len(text) == 500
    assert text.endswith("…")
    assert text.startswith("ValueError: xxx")


def test_describe_error_custom_limit():
    assert describe_error(ValueError("abcdef"), limit=10) == "ValueErro…"
    assert describe_error(ValueError("ab"), limit=13) == "ValueError: …"
    assert describe_error(ValueError("ab"), limit=14) == "ValueError: ab"


@pytest.mark.parametrize("limit", [0, 1, -5, True, 2.0, None])
def test_describe_error_rejects_limit(limit):
    with pytest.raises(ToolError) as caught:
        describe_error(ValueError("x"), limit=limit)
    assert caught.value.code == "invalid_input"
    assert caught.value.details == {"limit": repr(limit)}
