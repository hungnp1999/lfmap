"""R4 of docs/research/2026-11-10-jobs-into-flows-risk-analysis.md: doctor fails where the runner's load fails."""

import pytest
from typer.testing import CliRunner

from lfmap_core import flows_run, jobs_doctor
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
"""
FLOW = (
    '[[flows]]\nid = "ID"\ntrigger = { manual = true }\n'
    '[[flows.steps]]\nid = "s"\ncall = "fake-plugin.greet"\ninput = { name = "B" }\n'
)


@pytest.fixture
def files(user_dirs, monkeypatch):
    jobs_toml, flows_toml = user_dirs / "jobs.toml", user_dirs / "flows.toml"
    jobs_toml.write_text(JOBS, encoding="utf-8")
    monkeypatch.setenv("LFMAP_JOBS", str(jobs_toml))
    monkeypatch.setenv("LFMAP_FLOWS", str(flows_toml))

    def no_machine(args):
        raise ToolError("backend_unavailable", f"{args[0]} was not found (Windows only)")

    monkeypatch.setattr(jobs_doctor, "_run", no_machine)
    return flows_toml


def jobs_file_check(registry):
    return {c.name: c for c in jobs_doctor.run_checks(registry)}["jobs_file"]


def runner_message():
    with pytest.raises(ToolError) as caught:
        flows_run._flows_file()
    return caught.value


def test_a_valid_pair_passes(files, registry):
    files.write_text(FLOW.replace("ID", "other"), encoding="utf-8")
    check = jobs_file_check(registry)
    assert check.ok is True and check.detail.endswith("1 job(s)")


def test_no_flows_file_passes(files, registry):
    assert jobs_file_check(registry).ok is True


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (b"[[flows]\nid =", "is not valid TOML"),
        (b'[[flows]]\nid = "Bad Id"\n', "is invalid"),
        (b"\xff\xfe\x00", "is not UTF-8 text"),
        (FLOW.replace("ID", "hello").encode(), "Job and flow share the id hello"),
    ],
    ids=["toml", "shape", "utf8", "clash"],
)
def test_doctor_fails_with_the_runners_message(files, registry, content, expected):
    files.write_bytes(content)
    raised = runner_message()
    assert expected in raised.message
    check = jobs_file_check(registry)
    assert check.ok is False
    assert raised.message in check.detail
    assert "lfmap flows check" in check.fix


def test_the_cli_prints_the_runners_message_for_a_clash(files, registry):
    files.write_text(FLOW.replace("ID", "hello"), encoding="utf-8")
    result = runner.invoke(build_app(registry), ["jobs", "doctor", "--json"])
    assert result.exit_code == 1
    assert "Job and flow share the id hello" in result.output
