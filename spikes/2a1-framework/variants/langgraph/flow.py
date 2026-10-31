"""The `langgraph` variant (task F3): a LangGraph StateGraph with the SQLite checkpointer.

Phases run batch by batch (spec section 2): Plan all, Work all, Review all, then one Work and Review
batch for the cards sent back. The approval pause is a LangGraph `interrupt`; the graph state lives in
`<state_dir>/<run_id>/checkpoints.sqlite`, so `resume` in a new process continues the same graph.
"""

import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from pydantic import BaseModel

from common.gates import model_attempt, replay_attempt, review_log
from common.models import (
    Attempt,
    AwaitingApproval,
    Card,
    Done,
    Models,
    Package,
    Report,
    RunRecord,
    RunResult,
    RunStatus,
    new_run_id,
)
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

VARIANT = "langgraph"
GATE_ROUNDS = 2
REVIEW_ROUNDS = 2
CHECKPOINT_DB = "checkpoints.sqlite"


class State(BaseModel):
    """Run data kept in the graph state as one JSON-ready dict (checkpointed after every node)."""

    run_id: str
    package: Package
    cards: list[Card] = []
    attempts: list[Attempt] = []
    reports: list[Report] = []
    verdicts: dict[str, str] = {}
    status: RunStatus = "awaiting_approval"

    def last_attempt(self, card_id: str) -> Attempt:
        return [a for a in self.attempts if a.card_id == card_id][-1]


class GraphState(TypedDict):
    run: dict[str, Any]
    pending: list[str]
    feedback: dict[str, str]
    review_round: int


def _load(graph_state: GraphState) -> State:
    return State.model_validate(graph_state["run"])


def _dump(state: State) -> dict[str, Any]:
    return state.model_dump(mode="json")


def _result(state: State, run_dir: Path) -> RunResult:
    counts = {c.id: len([a for a in state.attempts if a.card_id == c.id]) for c in state.cards}
    verdicts = {c.id: state.verdicts[c.id] for c in state.cards}
    return RunResult(
        run_id=state.run_id, variant=VARIANT, status=state.status, verdicts=verdicts, attempts=counts, run_dir=run_dir
    )


def build_graph(models: Models | None, state_dir: Path, saver: SqliteSaver):
    """Compile the flow; `models` is None when only resuming (no model node runs after the pause)."""

    def plan(gs: GraphState) -> dict[str, Any]:
        state = _load(gs)
        if not state.cards:
            reply = models.leading.chat(PLAN_SYSTEM, plan_user(state.package), PLAN_SCHEMA)
            state.cards = parse_cards(reply)
        if not state.cards:
            raise ValueError(f"the Plan phase produced no card for package {state.package.id}")
        return {"run": _dump(state), "pending": [c.id for c in state.cards], "feedback": {}, "review_round": 0}

    def work(gs: GraphState) -> dict[str, Any]:
        state, working = _load(gs), models.working
        feedback = gs["feedback"]
        for card in [c for c in state.cards if c.id in gs["pending"]]:
            if card.replay_diff is not None and card.id not in feedback:
                state.attempts.append(replay_attempt(state.package, card))
                continue
            note = feedback.get(card.id, "")
            for _ in range(GATE_ROUNDS):
                round_no = len([a for a in state.attempts if a.card_id == card.id]) + 1
                attempt = model_attempt(state.package, card, round_no, working.chat(WORK_SYSTEM, work_user(card, note)))
                state.attempts.append(attempt)
                if attempt.ok:
                    break
                note = attempt.gate_log()
        return {"run": _dump(state)}

    def review(gs: GraphState) -> dict[str, Any]:
        state, leading = _load(gs), models.leading
        system = state.package.standard or STANDARD
        reports: dict[str, Report] = {}
        for card in [c for c in state.cards if c.id in gs["pending"]]:
            attempt = state.last_attempt(card.id)
            if not attempt.diff:
                report = Report(card_id=card.id, verdict="escalate", notes="no code was produced")
            else:
                reply = leading.chat(system, review_user(card, attempt.diff, review_log(card, attempt)), REPORT_SCHEMA)
                report = check_quotes(parse_report(card.id, reply), attempt.diff)
            state.reports.append(report)
            state.verdicts[card.id] = "escalate" if report.verdict == "invalid_json" else report.verdict
            reports[card.id] = report
        pending = [cid for cid in gs["pending"] if reports[cid].verdict == "rework"]
        feedback = {cid: rework_feedback(reports[cid]) for cid in pending}
        round_no = gs["review_round"] + 1
        if round_no == REVIEW_ROUNDS:
            for cid in pending:
                state.verdicts[cid] = "escalate"
        return {"run": _dump(state), "pending": pending, "feedback": feedback, "review_round": round_no}

    def after_review(gs: GraphState) -> str:
        return "work" if gs["pending"] and gs["review_round"] < REVIEW_ROUNDS else "pause"

    def pause(gs: GraphState) -> dict[str, Any]:
        state = _load(gs)
        run_dir = state_dir / state.run_id
        record = RunRecord(
            run_id=state.run_id,
            variant=VARIANT,
            package_id=state.package.id,
            cards=state.cards,
            attempts=state.attempts,
            reports=state.reports,
        )
        (run_dir / "reports.json").write_text(record.model_dump_json(indent=2), encoding="utf-8")
        awaiting = AwaitingApproval(
            run_id=state.run_id,
            variant=VARIANT,
            cards=[c.id for c in state.cards],
            verdicts=_result(state, run_dir).verdicts,
            report_path=str(run_dir / "reports.json"),
        )
        (run_dir / "awaiting_approval.json").write_text(awaiting.model_dump_json(indent=2), encoding="utf-8")
        return {}

    def approval(gs: GraphState) -> dict[str, Any]:
        approved = interrupt("awaiting_approval")
        state = _load(gs)
        state.status = "approved" if approved else "rejected"
        run_dir = state_dir / state.run_id
        done = Done(
            run_id=state.run_id, variant=VARIANT, approved=bool(approved), verdicts=_result(state, run_dir).verdicts
        )
        (run_dir / "done.json").write_text(done.model_dump_json(indent=2), encoding="utf-8")
        return {"run": _dump(state)}

    builder = StateGraph(GraphState)
    for name, node in (("plan", plan), ("work", work), ("review", review), ("pause", pause), ("approval", approval)):
        builder.add_node(name, node)
    builder.add_edge(START, "plan")
    builder.add_edge("plan", "work")
    builder.add_edge("work", "review")
    builder.add_conditional_edges("review", after_review, {"work": "work", "pause": "pause"})
    builder.add_edge("pause", "approval")
    builder.add_edge("approval", END)
    return builder.compile(checkpointer=saver)


@contextmanager
def _saver(run_dir: Path) -> Iterator[SqliteSaver]:
    conn = sqlite3.connect(run_dir / CHECKPOINT_DB, check_same_thread=False)
    try:
        yield SqliteSaver(conn)
    finally:
        conn.close()


def run_flow(package: Package, *, models: Models, state_dir: Path, replay_cards: list[Card] | None = None) -> RunResult:
    """Run Plan, Work and Review in batches, then pause for approval at the `interrupt`."""
    state_dir = Path(state_dir)
    state = State(run_id=new_run_id(VARIANT, package.id), package=package, cards=replay_cards or [])
    run_dir = state_dir / state.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    config = {"configurable": {"thread_id": state.run_id}}
    with _saver(run_dir) as saver:
        graph = build_graph(models, state_dir, saver)
        graph.invoke({"run": _dump(state), "pending": [], "feedback": {}, "review_round": 0}, config)
        return _result(_load(graph.get_state(config).values), run_dir)


def resume(run_id: str, *, approve: bool, state_dir: Path) -> RunResult:
    """Finish a paused run in a new process: reopen the checkpoint and answer the interrupt."""
    if not re.fullmatch(r"[\w.-]+", run_id):
        raise ValueError(f"not a run id: {run_id!r}")
    state_dir = Path(state_dir)
    run_dir = state_dir / run_id
    if not (run_dir / CHECKPOINT_DB).is_file():
        raise FileNotFoundError(f"no checkpoint for run {run_id}")
    config = {"configurable": {"thread_id": run_id}}
    with _saver(run_dir) as saver:
        graph = build_graph(None, state_dir, saver)
        if graph.get_state(config).next != ("approval",):
            raise ValueError(f"run {run_id} is not awaiting approval")
        graph.invoke(Command(resume=approve), config)
        return _result(_load(graph.get_state(config).values), run_dir)
