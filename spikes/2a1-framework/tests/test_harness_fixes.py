"""Harness fixes of task F6: refused Plan cards, diffs against the base, gate-decided verdicts, contracts."""

from pathlib import Path

import pytest
from contract_fixture import BAD_CALC, CARDS, GOOD_CALC, REAL, make_package, replay_card

from common.cases import case_package, load_package
from common.fake import FakeModel, plan_reply, review_reply, work_reply
from common.models import Card, Models, RunRecord
from common.plan import complete_cards
from common.prompts import PLAN_SYSTEM, plan_user, review_user, work_user
from common.scoring import normalise
from variants.plain.flow import run_flow

SPIKE = Path(__file__).resolve().parent.parent
BAD_REPLAY = Card(**CARDS[0], replay_diff=None)


def _record(result) -> RunRecord:
    return RunRecord.model_validate_json((result.run_dir / "reports.json").read_text(encoding="utf-8"))


# --- 1. a Plan card without tests is refused -----------------------------------------------------------


def test_card_without_tests_is_refused(tmp_path: Path):
    package = make_package(tmp_path)
    with pytest.raises(ValueError, match="no frozen tests"):
        complete_cards(package, [Card(id="x", target="calc.py", prompt="p")])


def test_package_tests_fill_and_override_the_plan(tmp_path: Path):
    package = make_package(tmp_path).model_copy(update={"tests": {"calc.py": ["tests/test_calc.py"]}})
    wrong = Card(id="calc", target="calc.py", prompt="p", tests=["tests/test_greet.py"])
    [card] = complete_cards(package, [wrong])
    assert card.tests == ["tests/test_calc.py"] and card.scope == ["calc.py"]
    with pytest.raises(ValueError, match="not one of the package's modules"):
        complete_cards(package, [Card(id="g", target="greet.py", prompt="p", tests=["tests/test_greet.py"])])


def test_missing_test_file_is_refused(tmp_path: Path):
    package = make_package(tmp_path)
    with pytest.raises(ValueError, match="not found in the workdir"):
        complete_cards(package, [Card(id="c", target="calc.py", prompt="p", tests=["tests/test_nope.py"])])


def test_plan_run_refuses_cards_without_tests(tmp_path: Path):
    bare = [{"id": "calc", "target": "calc.py", "prompt": "Write add."}]
    models = Models(leading=FakeModel("leading").on("WORK PACKAGE", plan_reply(bare)), working=FakeModel("working"))
    with pytest.raises(ValueError, match="no frozen tests"):
        run_flow(make_package(tmp_path), models=models, state_dir=tmp_path / "s")
    assert models.working.calls == []


def test_plan_prompt_demands_tests_and_shows_contracts(tmp_path: Path):
    package = make_package(tmp_path).model_copy(update={"contracts": "details is always a dict"})
    assert "EVERY card lists" in PLAN_SYSTEM
    assert "CONTRACTS\ndetails is always a dict" in plan_user(package)


# --- 2. later rounds are reviewed against the base -----------------------------------------------------


def test_second_round_diff_is_against_the_base_not_the_previous_round(tmp_path: Path):
    leading = FakeModel("leading").on("CARD ID: calc", review_reply("rework", [REAL]), review_reply("ready"))
    working = FakeModel("working").on("CARD ID: calc", work_reply("calc.py", GOOD_CALC))
    result = run_flow(
        make_package(tmp_path),
        models=Models(leading=leading, working=working),
        state_dir=tmp_path / "s",
        replay_cards=[replay_card()],
    )
    first, second = _record(result).attempts
    assert second.round == 2 and second.diff == first.diff
    assert "--- /dev/null" in second.diff and "+def add" in second.diff
    assert "DIFF\ndiff --git" in leading.calls[1] and "+def add" in leading.calls[1]


# --- 3. the gates decide ready, the model advises ------------------------------------------------------


def _gates_package(tmp_path: Path):
    return make_package(tmp_path).model_copy(update={"verdict_mode": "gates"})


def test_red_gate_is_never_ready_even_if_the_model_says_ready(tmp_path: Path):
    leading = FakeModel("leading").on("CARD ID: calc", review_reply("ready"))
    working = FakeModel("working").on("CARD ID: calc", work_reply("calc.py", BAD_CALC))
    plan = plan_reply(CARDS[:1])
    leading.on("WORK PACKAGE", plan)
    result = run_flow(_gates_package(tmp_path), models=Models(leading, working), state_dir=tmp_path / "s")
    assert result.verdicts == {"calc": "escalate"}
    reports = _record(result).reports
    assert [r.verdict for r in reports] == ["rework", "rework"]
    assert [r.model_verdict for r in reports] == ["ready", "ready"]
    assert any("Failed gates:\n[pytest]" in call for call in working.calls)
    assert "pytest: FAILED" in leading.calls[1]


def test_green_gates_make_ready_and_findings_stay_advice(tmp_path: Path):
    leading = FakeModel("leading").on("CARD ID: calc", review_reply("rework", [REAL]))
    result = run_flow(
        _gates_package(tmp_path),
        models=Models(leading, FakeModel("working")),
        state_dir=tmp_path / "s",
        replay_cards=[replay_card()],
    )
    assert result.verdicts == {"calc": "ready"} and result.attempts == {"calc": 1}
    report = _record(result).reports[0]
    assert report.verdict == "ready" and report.model_verdict == "rework" and len(report.findings) == 1
    awaiting = (result.run_dir / "awaiting_approval.json").read_text(encoding="utf-8")
    assert '"advice"' in awaiting and '"calc": 1' in awaiting


def test_model_mode_keeps_the_f4_behaviour(tmp_path: Path):
    leading = FakeModel("leading").on("CARD ID: calc", review_reply("rework", [REAL]), review_reply("ready"))
    working = FakeModel("working").on("CARD ID: calc", work_reply("calc.py", GOOD_CALC))
    result = run_flow(
        make_package(tmp_path), models=Models(leading, working), state_dir=tmp_path / "s", replay_cards=[replay_card()]
    )
    assert result.verdicts == {"calc": "ready"} and result.attempts == {"calc": 2}
    assert _record(result).reports[0].model_verdict == ""


# --- 4. contracts ---------------------------------------------------------------------------------------


def test_contracts_reach_work_and_review(tmp_path: Path):
    card = replay_card()
    assert "CONTRACTS" in work_user(card, "", "details is a dict")
    assert "CONTRACTS" not in work_user(card)
    text = review_user(card, "diff", "", "details is a dict", "pytest: passed")
    assert text.index("CONTRACTS") < text.index("DIFF") < text.index("GATES")


def test_cases_and_package_load_the_real_contracts():
    package = load_package(SPIKE / "cases" / "packages" / "K4-K7")
    assert "details` is always a dict" in package.contracts
    assert len(package.tests) == 4 and all(v[0].endswith(".py") for v in package.tests.values())
    assert "details` is always a dict" in case_package(SPIKE / "cases" / "K4-clean").contracts


# --- 5. normalise ---------------------------------------------------------------------------------------


def test_normalise_has_no_negative_zero():
    scores = normalise({"S1": {"a": 135, "b": 162}}, {"S1": "fewer"})["S1"]
    assert str(scores["b"]) == "0.0" and scores["a"] == 10.0
