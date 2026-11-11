import json

import pytest
from typer.testing import CliRunner

from lfmap_core import auth, cli, grants, totp
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


class _FakeProtector:
    def protect(self, data: bytes) -> bytes:
        return b"FAKE" + data[::-1]

    def unprotect(self, blob: bytes) -> bytes:
        return blob[4:][::-1]


_SECRET = b"12345678901234567890"
_NOW = 1_000_000.0


@pytest.fixture
def enrolled(monkeypatch):
    fake = _FakeProtector()
    monkeypatch.setattr(auth, "default_protector", lambda: fake)
    monkeypatch.setattr(auth, "now", lambda: _NOW + 60)
    auth.enroll(_SECRET, totp.code_at(_SECRET, _NOW), fake, at=_NOW)
    return _SECRET


def test_require_code_uses_totp_when_enrolled(user_dirs, registry, monkeypatch, enrolled):
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    monkeypatch.setattr(cli, "_confirm_code", lambda: "ABC234")
    good = totp.code_at(enrolled, _NOW + 60)
    result = run(registry, "approvals", "grant", "fake-plugin.write", "--tier", "T2", input=good + "\n")
    assert result.exit_code == 0, result.output
    assert "authenticator app" in result.output and "ABC234" not in result.output
    assert grants.active("fake-plugin.write", "T2")
    replay = run(registry, "approvals", "revoke", "fake-plugin.write", input=good + "\n")
    assert replay.exception.code == "permission_denied" and grants.active("fake-plugin.write", "T2")
    typed = run(registry, "approvals", "revoke", "fake-plugin.write", input="ABC234\n")
    assert typed.exception.code == "permission_denied"
    assert '"decision": "deny"' in audit_path().read_text(encoding="utf-8")


def test_require_code_keeps_the_typed_code_when_not_enrolled(user_dirs, registry, monkeypatch):
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    monkeypatch.setattr(cli, "_confirm_code", lambda: "ABC234")
    result = run(registry, "approvals", "grant", "fake-plugin.write", input="abc234\n")
    assert result.exit_code == 0 and "type this code: ABC234" in result.output


def test_require_code_fails_closed_on_a_corrupt_auth_file(user_dirs, registry, monkeypatch):
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    monkeypatch.setattr(cli, "_confirm_code", lambda: "ABC234")
    auth.auth_path().parent.mkdir(parents=True, exist_ok=True)
    auth.auth_path().write_text("{broken", encoding="utf-8")
    result = run(registry, "approvals", "grant", "fake-plugin.write", input="ABC234\n")
    assert result.exception.code == "permission_denied" and not grants.load()


def test_auth_enroll_refuses_off_windows(user_dirs, registry, monkeypatch):
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    monkeypatch.setattr(auth, "_WINDOWS", False)
    result = run(registry, "auth", "enroll")
    assert result.exception.code == "backend_unavailable"
    assert not auth.auth_path().exists() and "otpauth" not in result.output


def test_auth_commands_need_a_terminal(user_dirs, registry, monkeypatch):
    monkeypatch.setattr(auth, "default_protector", lambda: _FakeProtector())
    for command in ("enroll", "reset"):
        assert run(registry, "auth", command).exception.code == "permission_denied"


def test_auth_reset_needs_the_typed_code_and_returns_to_it(user_dirs, registry, monkeypatch, enrolled):
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    monkeypatch.setattr(cli, "_confirm_code", lambda: "ABC234")
    assert run(registry, "auth", "reset", input="nope\n").exception.code == "permission_denied"
    assert auth.enrolled()
    assert run(registry, "auth", "reset", input="ABC234\n").exit_code == 0
    assert not auth.enrolled() and "auth reset" in audit_path().read_text(encoding="utf-8")
    assert "enrolled: no" in run(registry, "auth", "status").output


def test_auth_enroll_replacing_needs_the_current_code(user_dirs, registry, monkeypatch, enrolled):
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    before = auth.auth_path().read_text(encoding="utf-8")
    refused = run(registry, "auth", "enroll", input="000000\n")
    assert refused.exception.code == "permission_denied" and "otpauth" not in refused.output
    assert auth.auth_path().read_text(encoding="utf-8").replace("failures", "") != ""
    assert json.loads(before)["secret"] == json.loads(auth.auth_path().read_text(encoding="utf-8"))["secret"]


def _queue_proposal(user_dirs, monkeypatch, registry, escalate: str) -> str:
    from lfmap_core import approvals, jobs
    from lfmap_core.approval import Policy
    from lfmap_core.config import load_config
    from lfmap_core.errors import ToolError
    from lfmap_core.runtime import call_tier, run_operation

    path = user_dirs / "jobs.toml"
    path.write_text(
        '[[jobs]]\nid = "nightly"\nplugin = "fake-plugin"\noperation = "write"\n'
        f'input = {{ names = ["a"], escalate = "{escalate}" }}\n'
        'schedule = { daily = "07:30" }\nmax_tier = 0\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("LFMAP_JOBS", str(path))
    job = jobs.load_jobs()[0]
    entry, config = registry.get(job.plugin), load_config()
    gate = approvals.JobApprover(job, Policy.from_config(config), approvals.ttl(config))
    with pytest.raises(ToolError) as error:
        gate(call_tier(entry, job.operation, job.input, config), "side_effects")
        run_operation(entry, job.operation, job.input, channel="job", approver=gate)
    return error.value.details["approval_id"]


def test_t3_proposal_needs_code(user_dirs, external_registry, monkeypatch, enrolled):
    from lfmap_core.approvals import approvals_dir

    monkeypatch.setattr(cli, "_interactive", lambda: True)
    t3 = _queue_proposal(user_dirs, monkeypatch, external_registry, "overwrite")
    assert json.loads(next((approvals_dir() / "pending").glob("*.json")).read_text(encoding="utf-8"))["tier"] == "T3"
    refused = run(external_registry, "approvals", "approve", t3, input="000000\n")
    assert refused.exception.code == "permission_denied"
    assert (approvals_dir() / "pending" / f"{t3}.json").exists()
    good = totp.code_at(enrolled, _NOW + 60)
    accepted = run(external_registry, "approvals", "approve", t3, input=good + "\ny\n")
    assert accepted.exit_code == 0, accepted.output
    assert (approvals_dir() / "done" / f"{t3}.json").exists()


def test_t2_proposal_does_not_need_the_code(user_dirs, registry, monkeypatch, enrolled):
    from lfmap_core.approvals import approvals_dir

    monkeypatch.setattr(cli, "_interactive", lambda: True)
    t2 = _queue_proposal(user_dirs, monkeypatch, registry, "overwrite")
    result = run(registry, "approvals", "approve", t2, input="y\ny\n")
    assert result.exit_code == 0, result.output
    assert "authenticator" not in result.output and (approvals_dir() / "done" / f"{t2}.json").exists()
