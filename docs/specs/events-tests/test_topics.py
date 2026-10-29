import pytest

from lfmap_core import ToolError
from lfmap_core.topics import topic_matches, validate_pattern, validate_topic


@pytest.mark.parametrize(
    "topic",
    ["jobs", "jobs.done", "knowledge.reindex.finished", "a-b.c_d.0", "x." * 7 + "y", "a" * 200],
)
def test_validate_topic_accepts(topic):
    assert validate_topic(topic) == topic


@pytest.mark.parametrize(
    "topic",
    [
        "",
        ".",
        "jobs.",
        ".jobs",
        "jobs..done",
        "Jobs.done",
        "jobs done",
        "jobs.done\n",
        "jobs.*",
        "jobs.>",
        "jobs.dōne",
        "jobs.１",
        "x." * 8 + "y",
        "a" * 201,
    ],
)
def test_validate_topic_rejects(topic):
    with pytest.raises(ToolError) as info:
        validate_topic(topic)
    assert info.value.code == "invalid_input"
    assert info.value.details == {"topic": topic}


@pytest.mark.parametrize("value", [None, 3, b"jobs", ["jobs"]])
def test_validate_topic_non_str(value):
    with pytest.raises(ToolError) as info:
        validate_topic(value)
    assert info.value.code == "invalid_input"
    assert info.value.details == {"topic": repr(value)}


@pytest.mark.parametrize("pattern", ["jobs", "jobs.*", "*", ">", "jobs.>", "*.done", "*.*.>", "a.*.c"])
def test_validate_pattern_accepts(pattern):
    assert validate_pattern(pattern) == pattern


@pytest.mark.parametrize(
    "pattern",
    ["", "jobs.", ">.done", "jobs.>.x", "jobs.*x", "jobs.x*", "jobs.>>", "jobs.**", "JOBS.*", "jobs..*", "*\n"],
)
def test_validate_pattern_rejects(pattern):
    with pytest.raises(ToolError) as info:
        validate_pattern(pattern)
    assert info.value.code == "invalid_input"
    assert info.value.details == {"pattern": pattern}


def test_validate_pattern_non_str():
    with pytest.raises(ToolError) as info:
        validate_pattern(None)
    assert info.value.details == {"pattern": "None"}


@pytest.mark.parametrize(
    ("pattern", "topic", "expected"),
    [
        ("jobs.done", "jobs.done", True),
        ("jobs.done", "jobs.failed", False),
        ("jobs.done", "jobs", False),
        ("jobs", "jobs.done", False),
        ("jobs.*", "jobs.done", True),
        ("jobs.*", "jobs", False),
        ("jobs.*", "jobs.done.late", False),
        ("*.done", "jobs.done", True),
        ("*.done", "done", False),
        ("*", "jobs", True),
        ("*", "jobs.done", False),
        ("jobs.>", "jobs.done", True),
        ("jobs.>", "jobs.done.late", True),
        ("jobs.>", "jobs", False),
        (">", "jobs", True),
        (">", "jobs.done.late", True),
        ("*.*.>", "a.b", False),
        ("*.*.>", "a.b.c", True),
        ("a.*.c", "a.b.c", True),
        ("a.*.c", "a.b.d", False),
        ("jobs.done", "jobs.do", False),
        ("job", "jobs", False),
    ],
)
def test_topic_matches(pattern, topic, expected):
    assert topic_matches(pattern, topic) is expected


def test_topic_matches_validates_topic():
    with pytest.raises(ToolError) as info:
        topic_matches("jobs.*", "jobs.*")
    assert info.value.details == {"topic": "jobs.*"}


def test_topic_matches_validates_pattern():
    with pytest.raises(ToolError) as info:
        topic_matches("jobs.>.x", "jobs.a.x")
    assert info.value.details == {"pattern": "jobs.>.x"}
