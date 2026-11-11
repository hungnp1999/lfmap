"""Declared flows: `%LOCALAPPDATA%\\lfmap\\flows.toml` and the static checks (docs/specs/flows.md sections 3 and 4).

Loading only needs the file to have the right shape. Every other rule lives in `check_flow`, so
`lfmap flows check` reports all findings of all flows at once; running a flow (FL-2) must call it first.
"""

import json
import os
import re
import tomllib
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from lfmap_core.config import app_dir
from lfmap_core.errors import ToolError
from lfmap_core.events import validate_pattern
from lfmap_core.flows_refs import find_refs
from lfmap_core.jobs import Schedule, check_input
from lfmap_core.registry import Registry

MAX_STEPS = 20
MAX_TIER = 1
_ID = r"^[a-z][a-z0-9-]*$"
_CALL = re.compile(r"^([^.\s]+)\.([^.\s]+)$")


class Trigger(BaseModel):
    """Exactly one of `manual = true`, `schedule = {...}` (the jobs `Schedule`) or `event = "<topic pattern>"`."""

    model_config = ConfigDict(extra="forbid")

    manual: Literal[True] | None = None
    schedule: Schedule | None = None
    event: str | None = None

    @field_validator("event")
    @classmethod
    def _pattern(cls, value: str | None) -> str | None:
        if value is None:
            return value
        try:
            return validate_pattern(value)
        except ToolError as error:
            raise ValueError(error.message) from error

    @model_validator(mode="after")
    def _one_kind(self) -> "Trigger":
        if sum(v is not None for v in (self.manual, self.schedule, self.event)) != 1:
            raise ValueError("trigger needs exactly one of manual, schedule, event")
        return self

    def describe(self) -> str:
        if self.schedule:
            return f"schedule {self.schedule.describe()}"
        return f"event {self.event}" if self.event else "manual"


class Step(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    call: str | None = None
    approve: str | None = None
    input: dict[str, Any] = Field(default_factory=dict)
    when: str | None = None
    via: Literal["call", "event"] = "call"  # "event": core publishes `<plugin>.<operation>.requested` (jobs only)


class Flow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=_ID)
    trigger: Trigger
    steps: list[Step]
    max_tier: int = 0
    enabled: bool = True


class FlowsFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    flows: list[Flow] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_ids(self) -> "FlowsFile":
        ids = [flow.id for flow in self.flows]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"duplicate flow ids: {', '.join(duplicates)}")
        return self


def flows_path() -> Path:
    override = os.environ.get("LFMAP_FLOWS")
    return Path(override) if override else app_dir() / "flows.toml"


def load_flows_file(path: Path | None = None) -> FlowsFile:
    path = path or flows_path()
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return FlowsFile()
    return parse_flows(text, path)


def parse_flows(text: str, path: Path) -> FlowsFile:
    """The shape of `flows.toml` text read from `path` (named in errors); a run hashes and parses the same bytes."""
    try:
        return FlowsFile.model_validate(tomllib.loads(text))
    except tomllib.TOMLDecodeError as error:
        raise ToolError("invalid_input", f"{path} is not valid TOML", {"error": str(error)}) from error
    except ValidationError as error:
        raise ToolError("invalid_input", f"{path} is invalid", {"error": str(error)}) from error


def load_flows(path: Path | None = None) -> list[Flow]:
    return load_flows_file(path).flows


def last_run_status(flow_id: str) -> str | None:
    """`status` of the newest run file of `flow_id` in `app_dir()/flows/runs/` (`flow` and `status` keys), else None."""
    runs = app_dir() / "flows" / "runs"
    if not runs.is_dir():
        return None
    for path in sorted(runs.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):  # noqa: S112 - an unreadable run file is skipped
            continue
        if isinstance(record, dict) and record.get("flow") == flow_id and isinstance(record.get("status"), str):
            return record["status"]
    return None


def may_match(pattern: str, probe: str) -> bool:
    """Whether some topic starting with (`probe` is `"flows."`) or ending with (`".requested"`) that part can match."""
    tokens = pattern.split(".")
    open_end = tokens[-1] == ">"
    if not open_end and len(tokens) < 2:
        return False  # a single token cannot be a topic of two or more tokens
    if probe == "flows.":
        return tokens[0] in ("flows", "*", ">")
    return tokens[-1] in ("requested", "*", ">")


def _step_findings(registry: Registry, step: Step, before: set[str]) -> list[str]:
    where = f"step {step.id!r}: "
    found: list[str] = []
    if step.call is not None and step.approve is not None:
        found.append(where + "has both call and approve")
    elif step.call is None and step.approve is None:
        found.append(where + "needs either call or approve")
    if step.approve is not None and step.input:
        found.append(where + "an approve step takes no input")
    if step.call is not None:
        found += [where + text for text in _call_findings(registry, step)]
    try:
        paths = find_refs(step.input) + find_refs(step.when)
    except ToolError as error:
        return [*found, where + error.message]
    for path in paths:
        if path[0] == "steps" and path[1] not in before:
            found.append(where + f"reference to step {path[1]!r}, which does not run earlier")
    return found


def _call_findings(registry: Registry, step: Step) -> list[str]:
    match = _CALL.match(step.call or "")
    if match is None:
        return [f"call {step.call!r} must look like <plugin>.<operation>"]
    plugin, operation = match.groups()
    try:
        entry = registry.get(plugin)
        if entry.manifest.operation(operation) is None:
            return [f"Unknown operation {plugin}.{operation}"]
        if step.via == "event" and not entry.manifest.adapters.events:
            return [f'via = "event" but plugin {plugin} has [adapters] events = false']
        if not find_refs(step.input):  # inputs with references are checked again after resolving
            check_input(entry, operation, step.input)
    except ToolError as error:
        return [error.message]
    return []


def check_flow(registry: Registry, flow: Flow) -> list[str]:
    """Every rule of spec section 3 not already enforced by loading; an empty list means the flow is sound."""
    found: list[str] = []
    if not 0 <= flow.max_tier <= MAX_TIER:
        found.append(f"max_tier {flow.max_tier} is not allowed; use 0 or 1 (T2 and T3 steps always need a person)")
    if flow.trigger.event is not None:
        if may_match(flow.trigger.event, "flows."):
            found.append(f"event {flow.trigger.event!r} could match a flows.* topic; no flow starts another flow")
        if may_match(flow.trigger.event, ".requested"):
            found.append(f"event {flow.trigger.event!r} could match a .requested topic")
    if len(flow.steps) > MAX_STEPS:
        found.append(f"flow has {len(flow.steps)} steps; at most {MAX_STEPS} steps are allowed")
    seen: set[str] = set()
    for step in flow.steps:
        if not re.fullmatch(_ID, step.id, re.ASCII):
            found.append(f"step id {step.id!r} must match [a-z][a-z0-9-]*")
        if step.id in seen:
            found.append(f"duplicate step id {step.id!r}")
        found += _step_findings(registry, step, seen)
        seen.add(step.id)
    return [f"{flow.id}: {text}" for text in found]
