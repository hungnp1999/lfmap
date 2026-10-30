import json

import pytest
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
    monkeypatch.setattr(cli, "_confirm_code", lambda: "ABC234")
    granted = run(registry, "approvals", "grant", "fake-plugin.write", "--tier", "T3", "--for", "2h", input="abc234\n")
    assert granted.exit_code == 0, granted.output
    assert "type this code: ABC234" in granted.output
    assert grants.active("fake-plugin.write", "T3")
    listed = json.loads(run(registry, "approvals", "list", "--json").output)
    assert [g["operation"] for g in listed] == ["fake-plugin.write"]
    assert run(registry, "approvals", "grant", "fake-plugin.write", "--tier", "T3", "--for", "2d").exception.code == (
        "invalid_input"
    )
    assert run(registry, "approvals", "grant", "nope.op").exception.code == "invalid_input"
    assert "Revoked 1" in run(registry, "approvals", "revoke", "fake-plugin.write", input="ABC234\n").output
    assert not grants.active("fake-plugin.write", "T3")
    decisions = [json.loads(line)["decision"] for line in audit_path().read_text(encoding="utf-8").splitlines()]
    assert decisions == ["grant", "revoke"]


def test_confirm_code_shape():
    codes = {cli._confirm_code() for _ in range(50)}
    assert len(codes) > 45
    assert all(len(c) == cli.CODE_LENGTH and set(c) <= set(cli.CODE_ALPHABET) for c in codes)
    assert not set("01IO") & set(cli.CODE_ALPHABET)


@pytest.mark.parametrize("typed", ["XYZ999\n", "\n", None])
def test_grant_with_wrong_code_or_eof_writes_nothing(user_dirs, registry, monkeypatch, typed):
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    monkeypatch.setattr(cli, "_confirm_code", lambda: "ABC234")
    result = run(registry, "approvals", "grant", "fake-plugin.write", "--tier", "T3", input=typed)
    assert result.exception.code == "permission_denied"
    assert "confirmation code" in result.exception.message
    assert grants.load() == []
    [record] = [json.loads(line) for line in audit_path().read_text(encoding="utf-8").splitlines()]
    assert (record["decision"], record["operation"], record["tier"]) == ("deny", "write", "T3")


def test_revoke_with_wrong_code_keeps_the_grant(user_dirs, registry, monkeypatch):
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    monkeypatch.setattr(cli, "_confirm_code", lambda: "ABC234")
    run(registry, "approvals", "grant", "fake-plugin.write", "--tier", "T2", input="ABC234\n")
    result = run(registry, "approvals", "revoke", "fake-plugin.write", input="nope\n")
    assert result.exception.code == "permission_denied"
    assert grants.active("fake-plugin.write", "T2")


def test_grant_checks_input_before_asking(user_dirs, registry, monkeypatch):
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    result = run(registry, "approvals", "grant", "fake-plugin.write", "--tier", "T3", "--for", "2d")
    assert result.exception.code == "invalid_input"
    assert "type this code" not in result.output
