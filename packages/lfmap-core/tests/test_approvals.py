import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import anyio
import pytest
from typer.testing import CliRunner

from lfmap_core import approvals, cli, grants, jobs
from lfmap_core.approval import Policy, audit_path, decide, job_decision
from lfmap_core.approvals import approvals_dir
from lfmap_core.cli import build_app
from lfmap_core.errors import ToolError
from lfmap_core.mcp_adapter import build_server

runner = CliRunner()


def run(registry, *args, input=None):
    return runner.invoke(build_app(registry), list(args), input=input)


def write_jobs(user_dirs, monkeypatch, *blocks: str) -> Path:
    path = user_dirs / "jobs.toml"
    path.write_text("\n".join(blocks), encoding="utf-8")
    monkeypatch.setenv("LFMAP_JOBS", str(path))
    return path


def job_block(job_id="nightly", operation="write", input='{ names = ["a"] }', max_tier=0) -> str:
    return (
        f'[[jobs]]\nid = "{job_id}"\nplugin = "fake-plugin"\noperation = "{operation}"\n'
        f'input = {input}\nschedule = {{ daily = "07:30" }}\nmax_tier = {max_tier}\n'
    )


def files(state: str) -> list[Path]:
    return sorted((approvals_dir() / state).glob("*"))


def all_files() -> set[str]:
    return {p.name for p in approvals_dir().rglob("*") if p.is_file()}


def audit_records() -> list[dict]:
    return [json.loads(line) for line in audit_path().read_text(encoding="utf-8").splitlines()]


def queued_id(registry, job_id="nightly") -> str:
    result = run(registry, "jobs", "run", job_id)
    assert result.exception.code == "permission_denied"
    assert result.exception.message == "Queued for approval"
    return result.exception.details["approval_id"]


@pytest.fixture
def terminal(monkeypatch):
    monkeypatch.setattr(cli, "_interactive", lambda: True)


@pytest.mark.parametrize(
    ("tier", "max_tier", "policy", "expected"),
    [
        ("T0", 0, {}, "allow"),
        ("T0", 0, {"T1": "deny"}, "allow"),
        ("T1", 0, {}, "queue"),
        ("T1", 1, {}, "allow"),
        ("T1", 1, {"T1": "allow"}, "allow"),
        ("T1", 1, {"T1": "ask"}, "queue"),
        ("T1", 1, {"T1": "deny"}, "deny"),
        ("T1", 0, {"T1": "deny"}, "deny"),
        ("T2", 0, {}, "queue"),
        ("T2", 1, {}, "queue"),
        ("T2", 1, {"T2": "allow"}, "queue"),
        ("T2", 1, {"T2": "deny"}, "deny"),
        ("T3", 1, {}, "queue"),
        ("T3", 1, {"T3": "allow"}, "queue"),
        ("T3", 1, {"T3": "deny"}, "deny"),
        ("T2", 1, {"operations": {"fake-plugin.write": "deny"}}, "deny"),
    ],
)
def test_job_decision_table(tier, max_tier, policy, expected):
    assert job_decision(Policy.model_validate(policy), "fake-plugin", "write", tier, max_tier) == expected


@pytest.mark.parametrize("tier", ["T2", "T3"])
def test_decide_never_asks_or_preapproves_for_jobs(tier):
    policy = Policy()
    assert decide(policy, "p", "op", tier, "job", {"p.op"}, True, granted=True) == "deny"


def test_max_tier_0_only_queues_a_local_write(user_dirs, monkeypatch, registry):
    write_jobs(user_dirs, monkeypatch, job_block())
    calls = []
    monkeypatch.setattr(jobs, "run_operation", lambda *args, **kwargs: calls.append(args))
    approval_id = queued_id(registry)
    assert calls == []
    [path] = files("pending")
    assert path.name == f"{approval_id}.json"
    proposal = json.loads(path.read_text(encoding="utf-8"))
    assert proposal["job"] == "nightly" and proposal["plugin"] == "fake-plugin" and proposal["operation"] == "write"
    assert proposal["input"] == {"names": ["a"]} and proposal["tier"] == "T1" and proposal["preview"] is None
    created, expires = datetime.fromisoformat(proposal["created"]), datetime.fromisoformat(proposal["expires"])
    assert expires - created == timedelta(days=7)
    last = audit_records()[-1]
    assert last["channel"] == "job" and last["decision"] == "queue" and approval_id in last["reason"]


def test_runtime_escalation_is_queued(user_dirs, monkeypatch, registry):
    write_jobs(user_dirs, monkeypatch, job_block(input='{ names = ["a"], escalate = "overwrite" }', max_tier=1))
    approval_id = queued_id(registry)
    proposal = approvals.load(approval_id)
    assert proposal.tier == "T2" and proposal.reason == "overwrite" and proposal.detail == "out.txt"
    assert [r["decision"] for r in audit_records()] == ["allow", "queue"]


def test_grants_do_not_cover_jobs(user_dirs, monkeypatch, registry):
    write_jobs(user_dirs, monkeypatch, job_block(input='{ names = ["a"], escalate = "external" }', max_tier=1))
    grants.add("fake-plugin.write", "T3", timedelta(hours=1))
    assert approvals.load(queued_id(registry)).tier == "T3"


def test_policy_deny_refuses_without_a_proposal(user_dirs, monkeypatch, registry):
    (user_dirs / "config.toml").write_text('[approval]\nT1 = "deny"\n', encoding="utf-8")
    write_jobs(user_dirs, monkeypatch, job_block(max_tier=1))
    result = run(registry, "jobs", "run", "nightly")
    assert result.exception.code == "permission_denied" and "approval_id" not in result.exception.details
    assert all_files() == set()
    assert audit_records()[-1]["decision"] == "deny"


def test_identical_proposals_are_merged(user_dirs, monkeypatch, registry):
    write_jobs(user_dirs, monkeypatch, job_block(), job_block("other", input='{ names = ["b"] }'))
    first = queued_id(registry)
    assert queued_id(registry) == first
    assert queued_id(registry, "other") != first
    assert len(files("pending")) == 2


def test_approve_runs_once_and_moves_to_done(user_dirs, monkeypatch, registry, terminal):
    write_jobs(user_dirs, monkeypatch, job_block())
    approval_id = queued_id(registry)
    seen = {}
    real = cli.run_operation

    def spy(entry, name, payload, variables=None, **kwargs):
        seen.update(name=name, payload=payload, **kwargs)
        return real(entry, name, payload, variables, **kwargs)

    monkeypatch.setattr(cli, "run_operation", spy)
    result = run(registry, "approvals", "approve", approval_id, "--json", input="y\n")
    assert result.exit_code == 0, result.output
    assert '"message": "a"' in result.output
    assert seen["payload"] == {"names": ["a"]} and seen["channel"] == "cli" and not seen.get("explicit_read")
    assert files("pending") == [] and [p.name for p in files("done")] == [f"{approval_id}.json"]
    records = audit_records()
    assert [r["decision"] for r in records[-2:]] == ["approve", "allow"]
    assert records[-1]["channel"] == "cli" and f"approved {approval_id}" in records[-1]["reason"]
    again = run(registry, "approvals", "approve", approval_id, input="y\n")
    assert again.exception.code == "not_found"


def test_approve_answered_no_stays_pending(user_dirs, monkeypatch, registry, terminal):
    write_jobs(user_dirs, monkeypatch, job_block())
    approval_id = queued_id(registry)
    result = run(registry, "approvals", "approve", approval_id, input="n\n")
    assert result.exit_code == 0 and "stays pending" in result.output
    assert [p.stem for p in files("pending")] == [approval_id]


def test_approve_and_reject_need_a_terminal(user_dirs, monkeypatch, registry):
    write_jobs(user_dirs, monkeypatch, job_block())
    approval_id = queued_id(registry)
    before = all_files()
    for action in ("approve", "reject"):
        result = run(registry, "approvals", action, approval_id, input="y\n")
        assert result.exception.code == "permission_denied"
    assert all_files() == before and [p.stem for p in files("pending")] == [approval_id]


def test_escalation_above_the_approved_tier_asks_again(user_dirs, monkeypatch, registry, terminal):
    write_jobs(user_dirs, monkeypatch, job_block(input='{ names = ["a"], escalate = "overwrite" }'))
    approval_id = queued_id(registry)
    assert approvals.load(approval_id).tier == "T1"
    refused = run(registry, "approvals", "approve", approval_id, input="y\nn\n")
    assert refused.exception.code == "permission_denied"
    assert [p.stem for p in files("done")] == [approval_id]


def test_forged_tier_cannot_lower_the_declared_one(user_dirs, monkeypatch, external_registry, terminal):
    write_jobs(user_dirs, monkeypatch, job_block(max_tier=1))
    approval_id = queued_id(external_registry)
    path = approvals_dir() / "pending" / f"{approval_id}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps({**data, "tier": "T1"}), encoding="utf-8")
    refused = run(external_registry, "approvals", "approve", approval_id, input="y\nn\n")
    assert refused.exception.code == "permission_denied"
    assert audit_records()[-1]["tier"] == "T3" and audit_records()[-1]["decision"] == "deny"


def test_reject_moves_to_rejected(user_dirs, monkeypatch, registry, terminal):
    write_jobs(user_dirs, monkeypatch, job_block())
    approval_id = queued_id(registry)
    result = run(registry, "approvals", "reject", approval_id)
    assert result.exit_code == 0
    assert files("pending") == [] and [p.stem for p in files("rejected")] == [approval_id]
    assert audit_records()[-1]["decision"] == "reject"


def test_expired_proposals_move_to_expired(user_dirs, monkeypatch, registry, terminal):
    write_jobs(user_dirs, monkeypatch, job_block())
    job = jobs.load_jobs()[0]
    old = approvals.queue(job, "T1", "side_effects", "", timedelta(days=7), now=datetime(2020, 1, 1, tzinfo=UTC))
    fresh = queued_id(registry)
    listed = json.loads(run(registry, "approvals", "pending", "--json").output)
    assert [p["id"] for p in listed] == [fresh]
    assert [p.stem for p in files("expired")] == [old]
    assert run(registry, "approvals", "approve", old, input="y\n").exception.code == "not_found"


def test_pending_text_output(user_dirs, monkeypatch, registry):
    write_jobs(user_dirs, monkeypatch, job_block())
    approval_id = queued_id(registry)
    output = run(registry, "approvals", "pending").output
    assert approval_id in output and "fake-plugin.write" in output and "T1" in output


@pytest.mark.parametrize("days", [3, 30])
def test_ttl_from_config(user_dirs, monkeypatch, registry, days):
    (user_dirs / "config.toml").write_text(f"[jobs]\napproval_ttl_days = {days}\n", encoding="utf-8")
    write_jobs(user_dirs, monkeypatch, job_block())
    proposal = approvals.load(queued_id(registry))
    assert proposal.expires - proposal.created == timedelta(days=days)


@pytest.mark.parametrize("value", [0, 31, "7", True, 1.5])
def test_invalid_ttl_is_rejected(value):
    with pytest.raises(ToolError) as error:
        approvals.ttl({"jobs": {"approval_ttl_days": value}})
    assert error.value.code == "invalid_input"


@pytest.mark.parametrize(
    "bad_id",
    ["../x", "a/b", "/etc/passwd", "C:\\x", "\\\\server\\share\\x", "20261021T073000Z-a-1234567", ""],
)
def test_bad_ids_are_refused_before_any_io(user_dirs, registry, terminal, bad_id):
    with pytest.raises(ToolError) as error:
        approvals.load(bad_id)
    assert error.value.code == "invalid_input"
    assert run(registry, "approvals", "approve", bad_id, input="y\n").exception.code == "invalid_input"


def test_forged_files_are_never_approved(user_dirs, monkeypatch, registry, terminal):
    write_jobs(user_dirs, monkeypatch, job_block())
    approval_id = queued_id(registry)
    folder = approvals_dir() / "pending"
    data = json.loads((folder / f"{approval_id}.json").read_text(encoding="utf-8"))
    (folder / f"{approval_id}.json").write_text(json.dumps({**data, "yes": True}), encoding="utf-8")
    renamed = approval_id[:-8] + "00000000"
    (folder / f"{renamed}.json").write_text(json.dumps(data), encoding="utf-8")
    for forged in (approval_id, renamed):
        assert run(registry, "approvals", "approve", forged, input="y\n").exception.code == "invalid_input"
    assert approvals.pending() == []


def test_no_proposal_file_is_ever_deleted(user_dirs, monkeypatch, registry, terminal):
    write_jobs(user_dirs, monkeypatch, job_block(), job_block("b", input='{ names = ["b"] }'))
    job = jobs.load_jobs()[0]
    seen = {approvals.queue(job, "T1", "side_effects", "", timedelta(days=1), now=datetime(2020, 1, 1, tzinfo=UTC))}
    seen |= {queued_id(registry), queued_id(registry, "b")}
    first, second = sorted(seen - {min(seen)})
    run(registry, "approvals", "approve", first, input="y\n")
    run(registry, "approvals", "reject", second)
    run(registry, "approvals", "pending")
    assert all_files() == {f"{i}.json" for i in seen}
    assert {p.parent.name for p in approvals_dir().rglob("*.json")} == {"done", "rejected", "expired"}


def test_mcp_exposes_no_approval_tool(registry):
    tools = anyio.run(build_server(registry, []).list_tools)
    assert not any("approv" in tool.name for tool in tools)


def test_invalid_input_is_refused_before_queueing(user_dirs, monkeypatch, registry):
    write_jobs(user_dirs, monkeypatch, job_block(input='{ names = "not a list" }'))
    assert run(registry, "jobs", "run", "nightly").exception.code == "invalid_input"
    assert all_files() == set()


def test_approve_refuses_invalid_input_and_keeps_the_proposal(user_dirs, monkeypatch, registry, terminal):
    write_jobs(user_dirs, monkeypatch, job_block())
    approval_id = queued_id(registry)
    path = approvals_dir() / "pending" / f"{approval_id}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps({**data, "input": {"names": 5}}), encoding="utf-8")
    assert run(registry, "approvals", "approve", approval_id, input="y\n").exception.code == "invalid_input"
    assert [p.stem for p in files("pending")] == [approval_id]


def test_approve_summary_cannot_hide_anything(user_dirs, monkeypatch, registry, terminal):
    write_jobs(user_dirs, monkeypatch, job_block())
    approval_id = queued_id(registry)
    path = approvals_dir() / "pending" / f"{approval_id}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    hidden = {**data, "reason": "x\x1b[8m", "detail": "\u202eevil", "input": {"names": ["\u202eb"]}}
    path.write_text(json.dumps(hidden), encoding="utf-8")
    listed = run(registry, "approvals", "pending").output
    assert "\x1b" not in listed and "\\u001b[8m" in listed
    result = run(registry, "approvals", "approve", approval_id, input="n\n")
    assert "\x1b" not in result.output and "\u202e" not in result.output
    assert "\\u001b[8m" in result.output and "\\u202eevil" in result.output and "\\u202eb" in result.output
