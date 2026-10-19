import pytest

from lfmap_core.errors import ToolError
from lfmap_core.runtime import build_tool, context_for, default_context, run_operation


def test_default_context(user_dirs):
    ctx = default_context("echo")
    assert ctx.channel == "sdk"
    assert ctx.settings == {}
    assert ctx.data_dir is None


def test_build_tool_channel(user_dirs, registry):
    (user_dirs / "config.toml").write_text("", encoding="utf-8")
    tool = build_tool(registry.get("fake-plugin"), channel="mcp")
    assert tool.ctx.channel == "mcp"
    assert tool.ctx.data_dir.exists()
    assert tool.ctx.data_dir.name == "fake-plugin"
    assert tool.ctx.temp_dir.exists()


def test_build_tool_settings(user_dirs, registry):
    (user_dirs / "config.toml").write_text('[plugins.fake-plugin.settings]\nmodel = "bge-m3"\n', encoding="utf-8")
    tool = build_tool(registry.get("fake-plugin"))
    assert tool.ctx.settings == {"model": "bge-m3"}


def test_build_tool_settings_invalid(user_dirs, registry):
    (user_dirs / "config.toml").write_text('[plugins.fake-plugin]\nsettings = "x"\n', encoding="utf-8")
    with pytest.raises(ToolError) as excinfo:
        build_tool(registry.get("fake-plugin"))
    assert excinfo.value.code == "invalid_input"


def test_run_operation(user_dirs, registry):
    (user_dirs / "config.toml").write_text("", encoding="utf-8")
    entry = registry.get("fake-plugin")
    result = run_operation(entry, "greet", {"name": "A"}, channel="cli")
    assert result.message == "Hello A"


def test_context_for(user_dirs, registry):
    (user_dirs / "config.toml").write_text("", encoding="utf-8")
    parent = build_tool(registry.get("fake-plugin"), channel="mcp").ctx
    ctx = context_for("other", parent)
    assert ctx.permissions is parent.permissions
    assert ctx.channel == "mcp"
    assert ctx.data_dir.name == "other"
