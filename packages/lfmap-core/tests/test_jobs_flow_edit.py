"""R2 of docs/research/2026-11-10-jobs-into-flows-risk-analysis.md: a job edited while paused starts a new run."""

import pytest
from typer.testing import CliRunner

from lfmap_core import approvals, cli, flows_run
from lfmap_core.approvals import approvals_dir
from lfmap_core.cli import build_app

runner = CliRunner()

NIGHTLY = """
[[jobs]]
id = "nightly"
plugin = "fake-plugin"
operation = "write"
input = { names = ["a"] }
schedule = { daily = "07:30" }
{extra}"""


def write_jobs(path, names="a", extra="", declared=True):
    text = NIGHTLY.replace('["a"]', f'["{names}"]').replace("{extra}", extra) if declared else ""
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def jobs_toml(user_dirs, monkeypatch):
    path = user_dirs / "jobs.toml"
    write_jobs(path)
    monkeypatch.setenv("LFMAP_JOBS", str(path))
    return path


def jobs_run(registry):
    return runner.invoke(build_app(registry), ["jobs", "run", "nightly"]).exception


def pending_ids():
    return sorted(p.stem for p in (approvals_dir() / "pending").glob("*.json"))


def expired_ids():
    return sorted(p.stem for p in (approvals_dir() / "expired").glob("*.json"))


def assert_superseded(registry, first_id):
    second = jobs_run(registry)
    assert second.message == "Queued for approval"
    second_id = second.details["approval_id"]
    assert second_id != first_id
    assert expired_ids() == [first_id]
    assert pending_ids() == [second_id]
    waiting, expired = sorted(flows_run.list_runs("nightly"), key=lambda r: r.status)
    assert (waiting.status, waiting.approval_id) == ("awaiting_approval", second_id)
    assert (expired.status, expired.approval_id) == ("expired", first_id)
    assert expired.steps[0].status == "failed"


def test_an_unchanged_job_keeps_its_waiting_run_and_proposal(jobs_toml, registry):
    first_id = jobs_run(registry).details["approval_id"]
    again = jobs_run(registry)
    assert again.message == "Queued for approval" and again.details["approval_id"] == first_id
    assert pending_ids() == [first_id] and expired_ids() == []
    assert [r.status for r in flows_run.list_runs("nightly")] == ["awaiting_approval"]


def test_a_changed_input_expires_the_waiting_run_and_starts_a_new_one(jobs_toml, registry):
    first_id = jobs_run(registry).details["approval_id"]
    write_jobs(jobs_toml, names="b")
    assert_superseded(registry, first_id)


def test_a_job_removed_and_added_again_expires_the_waiting_run(jobs_toml, registry):
    first_id = jobs_run(registry).details["approval_id"]
    write_jobs(jobs_toml, declared=False)
    write_jobs(jobs_toml, names="c")
    assert_superseded(registry, first_id)


def test_a_job_disabled_and_enabled_with_a_changed_input_expires_the_waiting_run(jobs_toml, registry):
    first_id = jobs_run(registry).details["approval_id"]
    write_jobs(jobs_toml, extra="enabled = false\n")
    write_jobs(jobs_toml, names="d", extra="enabled = true\n")
    assert_superseded(registry, first_id)


def test_approving_the_old_proposal_after_an_edit_names_reject(jobs_toml, registry, monkeypatch):
    first_id = jobs_run(registry).details["approval_id"]
    write_jobs(jobs_toml, names="b")
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    result = runner.invoke(build_app(registry), ["approvals", "approve", first_id], input="y\n")
    assert result.exception.code == "invalid_input"
    assert result.exception.message == f"flow changed; start a new run (or run: lfmap approvals reject {first_id})"
    assert approvals.load(first_id).id == first_id
