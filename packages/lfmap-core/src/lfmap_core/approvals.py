"""Approval queue for scheduled jobs (ADR-017, ADR-018): `%LOCALAPPDATA%\\lfmap\\approvals\\`.

A job never asks anyone. A call it may not run becomes a proposal in `pending\\`, which a person approves
or rejects with `lfmap approvals approve|reject` in an interactive terminal. Proposal files are only moved
between `pending`, `done`, `rejected` and `expired`, never deleted. A proposal file is untrusted input:
it is validated on every read, and its id must match `_ID` before it becomes part of a path.
"""

import os
import re
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError

from lfmap_core.approval import TIERS, DataLevel, Gate, Policy, Tier, audit, job_decision
from lfmap_core.config import app_dir
from lfmap_core.errors import ToolError
from lfmap_core.tool import Channel

if TYPE_CHECKING:
    from lfmap_core.jobs import Job

State = Literal["pending", "done", "rejected", "expired"]
STATES: tuple[State, ...] = ("pending", "done", "rejected", "expired")
DEFAULT_TTL_DAYS = 7
MAX_TTL_DAYS = 30
_ID = re.compile(r"\d{8}T\d{6}Z-[a-z][a-z0-9-]*-[0-9a-f]{8}")
_CALL = {"job", "plugin", "operation", "input", "tier", "reason", "detail"}


class Proposal(BaseModel):
    """A call a job was not allowed to run on its own. `preview` stays None until operations can declare dry runs."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=rf"^{_ID.pattern}$")
    created: AwareDatetime
    expires: AwareDatetime
    job: str = Field(pattern=r"^[a-z][a-z0-9-]*$")
    plugin: str
    operation: str
    input: dict[str, Any] = Field(default_factory=dict)
    tier: Tier
    reason: str
    detail: str = ""
    preview: str | None = None


def visible(text: str) -> str:
    """Escape control and format characters (ANSI escapes, bidi overrides) so a forged proposal cannot hide
    anything on the terminal where a person reads it before approving."""
    return "".join(f"\\u{ord(c):04x}" if unicodedata.category(c).startswith("C") else c for c in text)


def approvals_dir() -> Path:
    return app_dir() / "approvals"


def ttl(config: dict[str, Any]) -> timedelta:
    """`[jobs] approval_ttl_days` in config.toml: how long a proposal waits (default 7 days)."""
    section = config.get("jobs", {})
    days = section.get("approval_ttl_days", DEFAULT_TTL_DAYS) if isinstance(section, dict) else None
    if not isinstance(days, int) or isinstance(days, bool) or not 1 <= days <= MAX_TTL_DAYS:
        message = f"[jobs] approval_ttl_days must be a whole number from 1 to {MAX_TTL_DAYS}"
        raise ToolError("invalid_input", message, {"value": days})
    return timedelta(days=days)


def _path(state: State, approval_id: str) -> Path:
    if state not in STATES or not _ID.fullmatch(approval_id):
        raise ToolError("invalid_input", "Not a proposal id", {"id": approval_id})
    base = os.path.realpath(approvals_dir() / state)
    candidate = os.path.realpath(os.path.join(base, approval_id + ".json"))
    if not candidate.startswith(base + os.sep):
        raise ToolError("permission_denied", "Proposal path leaves the approvals folder", {"id": approval_id})
    return Path(candidate)


def _read(path: Path) -> Proposal:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise ToolError("not_found", "No pending proposal with this id (expired or already handled?)") from error
    try:
        proposal = Proposal.model_validate_json(text)
    except ValidationError as error:
        raise ToolError("invalid_input", f"{path} is not a valid proposal", {"error": str(error)}) from error
    if proposal.id != path.stem:
        raise ToolError("invalid_input", f"{path} holds another proposal id", {"id": proposal.id})
    return proposal


def _pending_files() -> list[Proposal]:
    """Valid pending proposals in id order. Invalid files are left where they are and can never be approved."""
    proposals = []
    for path in sorted((approvals_dir() / "pending").glob("*.json")):
        if not _ID.fullmatch(path.stem):
            continue
        try:
            proposals.append(_read(path))
        except ToolError:
            continue
    return proposals


def load(approval_id: str) -> Proposal:
    return _read(_path("pending", approval_id))


def move(approval_id: str, state: State) -> None:
    """Move a pending proposal to `state`. Atomic, so two callers can never both move the same proposal."""
    if state == "pending":
        raise ToolError("invalid_input", "A proposal can only leave pending")
    source = _path("pending", approval_id)
    target = _path(state, approval_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise ToolError("internal", f"{target} already exists", {"id": approval_id})
    try:
        os.replace(source, target)
    except FileNotFoundError as error:
        raise ToolError("not_found", "No pending proposal with this id (expired or already handled?)") from error


def sweep(now: datetime | None = None) -> list[str]:
    """Move expired pending proposals to `expired`; return their ids."""
    now = now or datetime.now(UTC)
    moved = []
    for proposal in _pending_files():
        if proposal.expires > now:
            continue
        try:
            move(proposal.id, "expired")
        except ToolError as error:
            if error.code != "not_found":
                raise
            continue
        moved.append(proposal.id)
    return moved


def pending(now: datetime | None = None) -> list[Proposal]:
    sweep(now)
    return _pending_files()


@dataclass(frozen=True)
class EventCall:
    """A call requested by an event; queued like a job named `events` (ADR-018, docs/specs/events.md section 6)."""

    plugin: str
    operation: str
    input: dict[str, Any]
    max_tier: int = 0
    id: str = "events"


def queue(
    job: "Job | EventCall", tier: Tier, reason: str, detail: str, lifetime: timedelta, now: datetime | None = None
) -> str:
    """Write a proposal for this call and return its id; an identical pending proposal is reused."""
    now = now or datetime.now(UTC)
    sweep(now)
    proposal = Proposal(
        id=f"{now.strftime('%Y%m%dT%H%M%SZ')}-{job.id}-{uuid.uuid4().hex[:8]}",
        created=now,
        expires=now + lifetime,
        job=job.id,
        plugin=job.plugin,
        operation=job.operation,
        input=job.input,
        tier=tier,
        reason=reason,
        detail=detail,
    )
    call = proposal.model_dump(mode="json", include=_CALL)
    for existing in _pending_files():
        if existing.model_dump(mode="json", include=_CALL) == call:
            return existing.id
    path = _path("pending", proposal.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(proposal.model_dump_json(indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return proposal.id


def _with_destination(reason: str, target: str, destination: str, data: DataLevel) -> tuple[str, str]:
    if not destination:
        return reason, target
    return f"{reason} to {destination} ({data})", target or destination


@dataclass
class JobApprover:
    """The approver of `lfmap jobs run` and of event calls (`channel="event"`). It never asks anyone (see
    `job_decision`): a call that needs a person is queued as a proposal and refused with `permission_denied`
    carrying its `approval_id`."""

    job: "Job | EventCall"
    policy: Policy
    lifetime: timedelta = timedelta(days=DEFAULT_TTL_DAYS)
    channel: Channel = "job"

    def __call__(
        self, tier: Tier, reason: str, target: str = "", destination: str = "", data: DataLevel = "normal"
    ) -> None:
        if tier == "T0":
            return
        plugin, op = self.job.plugin, self.job.operation
        key = f"{plugin}.{op}"
        reason, target = _with_destination(reason, target, destination, data)
        decision = job_decision(self.policy, plugin, op, tier, self.job.max_tier)
        record = {"channel": self.channel, "plugin": plugin, "operation": op, "tier": tier}
        record |= {"target": target} if target else {}
        if decision == "allow":
            audit({**record, "decision": "allow", "reason": reason})
            return
        if decision == "deny":
            audit({**record, "decision": "deny", "reason": reason})
            details = {"operation": key, "tier": tier, "reason": reason, "hint": "[approval] in config.toml denies it"}
            raise ToolError("permission_denied", f"{key} is denied ({tier}, {reason})", details)
        approval_id = queue(self.job, tier, reason, target, self.lifetime)
        audit({**record, "decision": "queue", "reason": f"{reason}; proposal {approval_id}"})
        details = {
            "approval_id": approval_id,
            "operation": key,
            "tier": tier,
            "reason": reason,
            "hint": f"run `lfmap approvals approve {approval_id}` in an interactive terminal",
        }
        raise ToolError("permission_denied", "Queued for approval", details)


@dataclass
class ApprovedGate:
    """The approver of `lfmap approvals approve`: the person approved one run of the proposal up to its tier.

    Calls at or below that tier run and are audited; anything higher, or denied by the policy, goes to
    `fallback`, a normal CLI gate that asks again or refuses.
    """

    proposal: Proposal
    fallback: Gate

    def __call__(
        self, tier: Tier, reason: str, target: str = "", destination: str = "", data: DataLevel = "normal"
    ) -> None:
        if tier == "T0":
            return
        p = self.proposal
        denied = self.fallback.policy.action(p.plugin, p.operation, tier) == "deny"
        if denied or TIERS.index(tier) > TIERS.index(p.tier):
            self.fallback(tier, reason, target, destination, data)
            return
        reason, target = _with_destination(reason, target, destination, data)
        record = {"channel": "cli", "plugin": p.plugin, "operation": p.operation, "tier": tier}
        record |= {"target": target} if target else {}
        audit({**record, "decision": "allow", "reason": f"{reason}; approved {p.id}"})
