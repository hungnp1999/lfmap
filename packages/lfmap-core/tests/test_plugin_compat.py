"""Plugin Contract v0.2 compatibility (issue #192): a plugin written against v0.1.1 must keep loading and running.

The fixture `tests/fixtures/frozen_plugin_v011/` is frozen. It uses only what Plugin Contract v0.1.1 offered
(no `min_tier`, no `ctx.events`, no flows). If one of these tests fails, fix lfmap-core, not the fixture; change
the fixture only with a contract version bump and a new frozen copy next to it.
"""

import hashlib
import json
import sys
from pathlib import Path

import anyio
import pytest
from typer.testing import CliRunner

from lfmap_core import ToolError, __version__, flows_run
from lfmap_core.cli import build_app
from lfmap_core.events import InProcessBus
from lfmap_core.events_adapter import EventAdapter
from lfmap_core.mcp_adapter import build_server
from lfmap_core.registry import Registry, load_entry
from lfmap_core.runtime import build_tool, default_context, run_operation

FROZEN = Path(__file__).parent / "fixtures" / "frozen_plugin_v011"
PACKAGE = FROZEN / "lfmap_frozen_note"
SHA256 = {
    "__init__.py": "17d2a77e51b69000257e533573a8bcffdffa9e72c0fcbf7daacb9a42e537c6e2",
    "lfmap.toml": "5e170bfa5d4f540225fe67499515825c80ceb39571d567a5a79677874cff34ff",
    "schemas.py": "c78075f2d660a8be03ef2c42183f3699b298282e09b5c19e70237fcb86df318f",
    "tool.py": "b6be96624d19a7c469a316dcfed47db63be2a2b580020392a8fac03ebdf18785",
}
runner = CliRunner()


@pytest.fixture
def tool_class(monkeypatch):
    monkeypatch.syspath_prepend(str(FROZEN))
    for name in [n for n in sys.modules if n.startswith("lfmap_frozen_note")]:
        monkeypatch.delitem(sys.modules, name)
    from lfmap_frozen_note.tool import FrozenNoteTool

    return FrozenNoteTool


@pytest.fixture
def registry(tool_class) -> Registry:
    reg = Registry()
    reg.register(load_entry(tool_class))
    return reg


def test_fixture_is_frozen():
    actual = {
        name: hashlib.sha256((PACKAGE / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest() for name in SHA256
    }
    assert actual == SHA256


def test_frozen_manifest_uses_only_v011_keys():
    text = (PACKAGE / "lfmap.toml").read_text(encoding="utf-8")
    for later in ("min_tier", "models", "principal", "via"):
        assert later not in text
    assert 'min_core_version = "0.1.0"' in text


def test_loads_with_current_core(tool_class):
    entry = load_entry(tool_class)
    assert entry.id == "frozen-note"
    assert set(tool_class.operations()) == {"shout", "save", "missing"}
    assert entry.manifest.operation("save").side_effects == "local_write"
    assert entry.manifest.adapters.events is False


def test_min_core_version_is_enforced(tool_class, monkeypatch):
    newer = (
        (PACKAGE / "lfmap.toml")
        .read_text(encoding="utf-8")
        .replace('"0.1.0"\n\n[plugin.entrypoint]', '"99.0.0"\n\n[plugin.entrypoint]')
    )
    assert '"99.0.0"' in newer
    monkeypatch.setattr(tool_class, "manifest_path", "lfmap.toml")
    monkeypatch.setattr("lfmap_core.registry.importlib.resources.files", lambda _: _Text(newer))
    with pytest.raises(ToolError) as error:
        load_entry(tool_class)
    assert error.value.code == "invalid_input"
    assert error.value.details == {"plugin": "frozen-note", "min_core_version": "99.0.0", "core_version": __version__}


class _Text:
    def __init__(self, text: str) -> None:
        self.text = text

    def __truediv__(self, _name: str) -> "_Text":
        return self

    def read_text(self, encoding: str = "utf-8") -> str:
        return self.text


def test_sdk_use_without_a_runtime(tool_class):
    from lfmap_frozen_note import shout
    from lfmap_frozen_note.schemas import ShoutInput

    assert shout(ShoutInput(text="hi")).text == "HI"
    assert tool_class(default_context("frozen-note")).health() == {"ok": True}


def test_cli_runs_it(registry):
    result = runner.invoke(build_app(registry), ["frozen-note", "shout", "--text", "hi", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {"text": "HI"}


def test_mcp_runs_it(registry):
    server = build_server(registry, ["frozen-note"])
    result = anyio.run(server.call_tool, "frozen_note_shout", {"text": "hi"})
    assert result.structured_content == {"text": "HI"}


def test_tool_error_keeps_its_code(registry):
    with pytest.raises(ToolError) as error:
        run_operation(registry.get("frozen-note"), "missing", {})
    assert error.value.code == "not_found"


def test_permissions_still_guard_writes(registry, tmp_path):
    entry = registry.get("frozen-note")
    out = tmp_path / "out"
    out.mkdir()
    done = run_operation(entry, "save", {"path": str(out / "a.txt"), "text": "x"}, {"output_dir": str(out)})
    assert (out / "a.txt").read_text(encoding="utf-8") == "x"
    assert done.model_dump() == {"path": str(out / "a.txt"), "bytes": 1}
    with pytest.raises(ToolError) as error:
        run_operation(entry, "save", {"path": str(tmp_path / "b.txt"), "text": "x"}, {"output_dir": str(out)})
    assert error.value.code == "permission_denied"


def test_has_no_events_unless_it_opts_in(registry):
    tool = build_tool(registry.get("frozen-note"))
    with pytest.raises(ToolError) as error:
        tool.ctx.events.publish("frozen-note.noted", {})
    assert error.value.code == "permission_denied"
    assert EventAdapter(registry, InProcessBus()).attach() == []


def test_a_flow_can_chain_it(registry, user_dirs, monkeypatch):
    flows = user_dirs / "flows.toml"
    flows.write_text(
        '[[flows]]\nid = "chain"\ntrigger = { manual = true }\n\n'
        '[[flows.steps]]\nid = "one"\ncall = "frozen-note.shout"\ninput = { text = "${trigger.payload.who}" }\n\n'
        '[[flows.steps]]\nid = "two"\ncall = "frozen-note.shout"\ninput = { text = "${steps.one.output.text}!" }\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("LFMAP_FLOWS", str(flows))
    run = flows_run.start(registry, "chain", {"who": "ab"})
    assert run.status == "completed"
    assert [s.output for s in run.steps] == [{"text": "AB"}, {"text": "AB!"}]
