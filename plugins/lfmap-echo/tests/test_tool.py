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
