"""FL-2 commands: `lfmap flows start|status|runs` and `lfmap approvals approve|reject|pending` on flows.resume."""

import json

import pytest
from typer.testing import CliRunner

from lfmap_core import approvals, cli, flows_run
from lfmap_core.approval import audit_path
from lfmap_core.cli import build_app
from lfmap_core.config import app_dir

runner = CliRunner()

FLOW = """
[[flows]]
id = "demo"
trigger = { manual = true }

[[flows.steps]]
id = "one"
call = "fake-plugin.greet"
input = { name = "${trigger.payload.who}" }

[[flows.steps]]
id = "save"
call = "fake-plugin.write"
input = { names = ["${steps.one.output.message}"] }

[[flows.steps]]
id = "review"
approve = "Check\\u001b[31m it"
"""


def run(registry, *args, input=None):
    return runner.invoke(build_app(registry), list(args), input=input)


@pytest.fixture
def put(user_dirs, monkeypatch):
    def _put(text: str = FLOW) -> None:
        path = user_dirs / "flows.toml"
        path.write_text(text, encoding="utf-8")
        monkeypatch.setenv("LFMAP_FLOWS", str(path))

    return _put


@pytest.fixture
def terminal(monkeypatch):
    monkeypatch.setattr(cli, "_interactive", lambda: True)


def audit_records() -> list[dict]:
    return [json.loads(line) for line in audit_path().read_text(encoding="utf-8").splitlines()]


# --- start ----------------------------------------------------------------------------------------------


def test_start_prints_the_status_and_the_approval_to_give(registry, put, user_dirs, terminal):
    put()
    payload = user_dirs / "payload.json"
    payload.write_text(json.dumps({"who": "Ann"}), encoding="utf-8")
    result = run(registry, "flows", "start", "demo", "--input-json", str(payload))
    assert result.exit_code == 0, result.output
    [saved] = flows_run.list_runs()
    assert saved.status == "awaiting_approval" and saved.payload == {"who": "Ann"}
    assert saved.run_id in result.output and "awaiting_approval" in result.output
    assert f"lfmap approvals approve {saved.approval_id}" in result.output


def test_start_without_input_uses_an_empty_payload(registry, put):
    put(
        '[[flows]]\nid = "demo"\ntrigger = { manual = true }\n[[flows.steps]]\nid = "one"\n'
        'call = "fake-plugin.greet"\ninput = { name = "A" }\n'
    )
    result = run(registry, "flows", "start", "demo")
    assert result.exit_code == 0 and "completed" in result.output
    assert flows_run.list_runs()[0].payload == {}


def test_start_exits_1_when_the_run_fails(registry, put):
    put(
        '[[flows]]\nid = "demo"\ntrigger = { manual = true }\n[[flows.steps]]\nid = "one"\n'
        'call = "fake-plugin.greet"\ninput = { name = "error" }\n'
    )
    result = run(registry, "flows", "start", "demo")
    assert result.exit_code == 1 and "failed" in result.output and "not_found" in result.output


def test_start_unknown_flow(registry, put):
    put()
    result = run(registry, "flows", "start", "nope")
    assert result.exception.code == "not_found"


def test_input_json_outside_the_roots_needs_a_person(registry, put, user_dirs):
    put()
    payload = user_dirs / "payload.json"
    payload.write_text("{}", encoding="utf-8")
    result = run(registry, "flows", "start", "demo", "--input-json", str(payload))
    assert result.exception.code == "permission_denied"
    assert flows_run.list_runs() == []


def test_interactive_input_json_read_is_audited(registry, put, user_dirs, terminal):
    put()
    payload = user_dirs / "payload.json"
    payload.write_text(json.dumps({"who": "Ann"}), encoding="utf-8")
    run(registry, "flows", "start", "demo", "--input-json", str(payload))
    outside = [r for r in audit_records() if r.get("reason") == "read_outside_roots"]
    assert len(outside) == 1 and outside[0]["plugin"] == "flows" and outside[0]["target"].endswith("payload.json")


@pytest.mark.parametrize("text", ["[1, 2]", "{not json", '"text"'])
def test_input_json_must_be_a_json_object(registry, put, user_dirs, terminal, text):
    put()
    payload = user_dirs / "payload.json"
    payload.write_text(text, encoding="utf-8")
    result = run(registry, "flows", "start", "demo", "--input-json", str(payload))
    assert result.exception.code == "invalid_input"


@pytest.mark.parametrize("path", ["\\\\server\\share\\p.json", "//server/share/p.json"])
def test_input_json_refuses_network_paths_even_for_a_person(registry, put, terminal, path):
    put()
    result = run(registry, "flows", "start", "demo", "--input-json", path)
    assert result.exception.code == "permission_denied"


def test_input_json_missing_file(registry, put, user_dirs, terminal):
    put()
    result = run(registry, "flows", "start", "demo", "--input-json", str(user_dirs / "none.json"))
    assert result.exception.code == "not_found"


# --- status and runs -------------------------------------------------------------------------------------


def test_status_is_step_by_step_without_outputs(registry, put, terminal, user_dirs):
    put()
    payload = user_dirs / "p.json"
    payload.write_text(json.dumps({"who": "Ann"}), encoding="utf-8")
    run(registry, "flows", "start", "demo", "--input-json", str(payload))
    [saved] = flows_run.list_runs()
    result = run(registry, "flows", "status", saved.run_id)
    assert result.exit_code == 0
    lines = result.output.splitlines()
    assert saved.run_id in lines[0] and "awaiting_approval" in lines[0]
    steps = [line.split() for line in lines[1:4]]
    assert [s[:2] for s in steps] == [["one", "completed"], ["save", "awaiting_approval"], ["review", "pending"]]
    assert "Hello Ann" not in result.output


def test_status_json_has_outputs(registry, put, terminal, user_dirs):
    put()
    payload = user_dirs / "p.json"
    payload.write_text(json.dumps({"who": "Ann"}), encoding="utf-8")
    run(registry, "flows", "start", "demo", "--input-json", str(payload))
    [saved] = flows_run.list_runs()
    data = json.loads(run(registry, "flows", "status", saved.run_id, "--json").output)
    assert data["run_id"] == saved.run_id and data["steps"][0]["output"] == {"message": "Hello Ann"}


def test_status_of_an_unknown_run(registry, put):
    assert run(registry, "flows", "status", "nope").exception.code == "not_found"


def test_runs_lists_recent_runs_without_outputs(registry, put, terminal, user_dirs):
    put()
    payload = user_dirs / "p.json"
    payload.write_text(json.dumps({"who": "Ann"}), encoding="utf-8")
    run(registry, "flows", "start", "demo", "--input-json", str(payload))
    run(registry, "flows", "start", "demo", "--input-json", str(payload))
    result = run(registry, "flows", "runs")
    assert result.exit_code == 0
    rows = [line.split() for line in result.output.splitlines()]
    assert len(rows) == 2 and all(r[1] == "demo" and r[2] == "awaiting_approval" for r in rows)
    assert "Hello Ann" not in result.output
    assert len(run(registry, "flows", "runs", "--limit", "1").output.splitlines()) == 1
    assert run(registry, "flows", "runs", "--flow", "other").output.strip() == ""


# --- approvals on flows.resume ---------------------------------------------------------------------------


def paused_id(registry, put, user_dirs) -> str:
    put()
    payload = user_dirs / "p.json"
    payload.write_text(json.dumps({"who": "Ann"}), encoding="utf-8")
    run(registry, "flows", "start", "demo", "--input-json", str(payload))
    return flows_run.list_runs()[0].approval_id


def test_pending_lists_the_flow_proposal(registry, put, user_dirs, terminal):
    approval_id = paused_id(registry, put, user_dirs)
    result = run(registry, "approvals", "pending")
    assert approval_id in result.output and "flows.resume" in result.output and "T2" in result.output


def test_approve_shows_the_step_and_resumes_in_a_new_process(registry, put, user_dirs, terminal):
    approval_id = paused_id(registry, put, user_dirs)
    result = run(registry, "approvals", "approve", approval_id, input="y\n")
    assert result.exit_code == 0, result.output
    assert "save" in result.output and "fake-plugin.write" in result.output and "Hello Ann" in result.output
    [saved] = flows_run.list_runs()
    # the person approved the write; the approve step "review" is the next stop
    assert saved.status == "awaiting_approval" and saved.approval_id != approval_id
    assert (app_dir() / "approvals" / "done" / f"{approval_id}.json").exists()
    second = run(registry, "approvals", "approve", saved.approval_id, input="y\n")
    assert second.exit_code == 0, second.output
    final = flows_run.load_run(saved.run_id)
    assert final.status == "completed" and [s.status for s in final.steps] == ["completed"] * 3
    assert "completed" in second.output


def test_approve_escapes_control_characters_of_the_step_text(registry, put, user_dirs, terminal):
    paused_id(registry, put, user_dirs)
    first = flows_run.list_runs()[0]
    flows_run.resume(registry, approvals.load(first.approval_id), lambda q: True)
    second = flows_run.list_runs()[0]
    result = run(registry, "approvals", "approve", second.approval_id, input="n\n")
    assert "\x1b" not in result.output and "\\u001b" in result.output


def test_declining_leaves_the_proposal_and_the_run_waiting(registry, put, user_dirs, terminal):
    approval_id = paused_id(registry, put, user_dirs)
    result = run(registry, "approvals", "approve", approval_id, input="n\n")
    assert result.exit_code == 0 and "stays pending" in result.output
    assert flows_run.list_runs()[0].status == "awaiting_approval"
    assert [p.id for p in approvals.pending()] == [approval_id]


def test_approve_needs_a_person(registry, put, user_dirs):
    approval_id = paused_id(registry, put, user_dirs)
    result = run(registry, "approvals", "approve", approval_id, input="y\n")
    assert result.exception.code == "permission_denied"
    assert flows_run.list_runs()[0].status == "awaiting_approval"


def test_approve_refuses_a_changed_flow_and_keeps_the_proposal(registry, put, user_dirs, terminal):
    approval_id = paused_id(registry, put, user_dirs)
    put(FLOW + "\n# edited\n")
    result = run(registry, "approvals", "approve", approval_id, input="y\n")
    assert result.exception.code == "invalid_input" and "flow changed" in result.exception.message
    assert [p.id for p in approvals.pending()] == [approval_id]


def test_reject_rejects_the_run(registry, put, user_dirs, terminal):
    approval_id = paused_id(registry, put, user_dirs)
    result = run(registry, "approvals", "reject", approval_id)
    assert result.exit_code == 0
    [saved] = flows_run.list_runs()
    assert saved.status == "rejected"
    assert (app_dir() / "approvals" / "rejected" / f"{approval_id}.json").exists()
    assert audit_records()[-1]["decision"] == "reject"


def test_reject_needs_a_person(registry, put, user_dirs):
    approval_id = paused_id(registry, put, user_dirs)
    assert run(registry, "approvals", "reject", approval_id).exception.code == "permission_denied"
    assert flows_run.list_runs()[0].status == "awaiting_approval"


def test_pending_sweep_expires_the_run(registry, put, user_dirs, terminal):
    from datetime import UTC, datetime, timedelta

    paused_id(registry, put, user_dirs)
    approvals.sweep(datetime.now(UTC) + timedelta(days=8))
    assert flows_run.list_runs()[0].status == "expired"
    assert run(registry, "approvals", "pending").output.strip() == ""
