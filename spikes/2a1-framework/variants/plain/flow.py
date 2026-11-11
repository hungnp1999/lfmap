"""The `plain` variant (task F1): standard library + pydantic, state in one JSON file per run.

Phases run batch by batch (spec section 2): Plan all, Work all, Review all, then one Work and Review
batch for the cards sent back. The approval pause saves the state and returns; `resume` runs in a new
process and only reads that file.
"""

import os
import re
from pathlib import Path

from pydantic import BaseModel

from common.gates import gate_summary, gate_verdict, model_attempt, read_in, replay_attempt, review_log
from common.models import (
    Attempt,
    AwaitingApproval,
    Card,
    ChatModel,
    Done,
    Models,
    Package,
    Report,
    RunRecord,
    RunResult,
    RunStatus,
    new_run_id,
)
from common.plan import complete_cards
from common.prompts import (
    PLAN_SCHEMA,
    PLAN_SYSTEM,
    REPORT_SCHEMA,
    STANDARD,
    WORK_SYSTEM,
    parse_cards,
    parse_report,
    plan_user,
    review_user,
    rework_feedback,
    work_user,
)
from common.quote import check_quotes

VARIANT = "plain"
GATE_ROUNDS = 2
REVIEW_ROUNDS = int(os.environ.get("LFMAP_REVIEW_ROUNDS", 2))  # 1: one Leading review per card, no rework batch


class State(BaseModel):
    """Everything a run needs to be resumed: saved as state.json in the run folder."""

    run_id: str
    package: Package
    cards: list[Card]
    bases: dict[str, str] = {}
    attempts: list[Attempt] = []
    reports: list[Report] = []
    verdicts: dict[str, str] = {}
    status: RunStatus = "awaiting_approval"

    def last_attempt(self, card_id: str) -> Attempt:
        return [a for a in self.attempts if a.card_id == card_id][-1]


def run_flow(package: Package, *, models: Models, state_dir: Path, replay_cards: list[Card] | None = None) -> RunResult:
    """Run Plan, Work and Review in batches, then pause for approval."""
    cards = replay_cards if replay_cards is not None else plan(package, models.leading)
    state = State(run_id=new_run_id(VARIANT, package.id), package=package, cards=cards)
    work_batch(state, cards, models.working, {})
    pending = cards
    for review_round in range(1, REVIEW_ROUNDS + 1):
        reports = review_batch(state, pending, models.leading)
        pending = [c for c in pending if reports[c.id].verdict == "rework"]
        if not pending or review_round == REVIEW_ROUNDS:
            break
        feedback = {c.id: _feedback(state, reports[c.id]) for c in pending}
        work_batch(state, pending, models.working, feedback)
    for card in pending:
        state.verdicts[card.id] = "escalate"
    return pause(state, Path(state_dir))


def plan(package: Package, leading: ChatModel) -> list[Card]:
    """Plan phase: one Leading call splits the package into cards; a card without frozen tests is refused."""
    cards = parse_cards(leading.chat(PLAN_SYSTEM, plan_user(package), PLAN_SCHEMA))
    if not cards:
        raise ValueError(f"the Plan phase produced no card for package {package.id}")
    return complete_cards(package, cards)


def _feedback(state: State, report: Report) -> str:
    """Rework feedback: in gates mode the failed gate log comes first, then the advisory findings."""
    gate_log = state.last_attempt(report.card_id).gate_log() if state.package.verdict_mode == "gates" else ""
    return rework_feedback(report, gate_log)


def work_batch(state: State, cards: list[Card], working: ChatModel, feedback: dict[str, str]) -> None:
    """Work phase for every card in order; a replay card's first round is its known diff."""
    for card in cards:
        state.bases.setdefault(card.id, read_in(state.package.workdir, card.target))
        if card.replay_diff is not None and card.id not in feedback:
            state.attempts.append(replay_attempt(state.package, card))
            continue
        note = feedback.get(card.id, "")
        for _ in range(GATE_ROUNDS):
            round_no = len([a for a in state.attempts if a.card_id == card.id]) + 1
            reply = working.chat(WORK_SYSTEM, work_user(card, note, state.package.contracts))
            attempt = model_attempt(state.package, card, round_no, reply, state.bases[card.id])
            state.attempts.append(attempt)
            if attempt.ok:
                break
            note = attempt.gate_log()


def review_batch(state: State, cards: list[Card], leading: ChatModel) -> dict[str, Report]:
    """Review phase: the last attempt of every card; quotes not in the diff are dropped.

    In gates mode the gates decide the verdict and the model's own verdict is kept as `model_verdict`.
    """
    reports: dict[str, Report] = {}
    system = state.package.standard or STANDARD
    for card in cards:
        attempt = state.last_attempt(card.id)
        if not attempt.diff:
            report = Report(card_id=card.id, verdict="escalate", notes="no code was produced")
        else:
            user = review_user(
                card, attempt.diff, review_log(card, attempt), state.package.contracts, gate_summary(attempt)
            )
            report = check_quotes(parse_report(card.id, leading.chat(system, user, REPORT_SCHEMA)), attempt.diff)
        if state.package.verdict_mode == "gates":
            report = report.model_copy(update={"model_verdict": report.verdict, "verdict": gate_verdict(attempt)})
        verdict = "escalate" if report.verdict == "invalid_json" else report.verdict
        state.reports.append(report)
        state.verdicts[card.id] = verdict
        reports[card.id] = report
    return reports


def _result(state: State, run_dir: Path) -> RunResult:
    counts = {c.id: len([a for a in state.attempts if a.card_id == c.id]) for c in state.cards}
    verdicts = {c.id: state.verdicts[c.id] for c in state.cards}
    return RunResult(
        run_id=state.run_id, variant=VARIANT, status=state.status, verdicts=verdicts, attempts=counts, run_dir=run_dir
    )


def _advice(state: State) -> dict[str, int]:
    """Kept findings of the last report of each card: what the human reviewer should read first."""
    last = {r.card_id: len(r.findings) for r in state.reports}
    return {c.id: last.get(c.id, 0) for c in state.cards}


def pause(state: State, state_dir: Path) -> RunResult:
    """Save state, reports and awaiting_approval.json; the caller's process may exit after this."""
    run_dir = state_dir / state.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    record = RunRecord(
        run_id=state.run_id,
        variant=VARIANT,
        package_id=state.package.id,
        cards=state.cards,
        attempts=state.attempts,
        reports=state.reports,
    )
    (run_dir / "reports.json").write_text(record.model_dump_json(indent=2), encoding="utf-8")
    (run_dir / "state.json").write_text(state.model_dump_json(indent=2), encoding="utf-8")
    result = _result(state, run_dir)
    awaiting = AwaitingApproval(
        run_id=state.run_id,
        variant=VARIANT,
        cards=[c.id for c in state.cards],
        verdicts=result.verdicts,
        advice=_advice(state),
        report_path=str(run_dir / "reports.json"),
    )
    (run_dir / "awaiting_approval.json").write_text(awaiting.model_dump_json(indent=2), encoding="utf-8")
    return result


def resume(run_id: str, *, approve: bool, state_dir: Path) -> RunResult:
    """Finish a paused run: load state.json, record the decision in done.json."""
    if not re.fullmatch(r"[\w.-]+", run_id):
        raise ValueError(f"not a run id: {run_id!r}")
    run_dir = Path(state_dir) / run_id
    state = State.model_validate_json((run_dir / "state.json").read_text(encoding="utf-8"))
    if state.status != "awaiting_approval":
        raise ValueError(f"run {run_id} is not awaiting approval (status {state.status})")
    state.status = "approved" if approve else "rejected"
    (run_dir / "state.json").write_text(state.model_dump_json(indent=2), encoding="utf-8")
    result = _result(state, run_dir)
    done = Done(run_id=run_id, variant=VARIANT, approved=approve, verdicts=result.verdicts)
    (run_dir / "done.json").write_text(done.model_dump_json(indent=2), encoding="utf-8")
    return result
