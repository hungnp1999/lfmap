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
