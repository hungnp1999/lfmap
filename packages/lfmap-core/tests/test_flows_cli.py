import json

import pytest
from typer.testing import CliRunner

from lfmap_core.cli import build_app
from lfmap_core.config import app_dir

runner = CliRunner()

GOOD = """
[[flows]]
id = "convert-inbox"
max_tier = 1
trigger = { event = "markitdown.classify.completed" }
steps = [
  { id = "export", call = "fake-plugin.greet", input = { name = "A" } },
  { id = "review", approve = "Check it" },
]

[[flows]]
id = "nightly"
enabled = false
trigger = { schedule = { daily = "06:30" } }
steps = [{ id = "hello", call = "fake-plugin.greet", input = { name = "B" } }]

[[flows]]
id = "by-hand"
trigger = { manual = true }
steps = []
"""

BAD = """
[[flows]]
id = "broken"
max_tier = 2
trigger = { manual = true }
steps = [{ id = "s", call = "nope.x" }]

[[flows]]
id = "also-broken"
trigger = { event = "flows.>" }
steps = [{ id = "s", call = "fake-plugin.greet", input = { name = "${trigger.x}" } }, { id = "s", approve = "x" }]
"""


@pytest.fixture
def put(user_dirs, monkeypatch):
    def _put(text: str) -> None:
        path = user_dirs / "flows.toml"
        path.write_text(text, encoding="utf-8")
        monkeypatch.setenv("LFMAP_FLOWS", str(path))

    return _put


def invoke(registry, *args):
    return runner.invoke(build_app(registry), ["flows", *args])


def test_list(registry, put):
    put(GOOD)
    result = invoke(registry, "list")
    assert result.exit_code == 0
    lines = result.output.splitlines()
    assert lines[0].split() == ["convert-inbox", "event", "markitdown.classify.completed", "enabled", "-"]
    assert "nightly" in lines[1] and "schedule daily 06:30" in lines[1] and "disabled" in lines[1]
    assert "by-hand" in lines[2] and "manual" in lines[2]


def test_list_json_with_last_run(registry, put):
    put(GOOD)
    runs = app_dir() / "flows" / "runs"
    runs.mkdir(parents=True)
    (runs / "r1.json").write_text(json.dumps({"flow": "nightly", "status": "completed"}), encoding="utf-8")
    rows = json.loads(invoke(registry, "list", "--json").output)
    assert [r["id"] for r in rows] == ["convert-inbox", "nightly", "by-hand"]
    assert rows[0] == {
        "id": "convert-inbox",
        "trigger": "event markitdown.classify.completed",
        "enabled": True,
        "steps": 2,
        "last_run": None,
    }
    assert rows[1]["last_run"] == "completed"
    assert rows[1]["enabled"] is False


def test_list_without_a_file(registry, user_dirs, monkeypatch):
    monkeypatch.setenv("LFMAP_FLOWS", str(user_dirs / "none.toml"))
    result = invoke(registry, "list")
    assert result.exit_code == 0
    assert result.output.strip() == ""
    assert json.loads(invoke(registry, "list", "--json").output) == []


def test_check_ok(registry, put):
    put(GOOD)
    result = invoke(registry, "check")
    assert result.exit_code == 0, result.output
    assert "ok" in result.output.lower(), result.output


def test_check_exits_1_on_findings(registry, put):
    put(BAD)
    result = invoke(registry, "check")
    assert result.exit_code == 1
    assert "broken: " in result.output
    assert "also-broken: " in result.output
    assert "max_tier" in result.output
    assert "Unknown plugin 'nope'" in result.output
    assert "duplicate step id" in result.output
    assert "flows." in result.output


def test_check_json(registry, put):
    put(BAD)
    result = invoke(registry, "check", "--json")
    assert result.exit_code == 1
    rows = json.loads(result.output)
    assert {row["flow"] for row in rows} == {"broken", "also-broken"}
    assert all(set(row) == {"flow", "finding"} for row in rows)


def test_check_json_ok_is_an_empty_list(registry, put):
    put(GOOD)
    result = invoke(registry, "check", "--json")
    assert result.exit_code == 0
    assert json.loads(result.output) == []


def test_check_checks_disabled_flows_too(registry, put):
    put('[[flows]]\nid = "off"\nenabled = false\nmax_tier = 5\ntrigger = { manual = true }\nsteps = []\n')
    assert invoke(registry, "check").exit_code == 1


def test_check_without_a_file_is_ok(registry, user_dirs, monkeypatch):
    monkeypatch.setenv("LFMAP_FLOWS", str(user_dirs / "none.toml"))
    assert invoke(registry, "check").exit_code == 0


def test_unreadable_file_is_a_tool_error(registry, put):
    put("[[flows")
    result = invoke(registry, "check")
    assert result.exit_code != 0
    assert result.exception.code == "invalid_input"
