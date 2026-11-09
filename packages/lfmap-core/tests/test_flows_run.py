"""FL-2: running flows (docs/specs/flows.md sections 5 and 10). The plugin is conftest's `fake-plugin`:
`greet` is T0, `write` is T1 and may escalate to T2 or T3 inside the call."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from lfmap_core import approvals, flows_run, jobs_flow
from lfmap_core.approval import audit_path
from lfmap_core.config import app_dir
from lfmap_core.errors import ToolError
from lfmap_core.events_payload import MAX_PAYLOAD_BYTES

THREE = """
[[flows]]
id = "chain"
trigger = { manual = true }

[[flows.steps]]
id = "one"
call = "fake-plugin.greet"
input = { name = "${trigger.payload.who}" }

[[flows.steps]]
id = "two"
call = "fake-plugin.greet"
input = { name = "${steps.one.output.message}", shout = true }

[[flows.steps]]
id = "three"
call = "fake-plugin.greet"
input = { name = "${steps.two.output.message}" }
when = "${steps.two.output.message}"
"""


def flow_toml(*steps: str, max_tier: int = 0, flow_id: str = "demo") -> str:
    body = "\n".join(f"[[flows.steps]]\n{step}\n" for step in steps)
    return f'[[flows]]\nid = "{flow_id}"\nmax_tier = {max_tier}\ntrigger = {{ manual = true }}\n\n{body}'


def greet(step_id: str, name: str = "A", extra: str = "") -> str:
    return f'id = "{step_id}"\ncall = "fake-plugin.greet"\ninput = {{ name = "{name}"{extra} }}'


def write_step(step_id: str, escalate: str | None = None, name: str = "a") -> str:
    more = f', escalate = "{escalate}"' if escalate else ""
    return f'id = "{step_id}"\ncall = "fake-plugin.write"\ninput = {{ names = ["{name}"]{more} }}'


@pytest.fixture
def put(user_dirs, monkeypatch):
    def _put(text: str) -> Path:
        path = user_dirs / "flows.toml"
        path.write_text(text, encoding="utf-8")
        monkeypatch.setenv("LFMAP_FLOWS", str(path))
        return path

    return _put


def audit_records() -> list[dict]:
    return [json.loads(line) for line in audit_path().read_text(encoding="utf-8").splitlines()]


def pending() -> list[approvals.Proposal]:
    return approvals.pending()


def statuses(run: flows_run.FlowRun) -> list[str]:
    return [step.status for step in run.steps]


def run_file(run_id: str) -> Path:
    return app_dir() / "flows" / "runs" / f"{run_id}.json"


def yes(question: str) -> bool:
    return True


# --- a flow that needs nobody -------------------------------------------------------------------


def test_three_step_flow_runs_to_completed(registry, put):
    put(THREE)
    run = flows_run.start(registry, "chain", {"who": "Ann"})
    assert run.status == "completed" and run.flow == "chain" and run.approval_id is None
    assert statuses(run) == ["completed"] * 3
    assert run.steps[0].output == {"message": "Hello Ann"}
    assert run.steps[1].output == {"message": "HELLO HELLO ANN"}
    assert run.steps[2].output == {"message": "Hello HELLO HELLO ANN"}
    assert pending() == []


def test_state_file_holds_references_and_a_hash_of_the_flow_file(registry, put):
    path = put(THREE)
    run = flows_run.start(registry, "chain", {"who": "Ann"})
    record = json.loads(run_file(run.run_id).read_text(encoding="utf-8"))
    assert record["flow"] == "chain" and record["status"] == "completed" and record["payload"] == {"who": "Ann"}
    assert record["flow_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert [s["id"] for s in record["steps"]] == ["one", "two", "three"]
    assert record["steps"][0]["output"] == {"message": "Hello Ann"}
    assert not list(run_file(run.run_id).parent.glob("*.tmp"))


def test_run_id_is_generated_and_unique(registry, put):
    put(THREE)
    first = flows_run.start(registry, "chain", {"who": "A"})
    second = flows_run.start(registry, "chain", {"who": "A"})
    assert first.run_id != second.run_id
    assert first.run_id.startswith("2") and "chain" in first.run_id


def test_when_false_skips_a_step_and_its_output_is_not_in_scope(registry, put):
    put(
        flow_toml(
            greet("one") + '\nwhen = "${trigger.payload.go}"',
            greet("two", "${steps.one.output.message}") + '\nwhen = "${steps.one.output.message}"',
        )
    )
    run = flows_run.start(registry, "demo", {"go": False})
    assert run.status == "completed" and statuses(run) == ["skipped", "skipped"]
    assert run.steps[0].output is None


def test_missing_key_in_input_fails_the_step_and_names_it(registry, put):
    put(flow_toml(greet("one", "${trigger.payload.who}")))
    run = flows_run.start(registry, "demo", {})
    assert run.status == "failed" and run.steps[0].status == "failed"
    assert run.steps[0].error["code"] == "invalid_input" and "one" in run.steps[0].error["message"]


def test_input_with_a_reference_is_validated_after_resolving(registry, put):
    put(flow_toml('id = "one"\ncall = "fake-plugin.greet"\ninput = { name = "A", times = "${trigger.payload.n}" }'))
    run = flows_run.start(registry, "demo", {"n": "many"})
    assert run.status == "failed" and run.steps[0].error["code"] == "invalid_input"


def test_start_refuses_what_check_flow_refuses(registry, put, user_dirs):
    put(flow_toml('id = "one"\ncall = "nope.x"'))
    with pytest.raises(ToolError) as caught:
        flows_run.start(registry, "demo", {})
    assert caught.value.code == "invalid_input" and "nope" in str(caught.value.details)
    assert not (app_dir() / "flows" / "runs").exists()


def test_start_unknown_or_disabled_flow(registry, put):
    put(flow_toml(greet("one")).replace("max_tier = 0", "max_tier = 0\nenabled = false"))
    with pytest.raises(ToolError) as unknown:
        flows_run.start(registry, "other", {})
    assert unknown.value.code == "not_found"
    with pytest.raises(ToolError) as disabled:
        flows_run.start(registry, "demo", {})
    assert disabled.value.code == "invalid_input" and "disabled" in disabled.value.message


@pytest.mark.parametrize("payload", [["not", "an", "object"], {"x": "y" * (MAX_PAYLOAD_BYTES + 1)}])
def test_start_refuses_a_bad_trigger_payload(registry, put, payload):
    put(THREE)
    with pytest.raises(ToolError) as caught:
        flows_run.start(registry, "chain", payload)
    assert caught.value.code == "invalid_input"


# --- failing steps and big outputs ----------------------------------------------------------------


def test_failing_step_fails_the_run_and_keeps_earlier_outputs(registry, put):
    put(flow_toml(greet("one"), greet("boom", "error"), greet("never")))
    run = flows_run.start(registry, "demo", {})
    assert run.status == "failed" and statuses(run) == ["completed", "failed", "pending"]
    assert run.steps[0].output == {"message": "Hello A"}
    assert run.steps[1].error["code"] == "not_found" and run.error["code"] == "not_found"
    saved = json.loads(run_file(run.run_id).read_text(encoding="utf-8"))
    assert saved["status"] == "failed" and saved["steps"][0]["output"] == {"message": "Hello A"}


def test_output_too_large_fails_the_step(registry, put):
    big = 'id = "big"\ncall = "fake-plugin.greet"\ninput = { name = "AAAAAAAA", times = 20000 }'
    put(flow_toml(big, greet("never")))
    run = flows_run.start(registry, "demo", {})
    assert run.status == "failed" and statuses(run) == ["failed", "pending"]
    assert run.steps[0].output is None
    assert run.steps[0].error["details"]["reason"] == "output_too_large"
    assert run.steps[0].error["details"]["limit"] == MAX_PAYLOAD_BYTES
    assert run_file(run.run_id).stat().st_size < MAX_PAYLOAD_BYTES


def test_an_unexpected_exception_fails_the_run_instead_of_leaving_it_running(registry, put, monkeypatch):
    put(flow_toml(greet("one")))

    def explode(*args, **kwargs):
        raise RuntimeError("backend crashed with secret text")

    monkeypatch.setattr(jobs_flow, "run_operation", explode)
    run = flows_run.start(registry, "demo", {})
    assert run.status == "failed" and run.steps[0].error["code"] == "internal"
    assert "secret text" not in json.dumps(run.model_dump(mode="json"))


def test_policy_deny_fails_without_a_proposal(registry, put, user_dirs):
    (user_dirs / "config.toml").write_text('[approval]\nT1 = "deny"\n', encoding="utf-8")
    put(flow_toml(write_step("w"), max_tier=1))
    run = flows_run.start(registry, "demo", {})
    assert run.status == "failed" and run.steps[0].error["code"] == "permission_denied"
    assert pending() == [] and audit_records()[-1]["decision"] == "deny"


# --- the ceiling and the pause ------------------------------------------------------------------


def test_step_above_the_ceiling_pauses_with_one_flows_resume_proposal(registry, put):
    put(flow_toml(greet("one"), write_step("save", name="${trigger.payload.who}"), greet("last")))
    run = flows_run.start(registry, "demo", {"who": "Ann"})
    assert run.status == "awaiting_approval" and statuses(run) == ["completed", "awaiting_approval", "pending"]
    [proposal] = pending()
    assert proposal.id == run.approval_id
    assert (proposal.job, proposal.plugin, proposal.operation, proposal.tier) == ("flows", "flows", "resume", "T2")
    assert proposal.input["run_id"] == run.run_id and proposal.input["step"] == "save"
    assert proposal.input["call"] == "fake-plugin.write"
    assert proposal.input["resolved_input"] == {"names": ["Ann"]}
    assert "save" in proposal.reason and "T1" in proposal.reason
    assert run.steps[1].output is None
    saved = json.loads(run_file(run.run_id).read_text(encoding="utf-8"))
    assert saved["status"] == "awaiting_approval" and saved["approval_id"] == proposal.id


def test_ceiling_one_lets_a_local_write_run(registry, put):
    put(flow_toml(write_step("save"), max_tier=1))
    run = flows_run.start(registry, "demo", {})
    assert run.status == "completed" and run.steps[0].output == {"message": "a"}
    assert pending() == []


def test_escalation_inside_a_step_pauses_too(registry, put):
    put(flow_toml(write_step("save", escalate="overwrite"), max_tier=1))
    run = flows_run.start(registry, "demo", {})
    assert run.status == "awaiting_approval"
    [proposal] = pending()
    assert proposal.tier == "T2" and proposal.plugin == "flows" and "overwrite" in proposal.reason
    assert proposal.detail == "out.txt"


def test_approve_step_pauses_and_its_text_is_the_reason(registry, put):
    put(flow_toml(greet("one"), 'id = "review"\napprove = "Check the file before it is shared"', greet("after")))
    run = flows_run.start(registry, "demo", {})
    assert run.status == "awaiting_approval" and statuses(run) == ["completed", "awaiting_approval", "pending"]
    [proposal] = pending()
    assert proposal.reason.endswith("Check the file before it is shared")
    assert proposal.input["step"] == "review" and proposal.input["call"] is None
    assert proposal.input["resolved_input"] == {}


def test_resume_after_a_restart_finishes_the_run(registry, put):
    put(flow_toml(greet("one"), write_step("save"), greet("last", "${steps.save.output.message}")))
    paused = flows_run.start(registry, "demo", {})
    # a new process knows only the files: the proposal id and what is on disk
    proposal = approvals.load(paused.approval_id)
    run = flows_run.resume(registry, proposal, yes)
    assert run.run_id == paused.run_id and run.status == "completed" and run.approval_id is None
    assert statuses(run) == ["completed"] * 3
    assert run.steps[1].output == {"message": "a"} and run.steps[2].output == {"message": "Hello a"}
    assert json.loads(run_file(run.run_id).read_text(encoding="utf-8"))["status"] == "completed"


def test_resuming_an_approve_step_just_passes(registry, put):
    put(flow_toml('id = "review"\napprove = "Look"', greet("after")))
    paused = flows_run.start(registry, "demo", {})
    run = flows_run.resume(registry, approvals.load(paused.approval_id), yes)
    assert run.status == "completed" and statuses(run) == ["completed", "completed"]


def test_resume_runs_an_escalation_the_person_saw(registry, put):
    put(flow_toml(write_step("save", escalate="overwrite"), max_tier=1))
    paused = flows_run.start(registry, "demo", {})
    run = flows_run.resume(registry, approvals.load(paused.approval_id), lambda question: pytest.fail(question))
    assert run.status == "completed" and run.steps[0].output == {"message": "a"}


def test_a_higher_tier_than_the_proposal_asks_again(registry, put):
    put(flow_toml(write_step("save", escalate="external"), max_tier=1))
    paused = flows_run.start(registry, "demo", {})
    asked = []
    run = flows_run.resume(registry, approvals.load(paused.approval_id), lambda q: asked.append(q) or False)
    assert len(asked) == 1 and run.status == "failed" and run.steps[0].error["code"] == "permission_denied"


def test_a_later_step_above_the_ceiling_pauses_again_with_a_new_proposal(registry, put):
    put(flow_toml(write_step("first", name="x"), write_step("second", name="y"), greet("last")))
    paused = flows_run.start(registry, "demo", {})
    again = flows_run.resume(registry, approvals.load(paused.approval_id), yes)
    assert again.status == "awaiting_approval" and statuses(again) == ["completed", "awaiting_approval", "pending"]
    assert again.approval_id != paused.approval_id
    [proposal] = pending()
    assert proposal.id == again.approval_id and proposal.input["step"] == "second"
    done = flows_run.resume(registry, approvals.load(again.approval_id), yes)
    assert done.status == "completed" and statuses(done) == ["completed"] * 3


def test_resume_refuses_a_changed_flow_file(registry, put):
    path = put(flow_toml(write_step("save"), greet("last")))
    paused = flows_run.start(registry, "demo", {})
    path.write_text(path.read_text(encoding="utf-8") + "\n# edited\n", encoding="utf-8")
    with pytest.raises(ToolError) as caught:
        flows_run.resume(registry, approvals.load(paused.approval_id), yes)
    assert caught.value.code == "invalid_input" and "flow changed; start a new run" in caught.value.message
    assert flows_run.load_run(paused.run_id).status == "awaiting_approval"
    assert [p.id for p in pending()] == [paused.approval_id]


def test_resume_refuses_a_run_that_is_not_waiting(registry, put):
    put(flow_toml(write_step("save")))
    paused = flows_run.start(registry, "demo", {})
    proposal = approvals.load(paused.approval_id)
    flows_run.resume(registry, proposal, yes)
    with pytest.raises(ToolError) as caught:
        flows_run.resume(registry, proposal, yes)
    assert caught.value.code == "invalid_input" and "not waiting" in caught.value.message


def _forged(proposal: approvals.Proposal, **input_changes) -> approvals.Proposal:
    return proposal.model_copy(update={"input": {**proposal.input, **input_changes}})


@pytest.mark.parametrize(
    "changes",
    [
        {"resolved_input": {"names": ["something else"]}},
        {"step": "last"},
        {"call": "fake-plugin.greet"},
        {"run_id": "no-such-run"},
        {"run_id": "../escape"},
    ],
)
def test_a_proposal_that_does_not_match_the_run_is_refused(registry, put, changes):
    put(flow_toml(write_step("save"), greet("last")))
    paused = flows_run.start(registry, "demo", {})
    forged = _forged(approvals.load(paused.approval_id), **changes)
    with pytest.raises(ToolError) as caught:
        flows_run.resume(registry, forged, yes)
    assert caught.value.code in ("invalid_input", "not_found")
    assert flows_run.load_run(paused.run_id).status == "awaiting_approval"


def test_a_proposal_of_another_id_is_refused(registry, put):
    put(flow_toml(write_step("save")))
    paused = flows_run.start(registry, "demo", {})
    other = approvals.load(paused.approval_id).model_copy(update={"id": "20990101T000000Z-flows-deadbeef"})
    with pytest.raises(ToolError) as caught:
        flows_run.resume(registry, other, yes)
    assert caught.value.code == "invalid_input"


def test_a_proposal_that_is_not_flows_resume_is_refused(registry, put):
    put(flow_toml(write_step("save")))
    paused = flows_run.start(registry, "demo", {})
    other = approvals.load(paused.approval_id).model_copy(update={"operation": "other"})
    with pytest.raises(ToolError):
        flows_run.resume(registry, other, yes)


# --- reject, expiry ---------------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["rejected", "expired"])
def test_close_marks_the_run_and_the_waiting_step(registry, put, status):
    put(flow_toml(write_step("save"), greet("last")))
    paused = flows_run.start(registry, "demo", {})
    flows_run.close(approvals.load(paused.approval_id), status)
    run = flows_run.load_run(paused.run_id)
    assert run.status == status and run.steps[0].status == "failed" and run.steps[1].status == "pending"
    assert run.approval_id == paused.approval_id


def test_close_ignores_a_proposal_the_run_is_not_waiting_for(registry, put):
    put(flow_toml(write_step("save")))
    paused = flows_run.start(registry, "demo", {})
    proposal = approvals.load(paused.approval_id)
    flows_run.close(proposal.model_copy(update={"id": "20990101T000000Z-flows-deadbeef"}), "rejected")
    flows_run.close(_forged(proposal, run_id="no-such-run"), "rejected")
    assert flows_run.load_run(paused.run_id).status == "awaiting_approval"


def test_an_expired_proposal_expires_the_run_at_the_next_sweep(registry, put):
    put(flow_toml(write_step("save")))
    paused = flows_run.start(registry, "demo", {})
    assert approvals.sweep(datetime.now(UTC) + timedelta(days=8)) == [paused.approval_id]
    run = flows_run.load_run(paused.run_id)
    assert run.status == "expired"
    assert (app_dir() / "approvals" / "expired" / f"{paused.approval_id}.json").exists()


def test_a_fresh_proposal_does_not_expire_the_run(registry, put):
    put(flow_toml(write_step("save")))
    paused = flows_run.start(registry, "demo", {})
    assert approvals.sweep() == []
    assert flows_run.load_run(paused.run_id).status == "awaiting_approval"


# --- events: one run per event ---------------------------------------------------------------------


def test_the_same_run_id_never_starts_a_second_run(registry, put):
    put(flow_toml(greet("one"), write_step("save")))
    run_id = "ev-" + "a" * 32
    first = flows_run.start(registry, "demo", {}, run_id=run_id)
    again = flows_run.start(registry, "demo", {}, run_id=run_id)
    assert first.run_id == again.run_id == run_id and again.status == "awaiting_approval"
    assert len(list(run_file(run_id).parent.glob("*.json"))) == 1
    assert len(pending()) == 1
    assert [r["decision"] for r in audit_records()] == ["queue"]


@pytest.mark.parametrize("run_id", ["../x", "a/b", "a\\b", "", ".hidden", "x" * 200, "a b", "ev-\x1b"])
def test_a_bad_run_id_is_refused_before_any_file_access(registry, put, run_id):
    put(flow_toml(greet("one")))
    with pytest.raises(ToolError) as caught:
        flows_run.start(registry, "demo", {}, run_id=run_id)
    assert caught.value.code == "invalid_input"
    assert not (app_dir() / "flows").exists()


# --- audit ---------------------------------------------------------------------------------------------


def test_calls_below_the_ceiling_are_audited_on_channel_flow(registry, put):
    put(flow_toml(write_step("auto", name="x"), write_step("manual", name="y"), max_tier=1))
    flows_run.start(registry, "demo", {})
    records = audit_records()
    assert [(r["channel"], r["plugin"], r["operation"], r["tier"], r["decision"]) for r in records] == [
        ("flow", "fake-plugin", "write", "T1", "allow")
    ] * 2


def test_queue_and_resume_audit_lines(registry, put):
    put(flow_toml(write_step("save")))
    paused = flows_run.start(registry, "demo", {})
    [queued] = audit_records()
    assert queued["channel"] == "flow" and queued["decision"] == "queue" and paused.approval_id in queued["reason"]
    assert (queued["plugin"], queued["operation"], queued["tier"]) == ("fake-plugin", "write", "T1")
    flows_run.resume(registry, approvals.load(paused.approval_id), yes)
    approved = audit_records()[-1]
    assert approved["channel"] == "cli" and approved["decision"] == "allow"
    assert paused.approval_id in approved["reason"] and approved["operation"] == "write"


def test_audit_lines_never_hold_document_text(registry, put):
    put(flow_toml(greet("one", "SECRET-TEXT"), write_step("save", name="SECRET-TEXT")))
    flows_run.start(registry, "demo", {})
    assert "SECRET-TEXT" not in audit_path().read_text(encoding="utf-8")


# --- reading runs -------------------------------------------------------------------------------------------


def test_load_run_errors(registry, put):
    with pytest.raises(ToolError) as missing:
        flows_run.load_run("nope")
    assert missing.value.code == "not_found"
    with pytest.raises(ToolError) as bad:
        flows_run.load_run("../x")
    assert bad.value.code == "invalid_input"
    runs = app_dir() / "flows" / "runs"
    runs.mkdir(parents=True)
    (runs / "broken.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ToolError) as broken:
        flows_run.load_run("broken")
    assert broken.value.code == "invalid_input"
    (runs / "other.json").write_text(
        flows_run.FlowRun(
            run_id="elsewhere", flow="f", flow_sha256="0", payload={}, steps=[], created=datetime.now(UTC)
        ).model_dump_json(),
        encoding="utf-8",
    )
    with pytest.raises(ToolError) as renamed:
        flows_run.load_run("other")
    assert renamed.value.code == "invalid_input"


def test_list_runs_newest_first_filtered_and_limited(registry, put):
    put(THREE + "\n" + flow_toml(greet("one"), flow_id="other"))
    a = flows_run.start(registry, "chain", {"who": "A"}, run_id="r1")
    b = flows_run.start(registry, "other", {}, run_id="r2")
    c = flows_run.start(registry, "chain", {"who": "C"}, run_id="r3")
    assert [r.run_id for r in flows_run.list_runs()] == [c.run_id, b.run_id, a.run_id]
    assert [r.run_id for r in flows_run.list_runs(flow="chain")] == [c.run_id, a.run_id]
    assert [r.run_id for r in flows_run.list_runs(limit=1)] == [c.run_id]


def test_list_runs_skips_unreadable_files(registry, put):
    put(THREE)
    flows_run.start(registry, "chain", {"who": "A"}, run_id="r1")
    (app_dir() / "flows" / "runs" / "junk.json").write_text("{", encoding="utf-8")
    assert [r.run_id for r in flows_run.list_runs()] == ["r1"]
    assert flows_run.list_runs(flow="none") == []


def test_list_runs_without_a_folder(registry):
    assert flows_run.list_runs() == []
