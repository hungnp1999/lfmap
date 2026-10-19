import json
from datetime import timedelta
from types import SimpleNamespace

import anyio
import pytest
from mcp import types
from mcp.client.client import Client

from lfmap_core import ToolError, grants, mcp_adapter
from lfmap_core.approval import audit_path
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


def test_t1_runs_and_is_audited(user_dirs, registry):
    server = build_server(registry, [])
    result = anyio.run(server.call_tool, "fake_plugin_write", {"names": ["a", "b"]})
    assert result.structured_content == {"message": "a,b"}
    (line,) = audit_path().read_text(encoding="utf-8").splitlines()
    assert json.loads(line) | {"time": None} == {
        "time": None,
        "channel": "mcp",
        "plugin": "fake-plugin",
        "operation": "write",
        "tier": "T1",
        "decision": "allow",
        "reason": "side_effects",
    }


def test_t2_denied_without_approval_or_elicitation(user_dirs, registry):
    server = build_server(registry, [])
    with pytest.raises(Exception, match="permission_denied.*--approve fake-plugin.write"):
        anyio.run(server.call_tool, "fake_plugin_write", {"names": ["a"], "escalate": "overwrite"})
    assert '"decision": "deny"' in audit_path().read_text(encoding="utf-8")


def test_t2_runs_when_approved(user_dirs, registry):
    server = build_server(registry, [], ["fake-plugin.write"])
    result = anyio.run(server.call_tool, "fake_plugin_write", {"names": ["a"], "escalate": "overwrite"})
    assert result.structured_content == {"message": "a"}


def test_approval_expires(user_dirs, registry, monkeypatch):
    server = build_server(registry, [], ["fake-plugin.write"])
    monkeypatch.setattr(mcp_adapter, "APPROVE_TTL_SECONDS", -1)
    with pytest.raises(Exception, match="permission_denied"):
        anyio.run(server.call_tool, "fake_plugin_write", {"names": ["a"], "escalate": "overwrite"})


def test_t3_denied_even_when_approved(user_dirs, registry):
    server = build_server(registry, [], ["fake-plugin.write"])
    with pytest.raises(Exception, match="permission_denied.*approvals grant fake-plugin.write --tier T3"):
        anyio.run(server.call_tool, "fake_plugin_write", {"names": ["a"], "escalate": "external"})


def test_t3_runs_with_grant(user_dirs, registry):
    grants.add("fake-plugin.write", "T3", timedelta(hours=1))
    server = build_server(registry, [])
    result = anyio.run(server.call_tool, "fake_plugin_write", {"names": ["a"], "escalate": "external"})
    assert result.structured_content == {"message": "a"}


def test_policy_deny(user_dirs, registry):
    (user_dirs / "config.toml").write_text('[approval]\nT1 = "deny"\n', encoding="utf-8")
    with pytest.raises(Exception, match="permission_denied"):
        anyio.run(build_server(registry, []).call_tool, "fake_plugin_write", {"names": ["a"]})


def test_asker_uses_elicitation():
    class Session:
        def check_client_capability(self, capability):
            return capability.elicitation is not None

    context = SimpleNamespace(request_context=SimpleNamespace(session=Session()))
    assert mcp_adapter._asker(context) is not None
    assert mcp_adapter._asker(SimpleNamespace()) is None


def test_annotations_and_description(registry):
    tools = {t.name: t for t in anyio.run(build_server(registry, []).list_tools)}
    assert tools["fake_plugin_greet"].annotations.read_only_hint is True
    assert "mcp_context" not in tools["fake_plugin_greet"].input_schema["properties"]
    write = tools["fake_plugin_write"]
    assert write.annotations.read_only_hint is False
    assert "(tier T1)" in write.description and "audit log" in write.description


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


@pytest.mark.parametrize(("action", "allowed"), [("accept", True), ("decline", False)])
def test_t2_asks_through_elicitation(user_dirs, registry, action, allowed):
    questions = []

    async def answer(context, params):
        questions.append(params.message)
        return types.ElicitResult(action=action, content={"approve": True} if action == "accept" else None)

    async def scenario():
        async with Client(build_server(registry, []), mode="legacy", elicitation_callback=answer) as client:
            return await client.call_tool("fake_plugin_write", {"names": ["a"], "escalate": "overwrite"})

    result = anyio.run(scenario)
    assert questions == ["Allow fake-plugin.write (T2, overwrite) on out.txt?"]
    assert (result.structured_content == {"message": "a"}) is allowed
    assert result.is_error is not allowed


def test_no_back_channel_means_denied(user_dirs, registry):
    async def answer(context, params):
        raise AssertionError("never asked")

    async def scenario():
        async with Client(build_server(registry, []), elicitation_callback=answer) as client:
            return await client.call_tool("fake_plugin_write", {"names": ["a"], "escalate": "overwrite"})

    result = anyio.run(scenario)
    assert result.is_error and "permission_denied" in result.content[0].text
