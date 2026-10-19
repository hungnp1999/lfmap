import json

from typer.testing import CliRunner

from lfmap_core import cli, grants
from lfmap_core.approval import audit_path
from lfmap_core.cli import build_app

runner = CliRunner()


def run(registry, *args, input=None):
    return runner.invoke(build_app(registry), list(args), input=input)


def test_plugins_list(registry):
    result = run(registry, "plugins", "list", "--json")
    assert result.exit_code == 0
    assert json.loads(result.output) == [{"id": "fake-plugin", "version": "1.2.3", "operations": ["greet", "write"]}]


def test_generated_command(registry):
    result = run(registry, "fake-plugin", "greet", "--name", "Hùng", "--times", "2", "--shout")
    assert result.exit_code == 0
    assert result.output.strip() == "message: HELLO HÙNG HELLO HÙNG"


def test_json_output(registry):
    result = run(registry, "fake-plugin", "greet", "--name", "A", "--json")
    assert json.loads(result.output) == {"message": "Hello A"}


def test_missing_required_option(registry):
    assert run(registry, "fake-plugin", "greet").exit_code == 2


def test_tool_error_propagates(registry):
    result = run(registry, "fake-plugin", "greet", "--name", "error")
    assert result.exception.code == "not_found"


def test_t1_runs_without_prompt(user_dirs, registry):
    result = run(registry, "fake-plugin", "write", "--input-json", json.dumps({"names": ["a", "b"]}))
    assert result.output.strip() == "message: a,b"
    assert '"tier": "T1"' in audit_path().read_text(encoding="utf-8")


def test_t2_asks_in_a_terminal(user_dirs, registry, monkeypatch):
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    payload = json.dumps({"names": ["a"], "escalate": "overwrite"})
    refused = run(registry, "fake-plugin", "write", "--input-json", payload, input="n\n")
    assert refused.exception.code == "permission_denied"
    accepted = run(registry, "fake-plugin", "write", "--input-json", payload, input="y\n")
    assert accepted.output.strip().endswith("message: a")


def test_t2_needs_yes_without_a_terminal(user_dirs, registry):
    payload = json.dumps({"names": ["a"], "escalate": "overwrite"})
    refused = run(registry, "fake-plugin", "write", "--input-json", payload)
    assert refused.exception.code == "permission_denied"
    assert "--yes" in refused.exception.details["hint"]
    assert run(registry, "fake-plugin", "write", "--input-json", payload, "--yes").output.strip() == "message: a"


def test_t3_ignores_yes(user_dirs, registry, monkeypatch):
    payload = json.dumps({"names": ["a"], "escalate": "external"})
    assert run(registry, "fake-plugin", "write", "--input-json", payload, "--yes").exception.code == "permission_denied"
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    assert run(registry, "fake-plugin", "write", "--input-json", payload, input="y\n").exit_code == 0


def test_grant_needs_a_terminal(user_dirs, registry):
    result = run(registry, "approvals", "grant", "fake-plugin.write", "--tier", "T3")
    assert result.exception.code == "permission_denied"
    assert grants.load() == []


def test_grant_list_revoke(user_dirs, registry, monkeypatch):
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    assert run(registry, "approvals", "grant", "fake-plugin.write", "--tier", "T3", "--for", "2h").exit_code == 0
    assert grants.active("fake-plugin.write", "T3")
    listed = json.loads(run(registry, "approvals", "list", "--json").output)
    assert [g["operation"] for g in listed] == ["fake-plugin.write"]
    assert run(registry, "approvals", "grant", "fake-plugin.write", "--tier", "T3", "--for", "2d").exception.code == (
        "invalid_input"
    )
    assert run(registry, "approvals", "grant", "nope.op").exception.code == "invalid_input"
    assert "Revoked 1" in run(registry, "approvals", "revoke", "fake-plugin.write").output
    assert not grants.active("fake-plugin.write", "T3")
    decisions = [json.loads(line)["decision"] for line in audit_path().read_text(encoding="utf-8").splitlines()]
    assert decisions == ["grant", "revoke"]
