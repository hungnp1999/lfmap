"""Risk-tiered approval (ADR-009, ADR-017) and the audit log.

Tiers: T0 no side effects (writes to the plugin's own data_dir/temp_dir count as none, ADR-016),
T1 creates new files in a declared write root, T2 overwrites, renames or deletes, T3 sends data out,
calls paid APIs, touches secrets or runs external commands. Tiers only change whether a person is
asked; permission roots never widen.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from lfmap_core import grants
from lfmap_core.config import app_dir
from lfmap_core.errors import ToolError
from lfmap_core.manifest import SideEffects
from lfmap_core.tool import Channel

Tier = Literal["T0", "T1", "T2", "T3"]
Action = Literal["allow", "audit", "ask", "deny"]
Decision = Literal["allow", "ask", "deny"]
JobDecision = Literal["allow", "queue", "deny"]
DataLevel = Literal["normal", "private", "secret"]

TIERS: tuple[Tier, ...] = ("T0", "T1", "T2", "T3")
DATA_LEVELS: tuple[DataLevel, ...] = ("normal", "private", "secret")
MAX_DESTINATION_DAYS = 90
AUDIT_FIELDS = frozenset({"time", "channel", "plugin", "operation", "tier", "decision", "reason", "target"})


def base_tier(side_effects: SideEffects) -> Tier:
    return {"none": "T0", "local_write": "T1", "external": "T3"}[side_effects]


def raise_tier(tier: Tier, floor: Tier) -> Tier:
    return max(tier, floor, key=TIERS.index)


class Destination(BaseModel):
    """A preapproved T3 destination: the highest data level it may receive and the day it expires."""

    model_config = ConfigDict(extra="forbid")

    data: Literal["normal", "private"] = "normal"
    expires: date


class Policy(BaseModel):
    """`[approval]` in config.toml. T3 can never be set below "ask": it needs a person, a grant or a
    preapproved destination (`[approval.destinations."host"]`, at most 90 days, never secret data)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    t1: Action = Field("audit", alias="T1")
    t2: Action = Field("ask", alias="T2")
    t3: Action = Field("ask", alias="T3")
    operations: dict[str, Action] = Field(default_factory=dict)
    destinations: dict[str, Destination] = Field(default_factory=dict)

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "Policy":
        try:
            policy = cls.model_validate(config.get("approval", {}))
        except ValidationError as error:
            raise ToolError("invalid_input", "[approval] in config.toml is invalid", {"error": str(error)}) from error
        limit = date.today() + timedelta(days=MAX_DESTINATION_DAYS)
        for host, destination in policy.destinations.items():
            if destination.expires > limit:
                raise ToolError(
                    "invalid_input",
                    f"[approval.destinations] {host} expires more than {MAX_DESTINATION_DAYS} days from today",
                    {"destination": host, "expires": str(destination.expires)},
                )
        return policy

    def destination_allows(self, host: str, data: DataLevel, today: date | None = None) -> bool:
        """True when `host` is preapproved, not expired, and may receive `data`. Secret data never leaves."""
        entry = {name.lower(): d for name, d in self.destinations.items()}.get(host.lower())
        if entry is None or data == "secret" or entry.expires < (today or date.today()):
            return False
        return DATA_LEVELS.index(data) <= DATA_LEVELS.index(entry.data)

    def action(self, plugin: str, op: str, tier: Tier) -> Action:
        if tier == "T0":
            return "allow"
        action = self.operations.get(f"{plugin}.{op}", getattr(self, tier.lower()))
        if tier == "T3" and action in ("allow", "audit"):
            return "ask"
        return action


def decide(
    policy: Policy,
    plugin: str,
    op: str,
    tier: Tier,
    channel: Channel,
    preapproved: set[str],
    can_elicit: bool,
    *,
    granted: bool = False,
) -> Decision:
    """Whether a call may run, must ask a person first, or is refused.

    `preapproved` holds `plugin.op` names the user approved up front (`serve mcp --approve`, CLI `--yes`);
    `can_elicit` says the adapter can ask the person (interactive terminal, MCP elicitation);
    `granted` says a time-limited grant from the interactive CLI covers this call.
    Neither a pre-approval nor MCP elicitation covers T3: an agent could answer for the person.
    A scheduled job has nobody to ask and takes no grant or pre-approval (it uses `job_decision`).
    """
    action = policy.action(plugin, op, tier)
    if action == "deny":
        return "deny"
    if action in ("allow", "audit"):
        return "allow"
    if channel == "job":
        return "deny"
    if granted:
        return "allow"
    if tier == "T3":
        return "ask" if channel == "cli" and can_elicit else "deny"
    if f"{plugin}.{op}" in preapproved:
        return "allow"
    return "ask" if can_elicit else "deny"


def job_decision(policy: Policy, plugin: str, op: str, tier: Tier, max_tier: int) -> JobDecision:
    """Whether a scheduled job runs a call, queues it for a person to approve, or is refused (ADR-018).

    Nobody watches a job, so it never asks and ignores grants, pre-approvals and preapproved destinations.
    `max_tier` (0 or 1, from jobs.toml) is a ceiling: the policy can only tighten it, and `deny` is never queued.
    """
    if tier == "T0":
        return "allow"
    action = policy.action(plugin, op, tier)
    if action == "deny":
        return "deny"
    if tier == "T1" and max_tier >= 1 and action in ("allow", "audit"):
        return "allow"
    return "queue"


def audit_path() -> Path:
    return app_dir() / "audit.jsonl"


def audit(record: dict[str, Any], path: Path | None = None) -> None:
    """Append one JSON line. Only known fields are accepted, so document content never lands here."""
    unknown = set(record) - AUDIT_FIELDS
    if unknown:
        raise ValueError(f"unknown audit fields: {sorted(unknown)}")
    line = {"time": datetime.now(UTC).isoformat(timespec="seconds"), **record}
    path = path or audit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as file:
        file.write(json.dumps(line, ensure_ascii=False) + "\n")


Asker = Callable[[str], bool]


def _hint(key: str, tier: Tier, channel: Channel) -> str:
    grant = f"run `lfmap approvals grant {key} --tier {tier} --for 1h` in an interactive terminal"
    if tier == "T3":
        grant += ", or add the destination to [approval.destinations] in config.toml"
        return grant if channel != "cli" else f"run the command in an interactive terminal, or {grant}"
    if channel == "cli":
        return "pass --yes or run the command in an interactive terminal"
    if channel == "mcp":
        return f"start the server with --approve {key}, use a client that supports elicitation, or {grant}"
    return grant


@dataclass
class Gate:
    """The approver an adapter attaches to `ToolContext.approver` for one call.

    `ask` puts a yes/no question to the person (terminal prompt, MCP elicitation); None when nobody can answer.
    """

    plugin: str
    operation: str
    channel: Channel
    policy: Policy
    preapproved: frozenset[str] = frozenset()
    ask: Asker | None = None

    def __call__(
        self, tier: Tier, reason: str, target: str = "", destination: str = "", data: DataLevel = "normal"
    ) -> None:
        if tier == "T0":
            return
        key = f"{self.plugin}.{self.operation}"
        preapproved_destination = (
            tier == "T3" and bool(destination) and self.policy.destination_allows(destination, data)
        )
        if destination:
            reason, target = f"{reason} to {destination} ({data})", target or destination
        granted = preapproved_destination or grants.active(key, tier)
        decision = decide(
            self.policy,
            self.plugin,
            self.operation,
            tier,
            self.channel,
            set(self.preapproved),
            self.ask is not None,
            granted=granted,
        )
        if decision == "ask":
            question = f"Allow {key} ({tier}, {reason})" + (f" on {target}" if target else "") + "?"
            decision = "allow" if self.ask and self.ask(question) else "deny"
        if decision == "deny" or self.policy.action(self.plugin, self.operation, tier) != "allow":
            record = {"channel": self.channel, "plugin": self.plugin, "operation": self.operation, "tier": tier}
            audit({**record, "decision": decision, "reason": reason, **({"target": target} if target else {})})
        if decision == "deny":
            details = {"operation": key, "tier": tier, "reason": reason, "hint": _hint(key, tier, self.channel)}
            raise ToolError("permission_denied", f"{key} needs approval ({tier}, {reason})", details)
