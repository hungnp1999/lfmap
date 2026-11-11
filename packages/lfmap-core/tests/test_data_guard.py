"""DC-2: the class guard in the approval gate (ADR-025, docs/specs/data-classes.md sections 5, 6, 11)."""

import json
import os
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from lfmap_core import Tool, ToolError, operation
from lfmap_core import data_guard as guard_module
from lfmap_core.approval import Gate, Policy, audit_path
from lfmap_core.approvals import EventCall, JobApprover, pending
from lfmap_core.manifest import parse_manifest
from lfmap_core.registry import PluginEntry
from lfmap_core.runtime import build_tool, context_for
from lfmap_core.tool import invoke

RECEIVED: list[str] = []


class TouchInput(BaseModel):
    read: list[str] = []
    write: list[str] = []
    overwrite: list[str] | None = None
    declare: bool = True
    external: list[str] | None = None
    callee_read: list[str] = []


class TouchOutput(BaseModel):
    label: str | None = None
    callee_shares_guard: bool = False


class GuardTool(Tool):
    @operation("touch")
    def touch(self, inp: TouchInput) -> TouchOutput:
        """Read, create and overwrite paths as told."""
        for path in inp.read:
            RECEIVED.append(str(self.ctx.permissions.require_read(path)))
        for path in inp.write:
            RECEIVED.append(str(self.ctx.permissions.require_write(path)))
        if inp.overwrite is not None:
            if inp.declare:
                self.ctx.require_approval("overwrite", detail="out", paths=inp.overwrite)
            else:
                self.ctx.require_approval("overwrite", detail="out")
        if inp.external is not None:
            self.ctx.require_approval("external", detail="api", paths=inp.external)
        shares = False
        if inp.callee_read:
            callee = context_for("guard-plugin", self.ctx, config={})
            shares = callee.data_guard is self.ctx.data_guard
            for path in inp.callee_read:
                callee.permissions.require_read(path)
        return TouchOutput(label=self.ctx.data_label, callee_shares_guard=shares)


MANIFEST = """
[plugin]
id = "guard-plugin"
name = "Guard"
version = "0.1.0"
description = "Test plugin for the class guard."
license = "Apache-2.0"
[plugin.entrypoint]
module = "tests"
class = "GuardTool"
[permissions]
fs_read = ["${root}"]
fs_write = ["${root}"]
[[operations]]
name = "touch"
input = "x:TouchInput"
output = "x:TouchOutput"
side_effects = "local_write"
"""

ENTRY = PluginEntry("guard-plugin", GuardTool, parse_manifest(MANIFEST))


@pytest.fixture
def work(tmp_path: Path) -> Path:
    base = tmp_path / "work"
    for name in ("scratch", "normal", "secret", "other"):
        (base / name).mkdir(parents=True)
        (base / name / "a.txt").write_text("a", encoding="utf-8")
        (base / name / "b.txt").write_text("b", encoding="utf-8")
    RECEIVED.clear()
    return base


def config(work: Path, **classes: str) -> dict[str, Any]:
    table = {str(work / name.replace("__", os.sep)): cls for name, cls in classes.items()}
    return {"paths": {"root": str(work)}, "data": {"classes": table}} if table else {"paths": {"root": str(work)}}


def run(work: Path, cfg: dict[str, Any], approver: Any, **payload: Any) -> TouchOutput:
    tool = build_tool(ENTRY, channel=getattr(approver, "channel", "cli"), approver=approver, config=cfg)
    return invoke(tool, "touch", payload)


def gate(channel: str = "cli", ask: Any = None, **policy: str) -> Gate:
    return Gate("guard-plugin", "touch", channel, Policy.model_validate(policy), ask=ask)


def lines() -> list[dict[str, Any]]:
    if not audit_path().exists():
        return []
    records = [json.loads(line) for line in audit_path().read_text(encoding="utf-8").splitlines()]
    return [{k: v for k, v in r.items() if k != "time"} for r in records]


def raw_lines() -> list[str]:
    return [line.split(", ", 1)[1] for line in audit_path().read_text(encoding="utf-8").splitlines()]


class Recorder:
    channel = "cli"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def __call__(self, tier: str, reason: str, target: str = "", **kwargs: Any) -> None:
        self.calls.append((tier, reason, kwargs))


def real(path: Path) -> str:
    return os.path.realpath(path)


def test_no_table_no_change(work):
    tool = build_tool(ENTRY, channel="cli", approver=gate(ask=lambda q: True), config=config(work))
    assert tool.ctx.data_guard is None
    assert tool.ctx.permissions.on_path is None
    assert tool.ctx.data_label is None
    common = {"read": [str(work / "secret" / "a.txt")], "write": [str(work / "scratch" / "x.txt")]}
    invoke(tool, "touch", {**common, "overwrite": [str(work / "scratch")]})
    run(work, config(work), gate(ask=lambda q: True), **common, overwrite=[], declare=False)
    expected = {
        "principal": "owner",
        "channel": "cli",
        "plugin": "guard-plugin",
        "operation": "touch",
        "tier": "T2",
        "decision": "allow",
        "reason": "overwrite",
        "target": "out",
    }
    assert [list(r.items()) for r in lines()] == [list(expected.items())] * 2
    first, second = raw_lines()
    assert first == second


@pytest.mark.parametrize("policy", [{}, {"T1": "allow"}])
def test_secret_read_audited_once(work, policy):
    out = run(
        work,
        config(work, secret="secret"),
        gate(**policy),
        read=[str(work / "secret" / "a.txt"), str(work / "secret" / "b.txt")],
    )
    assert out.label == "secret"
    assert lines() == [
        {
            "principal": "owner",
            "channel": "cli",
            "plugin": "guard-plugin",
            "operation": "touch",
            "tier": "T1",
            "action_tier": "T0",
            "data_class": "secret",
            "decision": "allow",
            "reason": "secret_read",
            "target": real(work / "secret" / "a.txt"),
        }
    ]


def test_secret_write_asks(work):
    target = str(work / "secret" / "new.txt")
    cfg = config(work, secret="secret")
    questions: list[str] = []
    run(work, cfg, gate(ask=lambda q: questions.append(q) or True), write=[target])
    assert len(questions) == 1 and "T2" in questions[0] and "secret_write" in questions[0]
    assert RECEIVED == [real(work / "secret" / "new.txt")]
    assert lines() == [
        {
            "principal": "owner",
            "channel": "cli",
            "plugin": "guard-plugin",
            "operation": "touch",
            "tier": "T2",
            "action_tier": "T1",
            "data_class": "secret",
            "decision": "allow",
            "reason": "secret_write",
            "target": real(work / "secret" / "new.txt"),
        }
    ]

    RECEIVED.clear()
    with pytest.raises(ToolError) as refused:
        run(work, cfg, gate(ask=lambda q: False), write=[target])
    assert refused.value.code == "permission_denied"
    with pytest.raises(ToolError) as on_mcp:
        run(work, cfg, gate(channel="mcp"), write=[target])
    assert on_mcp.value.code == "permission_denied"
    job = JobApprover(EventCall("guard-plugin", "touch", {"write": [target]}, max_tier=1), Policy(), channel="job")
    with pytest.raises(ToolError) as queued:
        run(work, cfg, job, write=[target])
    assert queued.value.code == "permission_denied"
    assert [(p.tier, p.reason) for p in pending()] == [("T2", "secret_write")]
    assert queued.value.details["approval_id"] == pending()[0].id
    assert RECEIVED == []
    assert [(r["channel"], r["tier"], r["decision"]) for r in lines()[1:]] == [
        ("cli", "T2", "deny"),
        ("mcp", "T2", "deny"),
        ("job", "T2", "queue"),
    ]


def test_scratch_overwrite_is_t1(work):
    out_dir = str(work / "scratch")
    run(work, config(work, scratch="scratch"), gate(), write=[out_dir], overwrite=[out_dir])
    assert lines() == [
        {
            "principal": "owner",
            "channel": "cli",
            "plugin": "guard-plugin",
            "operation": "touch",
            "tier": "T1",
            "action_tier": "T2",
            "data_class": "scratch",
            "decision": "allow",
            "reason": "overwrite",
            "target": "out",
        }
    ]


def test_scratch_not_lowered_when_mixed(work):
    mixed = config(work, scratch="scratch", normal="normal")
    with pytest.raises(ToolError) as written_normal:
        run(work, mixed, gate(), write=[str(work / "normal" / "x.txt")], overwrite=[str(work / "scratch")])
    assert written_normal.value.code == "permission_denied"
    nested = config(work, scratch="scratch", scratch__keep="normal")
    with pytest.raises(ToolError) as nested_normal:
        run(work, nested, gate(), overwrite=[str(work / "scratch")])
    assert nested_normal.value.code == "permission_denied"
    assert [(r["tier"], r["action_tier"], r["data_class"], r["decision"]) for r in lines()] == [
        ("T2", "T2", "normal", "deny"),
        ("T2", "T2", "normal", "deny"),
    ]


def test_overwrite_without_paths_unchanged(work):
    run(work, config(work, scratch="scratch"), gate(ask=lambda q: True), overwrite=[], declare=False)
    assert lines() == [
        {
            "principal": "owner",
            "channel": "cli",
            "plugin": "guard-plugin",
            "operation": "touch",
            "tier": "T2",
            "decision": "allow",
            "reason": "overwrite",
            "target": "out",
        }
    ]


@pytest.mark.parametrize("cls", ["scratch", "normal", "private", "secret"])
def test_external_never_lowered(work, cls):
    recorder = Recorder()
    run(work, config(work, other=cls), recorder, external=[str(work / "other")])
    assert recorder.calls == [("T3", "external", {})]


def test_adjust_error_keeps_secret_floor(work, monkeypatch):
    def broken(*args: Any) -> str:
        raise RuntimeError("broken")

    monkeypatch.setattr(guard_module, "adjust", broken)
    recorder = Recorder()
    cfg = config(work, secret="secret", scratch="scratch", normal="normal")
    run(
        work,
        cfg,
        recorder,
        read=[str(work / "secret" / "a.txt"), str(work / "normal" / "a.txt")],
        write=[str(work / "secret" / "new.txt"), str(work / "scratch" / "new.txt")],
    )
    run(work, cfg, recorder, write=[str(work / "scratch" / "x.txt")], overwrite=[str(work / "scratch")])
    assert recorder.calls == [
        ("T1", "secret_read", {"data_class": "secret", "action_tier": "T0"}),
        ("T2", "secret_write", {"data_class": "secret", "action_tier": "T1"}),
        ("T2", "overwrite", {"data_class": "scratch", "action_tier": "T2"}),
    ]


def test_junction_into_scratch_classified_by_target(work):
    link = work / "scratch" / "link"
    try:
        os.symlink(work / "secret", link, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("cannot create a directory link here")
    recorder = Recorder()
    out = run(work, config(work, scratch="scratch", secret="secret"), recorder, read=[str(link / "a.txt")])
    assert out.label == "secret"
    run(work, config(work, scratch="scratch", secret="secret"), recorder, overwrite=[str(link)])
    assert recorder.calls == [
        ("T1", "secret_read", {"data_class": "secret", "action_tier": "T0"}),
        ("T2", "overwrite", {"data_class": "secret", "action_tier": "T2"}),
    ]
    assert RECEIVED == [real(work / "secret" / "a.txt")]


def test_context_for_shares_guard(work):
    recorder = Recorder()
    out = run(
        work,
        config(work, secret="secret", normal="normal"),
        recorder,
        read=[str(work / "normal" / "a.txt")],
        callee_read=[str(work / "secret" / "a.txt")],
    )
    assert out.callee_shares_guard
    assert out.label == "secret"
    assert recorder.calls == [("T1", "secret_read", {"data_class": "secret", "action_tier": "T0"})]


def test_mark_data_only_raises(work):
    tool = build_tool(
        ENTRY, channel="cli", approver=Recorder(), config=config(work, secret="secret", scratch="scratch")
    )
    tool.ctx.mark_data(str(work / "other"))
    assert tool.ctx.data_label == "private"
    tool.ctx.mark_data(str(work / "scratch"))
    assert tool.ctx.data_label == "private"
    tool.ctx.mark_data(str(work / "secret"))
    assert tool.ctx.data_label == "secret"
    with pytest.raises(ToolError):
        tool.ctx.mark_data("\\\\server\\share\\x")
