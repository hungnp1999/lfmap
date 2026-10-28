import pytest

from lfmap_core import ToolError
from lfmap_core.registry import Registry, load_entry
from lfmap_echo import EchoTool, SayInput, say


def test_say():
    assert say(SayInput(text="hi")).model_dump() == {"text": "hi", "length": 2}


def test_say_upper():
    assert say(SayInput(text="xin chào", upper=True)).text == "XIN CHÀO"


def test_manifest_matches_tool():
    entry = load_entry(EchoTool)
    assert entry.id == "echo"
    assert entry.manifest.operation("say").side_effects == "none"


def test_discovered_through_entry_point():
    registry = Registry()
    registry.discover()
    assert registry.get("echo").tool_class is EchoTool


def test_manifest_needing_newer_core_is_refused(monkeypatch):
    monkeypatch.setattr("lfmap_core.registry.__version__", "0.0.9")
    with pytest.raises(ToolError) as caught:
        load_entry(EchoTool)
    assert caught.value.details == {"plugin": "echo", "min_core_version": "0.1.0", "core_version": "0.0.9"}


def test_discover_skips_plugin_needing_newer_core(monkeypatch):
    monkeypatch.setattr("lfmap_core.registry.__version__", "0.0.9")
    registry = Registry()
    registry.discover()
    assert "echo" not in [entry.id for entry in registry.all()]
