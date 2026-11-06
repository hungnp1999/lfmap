import json
import os
from pathlib import Path

import pytest

from lfmap_core import ToolError
from lfmap_core.config import app_dir
from lfmap_core.flows import Flow, check_flow, flows_path, last_run_status, load_flows, load_flows_file

BASE = """
[[flows]]
id = "convert-inbox"
max_tier = 1

[flows.trigger]
event = "markitdown.classify.completed"

[[flows.steps]]
id = "export"
call = "fake-plugin.write"
input = { names = ["${trigger.payload.output.path}"] }

[[flows.steps]]
id = "greet"
call = "fake-plugin.greet"
input = { name = "Hùng" }
when = "${steps.export.output.message}"

[[flows.steps]]
id = "review"
approve = "Check the converted file before it is shared"
"""


def write(user_dirs: Path, monkeypatch, text: str) -> Path:
    path = user_dirs / "flows.toml"
    path.write_text(text, encoding="utf-8")
    monkeypatch.setenv("LFMAP_FLOWS", str(path))
    return path


def make(**changes) -> Flow:
    data = {
        "id": "demo",
        "trigger": {"manual": True},
        "steps": [{"id": "hello", "call": "fake-plugin.greet", "input": {"name": "A"}}],
    }
    data.update(changes)
    return Flow.model_validate(data)


def step(**fields) -> dict:
    return {"id": "s1", "call": "fake-plugin.greet", "input": {"name": "A"}} | fields


def findings(registry, **changes) -> list[str]:
    return check_flow(registry, make(**changes))


# Loading


def test_flows_path_defaults_next_to_jobs(monkeypatch):
    monkeypatch.delenv("LFMAP_FLOWS", raising=False)
    assert flows_path() == app_dir() / "flows.toml"


def test_flows_path_override(monkeypatch, tmp_path):
    monkeypatch.setenv("LFMAP_FLOWS", str(tmp_path / "x.toml"))
    assert flows_path() == tmp_path / "x.toml"


def test_missing_file_means_no_flows(user_dirs, monkeypatch):
    monkeypatch.setenv("LFMAP_FLOWS", str(user_dirs / "none.toml"))
    assert load_flows() == []


def test_load_flows(user_dirs, monkeypatch):
    write(user_dirs, monkeypatch, BASE)
    (flow,) = load_flows()
    assert flow.id == "convert-inbox"
    assert flow.max_tier == 1
    assert flow.enabled is True
    assert flow.trigger.event == "markitdown.classify.completed"
    assert [s.id for s in flow.steps] == ["export", "greet", "review"]
    assert flow.steps[2].approve == "Check the converted file before it is shared"
    assert flow.steps[1].when == "${steps.export.output.message}"


def test_defaults(user_dirs, monkeypatch):
    write(user_dirs, monkeypatch, '[[flows]]\nid = "a"\ntrigger = { manual = true }\nsteps = []\n')
    (flow,) = load_flows()
    assert (flow.max_tier, flow.enabled) == (0, True)


def test_invalid_toml(user_dirs, monkeypatch):
    write(user_dirs, monkeypatch, "[[flows")
    with pytest.raises(ToolError) as error:
        load_flows()
    assert error.value.code == "invalid_input"


@pytest.mark.parametrize(
    "text",
    [
        '[[flows]]\nid = "a"\nextra = 1\ntrigger = { manual = true }\nsteps = []\n',
        '[[flows]]\nid = "a"\ntrigger = { manual = true, extra = 1 }\nsteps = []\n',
        '[[flows]]\nid = "a"\ntrigger = { manual = true }\nsteps = [{ id = "x", call = "a.b", extra = 1 }]\n',
        '[[flows]]\nid = "A"\ntrigger = { manual = true }\nsteps = []\n',
        '[[flows]]\nid = "1a"\ntrigger = { manual = true }\nsteps = []\n',
        '[[flows]]\nid = "a"\nsteps = []\n',
        '[[flows]]\nid = "a"\ntrigger = {}\nsteps = []\n',
        '[[flows]]\nid = "a"\ntrigger = { manual = true, event = "a.b" }\nsteps = []\n',
        '[[flows]]\nid = "a"\ntrigger = { manual = true, schedule = { daily = "06:30" } }\nsteps = []\n',
        '[[flows]]\nid = "a"\ntrigger = { event = "a.b", schedule = { daily = "06:30" } }\nsteps = []\n',
        '[[flows]]\nid = "a"\ntrigger = { manual = false }\nsteps = []\n',
        '[[flows]]\nid = "a"\ntrigger = { event = "Bad Topic" }\nsteps = []\n',
        '[[flows]]\nid = "a"\ntrigger = { schedule = { daily = "25:00" } }\nsteps = []\n',
        '[[flows]]\nid = "a"\ntrigger = { schedule = {} }\nsteps = []\n',
        2 * '[[flows]]\nid = "a"\ntrigger = { manual = true }\nsteps = []\n',
    ],
)
def test_load_refuses_malformed_files(user_dirs, monkeypatch, text):
    write(user_dirs, monkeypatch, text)
    with pytest.raises(ToolError) as error:
        load_flows()
    assert error.value.code == "invalid_input"


def test_each_trigger_kind_loads(user_dirs, monkeypatch):
    text = (
        '[[flows]]\nid = "m"\ntrigger = { manual = true }\nsteps = []\n'
        '[[flows]]\nid = "s"\ntrigger = { schedule = { daily = "06:30" } }\nsteps = []\n'
        '[[flows]]\nid = "e"\ntrigger = { event = "a.*.completed" }\nsteps = []\n'
    )
    write(user_dirs, monkeypatch, text)
    flows = load_flows_file().flows
    assert [f.trigger.describe() for f in flows] == ["manual", "schedule daily 06:30", "event a.*.completed"]


# Last run status


def test_last_run_status(user_dirs):
    runs = app_dir() / "flows" / "runs"
    assert last_run_status("a") is None
    runs.mkdir(parents=True)
    (runs / "r1.json").write_text(json.dumps({"flow": "a", "status": "completed"}), encoding="utf-8")
    (runs / "r2.json").write_text(json.dumps({"flow": "b", "status": "failed"}), encoding="utf-8")
    (runs / "bad.json").write_text("{", encoding="utf-8")
    assert last_run_status("a") == "completed"
    assert last_run_status("c") is None
    newer = runs / "r3.json"
    newer.write_text(json.dumps({"flow": "a", "status": "awaiting_approval"}), encoding="utf-8")
    os.utime(newer, (4_000_000_000, 4_000_000_000))
    assert last_run_status("a") == "awaiting_approval"


# check_flow: the good flow


def test_good_flow_has_no_findings(registry, user_dirs, monkeypatch):
    write(user_dirs, monkeypatch, BASE)
    assert check_flow(registry, load_flows()[0]) == []


def test_finding_names_the_flow(registry):
    (finding,) = findings(registry, max_tier=2)
    assert finding.startswith("demo: ")


# check_flow: steps


def test_flow_without_steps_has_nothing_to_check(registry):
    assert findings(registry, steps=[]) == []


def test_duplicate_step_ids(registry):
    result = findings(registry, steps=[step(), step()])
    assert any("duplicate step id 's1'" in f for f in result)


@pytest.mark.parametrize("bad", ["Export", "1x", "a_b", "a b", "", "-a", "é"])
def test_step_id_pattern(registry, bad):
    assert any("step id" in f for f in findings(registry, steps=[step(id=bad)]))


@pytest.mark.parametrize("good", ["a", "a1", "a-b-1"])
def test_step_id_pattern_accepts(registry, good):
    assert findings(registry, steps=[step(id=good)]) == []


def test_twenty_steps_are_allowed_twenty_one_are_not(registry):
    many = [step(id=f"s-{chr(97 + i)}") for i in range(21)]
    assert findings(registry, steps=many[:20]) == []
    assert any("at most 20 steps" in f for f in findings(registry, steps=many))


def test_call_and_approve_together(registry):
    assert any("both" in f for f in findings(registry, steps=[step(approve="ok")]))


def test_neither_call_nor_approve(registry):
    assert any("either" in f for f in findings(registry, steps=[{"id": "s1"}]))


def test_approve_step_with_input_is_refused(registry):
    assert any("input" in f for f in findings(registry, steps=[{"id": "s1", "approve": "ok", "input": {"a": 1}}]))


def test_approve_step_alone_is_fine(registry):
    assert findings(registry, steps=[{"id": "s1", "approve": "ok"}]) == []


# check_flow: call and input


@pytest.mark.parametrize("call", ["greet", "a.b.c", ".greet", "fake-plugin.", ""])
def test_call_shape(registry, call):
    assert any("<plugin>.<operation>" in f for f in findings(registry, steps=[step(call=call)]))


def test_unknown_plugin(registry):
    assert any("Unknown plugin 'nope'" in f for f in findings(registry, steps=[step(call="nope.greet")]))


def test_unknown_operation(registry):
    assert any("Unknown operation" in f for f in findings(registry, steps=[step(call="fake-plugin.nope")]))


def test_literal_input_is_validated(registry):
    result = findings(registry, steps=[step(input={"name": 5})])
    assert any("Input does not match" in f and "'s1'" in f for f in result)


def test_literal_input_missing_field(registry):
    assert any("Input does not match" in f for f in findings(registry, steps=[step(input={})]))


def test_input_with_reference_is_not_validated_before_running(registry):
    steps = [step(input={"name": 5, "times": "${trigger.payload.n}"})]
    assert findings(registry, steps=steps) == []


def test_input_with_reference_still_has_refs_checked(registry):
    steps = [step(input={"name": "${nope.x}"})]
    assert any("${nope.x}" in f for f in findings(registry, steps=steps))


# check_flow: references


def test_reference_to_trigger_is_fine(registry):
    assert findings(registry, steps=[step(input={"name": "${trigger.payload.x}"})]) == []


def test_reference_to_earlier_step_is_fine(registry):
    steps = [step(id="a"), step(id="b", input={"name": "${steps.a.output.message}"})]
    assert findings(registry, steps=steps) == []


def test_reference_to_later_step(registry):
    steps = [step(id="a", input={"name": "${steps.b.output.message}"}), step(id="b")]
    assert any("'b'" in f and "earlier" in f for f in findings(registry, steps=steps))


def test_reference_to_itself(registry):
    steps = [step(id="a", input={"name": "${steps.a.output.message}"})]
    assert any("earlier" in f for f in findings(registry, steps=steps))


def test_reference_to_unknown_step(registry):
    steps = [step(input={"name": "${steps.ghost.output.x}"})]
    assert any("ghost" in f for f in findings(registry, steps=steps))


@pytest.mark.parametrize("ref", ["${env.HOME}", "${other.x}", "${steps}", "${trigger.a + 1}", "${}"])
def test_unknown_root_or_bad_grammar(registry, ref):
    result = findings(registry, steps=[step(input={"name": ref})])
    assert any(ref in f for f in result)


def test_when_references_are_checked(registry):
    assert findings(registry, steps=[step(when="${trigger.payload.go}")]) == []
    assert any("earlier" in f for f in findings(registry, steps=[step(when="${steps.s1.output.x}")]))
    assert any("${bad}" in f for f in findings(registry, steps=[step(when="${bad}")]))


def test_reference_inside_nested_input_is_checked(registry):
    steps = [{"id": "w", "call": "fake-plugin.write", "input": {"names": ["a", "${steps.zz.output.x}"]}}]
    assert any("zz" in f for f in findings(registry, steps=steps))


# check_flow: tier ceiling


@pytest.mark.parametrize("tier", [0, 1])
def test_allowed_tiers(registry, tier):
    assert findings(registry, max_tier=tier) == []


@pytest.mark.parametrize("tier", [2, 3, 9, -1])
def test_max_tier_above_one_is_refused(registry, tier):
    assert any("max_tier" in f for f in findings(registry, max_tier=tier))


def test_step_above_the_ceiling_is_not_a_finding(registry):
    steps = [{"id": "w", "call": "fake-plugin.write", "input": {"names": ["a"]}}]
    assert findings(registry, max_tier=0, steps=steps) == []


# check_flow: event trigger


@pytest.mark.parametrize(
    "pattern",
    [
        "flows.>",
        "flows.run.completed",
        "flows.run.*",
        ">",
        "*.>",
        "*.*.completed",
        "*.*.failed",
        "flows.*",
    ],
)
def test_event_trigger_may_not_match_flows_topics(registry, pattern):
    assert any("flows." in f for f in findings(registry, trigger={"event": pattern}))


@pytest.mark.parametrize(
    "pattern",
    [
        "markitdown.convert.requested",
        "markitdown.*.requested",
        "markitdown.>",
        "*.*.*",
        "markitdown.convert.*",
        "a.requested",
        "*.requested",
        "x.y.>",
    ],
)
def test_event_trigger_may_not_match_requested_topics(registry, pattern):
    assert any("requested" in f for f in findings(registry, trigger={"event": pattern}))


@pytest.mark.parametrize(
    "pattern",
    [
        "markitdown.classify.completed",
        "markitdown.*.completed",
        "email.message.received",
        "markitdown.*.failed",
        "flowsx.run.completed",
        "requested",
        "flows",
    ],
)
def test_event_trigger_fine(registry, pattern):
    assert findings(registry, trigger={"event": pattern}) == []


def test_other_triggers_have_no_topic_rules(registry):
    assert findings(registry, trigger={"manual": True}) == []
    assert findings(registry, trigger={"schedule": {"daily": "06:30"}}) == []


def test_all_findings_are_reported_not_just_the_first(registry):
    flow = make(max_tier=3, steps=[step(), step(), step(id="Bad", call="nope.x")])
    assert len(check_flow(registry, flow)) >= 4
