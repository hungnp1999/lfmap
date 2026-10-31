"""Data models of the spike flow and the variant contract types (handoff "Hợp đồng biến thể")."""

import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, Field

Verdict = Literal["ready", "rework", "escalate"]
RunStatus = Literal["awaiting_approval", "approved", "rejected"]

DEFAULT_PYTEST = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]
DEFAULT_RUFF = [sys.executable, "-m", "ruff"]


class Card(BaseModel):
    """One task card: the Working model writes `target`; `tests` are frozen; only `scope` may change."""

    id: str
    title: str = ""
    target: str
    scope: list[str] = Field(default_factory=list)
    tests: list[str] = Field(default_factory=list)
    prompt: str
    replay_diff: str | None = None
    replay_log: str | None = None

    def allowed(self) -> set[str]:
        """Files this card may change: its scope, or only its target when no scope is given."""
        return set(self.scope) or {self.target}


class Package(BaseModel):
    """A work package: goal and standard for the Plan and Review phases, a workdir for the gates."""

    id: str
    goal: str = ""
    standard: str = ""
    workdir: Path | None = None
    pytest_cmd: list[str] = Field(default_factory=lambda: list(DEFAULT_PYTEST))
    ruff_cmd: list[str] = Field(default_factory=lambda: list(DEFAULT_RUFF))


class GateResult(BaseModel):
    """Outcome of one deterministic gate."""

    name: str
    ok: bool
    output: str = ""


class Attempt(BaseModel):
    """One Work round of a card: where the code came from, its diff and the gate results."""

    card_id: str
    round: int
    source: Literal["replay", "model"]
    diff: str
    gates: list[GateResult] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True when every gate passed (or no gate ran)."""
        return all(g.ok for g in self.gates)

    def gate_log(self) -> str:
        """Output of the failed gates, fed back to the Working model and shown to the reviewer."""
        return "\n\n".join(f"[{g.name}]\n{g.output}" for g in self.gates if not g.ok)


class Finding(BaseModel):
    """One review finding; `quote` must be a line copied from the diff."""

    check: str
    file: str = ""
    quote: str
    problem: str


class Report(BaseModel):
    """Leading review of one attempt; `dropped` holds findings whose quote is not in the diff."""

    card_id: str
    verdict: Verdict | Literal["invalid_json"]
    findings: list[Finding] = Field(default_factory=list)
    dropped: list[Finding] = Field(default_factory=list)
    notes: str = ""


class RunRecord(BaseModel):
    """Content of `reports.json`: every card, attempt and report of a run (read by score.py)."""

    run_id: str
    variant: str
    package_id: str
    cards: list[Card]
    attempts: list[Attempt]
    reports: list[Report]


class AwaitingApproval(BaseModel):
    """Content of `awaiting_approval.json`, written when a run pauses (spec section 2, step 4)."""

    run_id: str
    variant: str
    cards: list[str]
    verdicts: dict[str, str]
    report_path: str


class Done(BaseModel):
    """Content of `done.json`, written by `resume`."""

    run_id: str
    variant: str
    approved: bool
    verdicts: dict[str, str]


class RunResult(BaseModel):
    """What `run_flow` and `resume` return."""

    run_id: str
    variant: str
    status: RunStatus
    verdicts: dict[str, str]
    attempts: dict[str, int]
    run_dir: Path


class ChatModel(Protocol):
    """A chat model: one system and one user message in, the reply text out (JSON when a schema is given)."""

    name: str

    def chat(self, system: str, user: str, schema: dict | None = None) -> str: ...


@dataclass
class Models:
    """The two models of the flow (handoff D4): Leading plans and reviews, Working writes code."""

    leading: ChatModel
    working: ChatModel


def new_run_id(variant: str, package_id: str) -> str:
    """Unique run id naming the variant and the package."""
    return f"{variant}-{package_id}-{uuid.uuid4().hex[:8]}"
