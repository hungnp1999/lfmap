import json
from datetime import timedelta

import pytest
from typer.testing import CliRunner

from lfmap_core import approvals, cli, flows_run, jobs, jobs_flow
from lfmap_core.approvals import approvals_dir
from lfmap_core.cli import build_app
from lfmap_core.errors import ToolError

runner = CliRunner()

JOBS = """
[[jobs]]
id = "hello"
plugin = "fake-plugin"
operation = "greet"
input = { name = "A" }
schedule = { every_minutes = 60 }

[[jobs]]
id = "nightly"
plugin = "fake-plugin"
operation = "write"
input = { names = ["a"] }
schedule = { daily = "07:30" }
"""


@pytest.fixture
def jobs_toml(user_dirs, monkeypatch):
    path = user_dirs / "jobs.toml"
    path.write_text(JOBS, encoding="utf-8")
    monkeypatch.setenv("LFMAP_JOBS", str(path))
    return path


def run(registry, *args, input=None):
    return runner.invoke(build_app(registry), list(args), input=input)


def run_files():
    return sorted(flows_run.runs_dir().glob("*.json")) if flows_run.runs_dir().exists() else []


def test_a_job_is_translated_into_a_one_step_scheduled_flow(jobs_toml):
    job = jobs.Job(
        id="j",
        plugin="p",
        operation="o",
        input={"x": 1},
        schedule={"daily": "07:30"},
        max_tier=1,
        enabled=False,
        via="event",
    )
    flow = jobs_flow.job_to_flow(job)
    assert (flow.id, flow.max_tier, flow.enabled) == ("j", 1, False)
    assert flow.trigger.schedule == job.schedule
    [step] = flow.steps
    assert (step.id, step.call, step.input, step.via) == ("run", "p.o", {"x": 1}, "event")


def test_a_job_and_a_flow_may_not_share_an_id(jobs_toml, user_dirs, monkeypatch):
    flows_toml = user_dirs / "flows.toml"
    flows_toml.write_text('[[flows]]\nid = "hello"\ntrigger = { manual = true }\nsteps = []\n', encoding="utf-8")
    monkeypatch.setenv("LFMAP_FLOWS", str(flows_toml))
    with pytest.raises(ToolError, match="share the id hello"):
        jobs_flow.load_all()


def test_flows_list_and_check_include_translated_jobs(jobs_toml, registry):
    listed = json.loads(run(registry, "flows", "list", "--json").output)
    assert {row["id"] for row in listed} == {"hello", "nightly"}
    assert run(registry, "flows", "check").exit_code == 0


def test_a_completed_job_run_leaves_no_run_file(jobs_toml, registry):
    result = run(registry, "jobs", "run", "hello", "--json")
    assert result.exit_code == 0 and json.loads(result.output) == {"message": "Hello A"}
    assert run_files() == []


def test_a_job_above_its_ceiling_pauses_behind_one_flows_resume_proposal(jobs_toml, registry, monkeypatch):
    first = run(registry, "jobs", "run", "nightly").exception
    assert first.code == "permission_denied" and first.message == "Queued for approval"
    approval_id = first.details["approval_id"]
    proposal = approvals.load(approval_id)
    assert approvals.is_flow_resume(proposal) and proposal.job == "nightly"
    assert [r.status for r in flows_run.list_runs("nightly")] == ["awaiting_approval"]
    again = run(registry, "jobs", "run", "nightly").exception
    assert again.details["approval_id"] == approval_id
    assert len(list((approvals_dir() / "pending").glob("*.json"))) == 1


def test_approving_the_proposal_runs_the_job_once(jobs_toml, registry, monkeypatch):
    approval_id = run(registry, "jobs", "run", "nightly").exception.details["approval_id"]
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    result = run(registry, "approvals", "approve", approval_id, input="y\n")
    assert result.exit_code == 0, result.output
    assert [r.status for r in flows_run.list_runs("nightly")] == ["completed"]
    assert list((approvals_dir() / "done").glob("*.json"))
    # the next scheduled run is a new run, queued again
    assert run(registry, "jobs", "run", "nightly").exception.message == "Queued for approval"
    assert len(flows_run.list_runs("nightly")) == 2


def test_a_job_whose_flow_file_hash_changed_cannot_resume(jobs_toml, registry, monkeypatch):
    approval_id = run(registry, "jobs", "run", "nightly").exception.details["approval_id"]
    jobs_toml.write_text(JOBS.replace('names = ["a"]', 'names = ["b"]'), encoding="utf-8")
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    result = run(registry, "approvals", "approve", approval_id, input="y\n")
    assert result.exception.code == "invalid_input" and "flow changed" in result.exception.message


def test_an_expired_proposal_frees_the_job(jobs_toml, registry):
    approval_id = run(registry, "jobs", "run", "nightly").exception.details["approval_id"]
    later = approvals.load(approval_id).expires + timedelta(seconds=1)
    approvals.sweep(later)
    assert [r.status for r in flows_run.list_runs("nightly")] == ["expired"]
