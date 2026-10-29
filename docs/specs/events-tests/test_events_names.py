import pytest

from lfmap_core import ToolError
from lfmap_core.events_names import PHASES, operation_topic, parse_operation_topic, plugin_may_publish


def test_phases():
    assert PHASES == ("requested", "completed", "failed")


@pytest.mark.parametrize(
    ("plugin_id", "operation", "phase", "expected"),
    [
        ("markitdown", "convert", "requested", "markitdown.convert.requested"),
        ("knowledge", "get_context", "completed", "knowledge.get_context.completed"),
        ("lfmap-isomp", "scan2", "failed", "lfmap-isomp.scan2.failed"),
        ("a", "b", "requested", "a.b.requested"),
    ],
)
def test_operation_topic(plugin_id, operation, phase, expected):
    assert operation_topic(plugin_id, operation, phase) == expected


@pytest.mark.parametrize(
    "plugin_id", ["", "Markitdown", "1abc", "-abc", "ab_c", "ab.c", "ab c", "abc\n", "ábc", "a" * 65, None, 3]
)
def test_operation_topic_rejects_plugin(plugin_id):
    with pytest.raises(ToolError) as caught:
        operation_topic(plugin_id, "convert", "requested")
    assert caught.value.code == "invalid_input"
    expected = plugin_id if isinstance(plugin_id, str) else repr(plugin_id)
    assert caught.value.details == {"plugin": expected}


@pytest.mark.parametrize("operation", ["", "Convert", "1op", "_op", "op-x", "op.x", "op\n", "ópx", "o" * 65, None])
def test_operation_topic_rejects_operation(operation):
    with pytest.raises(ToolError) as caught:
        operation_topic("markitdown", operation, "requested")
    assert caught.value.code == "invalid_input"
    expected = operation if isinstance(operation, str) else repr(operation)
    assert caught.value.details == {"operation": expected}


@pytest.mark.parametrize("phase", ["", "Requested", "done", "requested ", "*", None])
def test_operation_topic_rejects_phase(phase):
    with pytest.raises(ToolError) as caught:
        operation_topic("markitdown", "convert", phase)
    assert caught.value.code == "invalid_input"
    expected = phase if isinstance(phase, str) else repr(phase)
    assert caught.value.details == {"phase": expected}


def test_operation_topic_checks_plugin_first():
    with pytest.raises(ToolError) as caught:
        operation_topic("Bad", "Bad", "bad")
    assert caught.value.details == {"plugin": "Bad"}


def test_longest_names_are_accepted():
    assert operation_topic("a" * 64, "o" * 64, "failed") == "a" * 64 + "." + "o" * 64 + ".failed"


@pytest.mark.parametrize(
    ("topic", "expected"),
    [
        ("markitdown.convert.requested", ("markitdown", "convert", "requested")),
        ("knowledge.get_context.completed", ("knowledge", "get_context", "completed")),
        ("lfmap-isomp.scan.failed", ("lfmap-isomp", "scan", "failed")),
    ],
)
def test_parse_operation_topic(topic, expected):
    assert parse_operation_topic(topic) == expected


@pytest.mark.parametrize(
    "topic",
    [
        "",
        "markitdown",
        "markitdown.convert",
        "markitdown.convert.done",
        "markitdown.convert.requested.late",
        "x.markitdown.convert.requested",
        "Markitdown.convert.requested",
        "markitdown.Convert.requested",
        "markitdown.convert.requested\n",
        "markitdown..requested",
        "markitdown.convert.*",
        "*.convert.requested",
        "markitdown.op-x.requested",
        None,
        42,
    ],
)
def test_parse_operation_topic_returns_none(topic):
    assert parse_operation_topic(topic) is None


@pytest.mark.parametrize(
    ("plugin_id", "topic", "expected"),
    [
        ("knowledge", "knowledge.reindex.finished", True),
        ("knowledge", "knowledge.indexed", True),
        ("knowledge", "knowledge.a.b.c.d", True),
        ("knowledge", "knowledge", False),
        ("knowledge", "markitdown.converted", False),
        ("knowledge", "knowledge-x.indexed", False),
        ("knowledge", "knowledgex.indexed", False),
        ("knowledge", "core.started", False),
        ("knowledge", "knowledge.reindex.requested", False),
        ("knowledge", "knowledge.reindex.completed", False),
        ("knowledge", "knowledge.reindex.failed", False),
        ("knowledge", "knowledge.reindex.failed.again", True),
        ("knowledge", None, False),
        ("knowledge", b"knowledge.indexed", False),
    ],
)
def test_plugin_may_publish(plugin_id, topic, expected):
    assert plugin_may_publish(plugin_id, topic) is expected


def test_plugin_may_publish_checks_plugin_id():
    with pytest.raises(ToolError) as caught:
        plugin_may_publish("Knowledge", "Knowledge.indexed")
    assert caught.value.code == "invalid_input"
    assert caught.value.details == {"plugin": "Knowledge"}
