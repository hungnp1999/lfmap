import anyio
import pytest

from lfmap_core import ToolError
from lfmap_core.mcp_adapter import build_server, tool_name


def test_tool_name():
    assert tool_name("fake-plugin", "greet") == "fake_plugin_greet"
    with pytest.raises(ToolError):
        tool_name("x" * 60, "operation")


def test_list_tools_schema(registry):
    tools = anyio.run(build_server(registry, ["fake-plugin"]).list_tools)
    greet = next(t for t in tools if t.name == "fake_plugin_greet")
    assert greet.description == "Greet someone."
    assert greet.input_schema["required"] == ["name"]
    assert set(greet.input_schema["properties"]) == {"name", "times", "shout"}


def test_call_tool(registry):
    server = build_server(registry, [])
    result = anyio.run(server.call_tool, "fake_plugin_greet", {"name": "A", "times": 2})
    assert result.structured_content == {"message": "Hello A Hello A"}


def test_call_tool_error(registry):
    server = build_server(registry, [])
    with pytest.raises(Exception, match="not_found"):
        anyio.run(server.call_tool, "fake_plugin_greet", {"name": "error"})


def test_side_effects_denied_without_approval(registry):
    server = build_server(registry, [])
    with pytest.raises(Exception, match="permission_denied.*--approve fake-plugin.write"):
        anyio.run(server.call_tool, "fake_plugin_write", {"names": ["a"]})


def test_side_effects_run_when_approved(registry):
    server = build_server(registry, [], ["fake-plugin.write"])
    result = anyio.run(server.call_tool, "fake_plugin_write", {"names": ["a", "b"]})
    assert result.structured_content == {"message": "a,b"}


def test_annotations_and_description(registry):
    tools = {t.name: t for t in anyio.run(build_server(registry, []).list_tools)}
    assert tools["fake_plugin_greet"].annotations.read_only_hint is True
    write = tools["fake_plugin_write"]
    assert write.annotations.read_only_hint is False
    assert "Requires approval when the server starts." in write.description


def test_unknown_approval_refused(registry):
    with pytest.raises(ToolError) as caught:
        build_server(registry, [], ["fake-plugin.nope"])
    assert caught.value.code == "invalid_input"


def test_external_cannot_be_pre_approved(external_registry):
    with pytest.raises(ToolError) as caught:
        build_server(external_registry, [], ["fake-plugin.write"])
    assert caught.value.code == "invalid_input"
    tools = {t.name: t for t in anyio.run(build_server(external_registry, []).list_tools)}
    assert tools["fake_plugin_write"].annotations.open_world_hint is True
