"""Variant contract (handoff "Hợp đồng biến thể"), the same for every variant; E4, E5 and E7 are checked here."""

import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import pytest
from contract_fixture import (
    escalate_models,
    flow,
    full_models,
    make_package,
    replay_card,
    replay_models,
)

from common.metrics import Trace, traced
from common.models import AwaitingApproval, Done, Models, RunRecord, RunResult

SPIKE = Path(__file__).resolve().parent.parent
IMPLEMENTED = {"plain"}
VARIANTS = [
    pytest.param(
        name,
        marks=()
        if name in IMPLEMENTED
        else pytest.mark.xfail(raises=NotImplementedError, strict=True, reason="variant not implemented yet (F2/F3)"),
    )
    for name in ("plain", "pydanticai", "langgraph")
]
OFFLINE_LIMIT_S = 30


def _python(*args: str) -> str:
    done = subprocess.run([sys.executable, *args], cwd=SPIKE, capture_output=True, text=True, timeout=OFFLINE_LIMIT_S)
    if done.returncode != 0 and "NotImplementedError" in done.stderr:
        raise NotImplementedError(done.stderr[-300:])
    assert done.returncode == 0, done.stderr
    return done.stdout


def _record(run_dir: Path) -> RunRecord:
    return RunRecord.model_validate_json((run_dir / "reports.json").read_text(encoding="utf-8"))


@dataclass
class FullRun:
    """One run of the full scenario, shared by the read-only tests of a variant."""

    variant: str
    result: RunResult
    models: Models
    trace: Trace
    root: Path


@pytest.fixture(scope="module")
def full(request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory) -> FullRun:
    variant, root, trace, models = request.param, tmp_path_factory.mktemp(request.param), Trace(), full_models()
    result = flow(variant).run_flow(make_package(root), models=traced(models, trace), state_dir=root / "state")
    return FullRun(variant, result, models, trace, root)


@pytest.mark.parametrize("full", VARIANTS, indirect=True)
def test_full_run_pauses_for_approval(full: FullRun):
    result = full.result
    assert result.status == "awaiting_approval"
    assert result.verdicts == {"calc": "ready", "greet": "ready"}
    assert result.attempts == {"calc": 3, "greet": 1}
    awaiting = AwaitingApproval.model_validate_json((result.run_dir / "awaiting_approval.json").read_text())
    assert awaiting.run_id == result.run_id and awaiting.variant == full.variant
    assert awaiting.cards == ["calc", "greet"]
    assert Path(awaiting.report_path).is_file()
    assert not (result.run_dir / "done.json").exists()
    assert (full.root / "work" / "calc.py").read_text() == "def add(a: int, b: int) -> int:\n    return a + b\n"


@pytest.mark.parametrize("full", VARIANTS, indirect=True)
def test_batch_phase_order(full: FullRun):
    assert full.trace.sequence() == ["leading", "working", "leading", "working", "leading"]
    calls = [c.model for c in full.trace.calls]
    assert calls == ["leading"] + ["working"] * 3 + ["leading"] * 2 + ["working", "leading"]


@pytest.mark.parametrize("full", VARIANTS, indirect=True)
def test_report_drops_unquoted_findings(full: FullRun):
    first = next(r for r in _record(full.result.run_dir).reports if r.card_id == "calc")
    assert first.verdict == "rework"
    assert [f.quote for f in first.findings] == ["return a + b"]
    assert [f.quote for f in first.dropped] == ["os.system(cmd)"]


@pytest.mark.parametrize("full", VARIANTS, indirect=True)
def test_gate_failure_is_retried_with_the_gate_log(full: FullRun):
    attempts = [a for a in _record(full.result.run_dir).attempts if a.card_id == "calc"]
    assert [a.round for a in attempts] == [1, 2, 3]
    assert [a.ok for a in attempts] == [False, True, True]
    calls = full.models.working.calls
    assert "[pytest]" in calls[1] and "FIX THIS" in calls[1]
    assert "Reviewer findings" in calls[3]


@pytest.mark.parametrize("variant", VARIANTS)
def test_second_rework_escalates(variant: str, tmp_path: Path):
    result = flow(variant).run_flow(make_package(tmp_path), models=escalate_models(), state_dir=tmp_path / "s")
    assert result.verdicts == {"calc": "escalate"}
    assert result.attempts == {"calc": 2}


@pytest.mark.parametrize("variant", VARIANTS)
def test_replay_skips_plan_and_work(variant: str, tmp_path: Path):
    models = replay_models()
    result = flow(variant).run_flow(
        make_package(tmp_path), models=models, state_dir=tmp_path / "s", replay_cards=[replay_card()]
    )
    assert result.verdicts == {"calc": "ready"}
    assert models.working.calls == []
    assert len(models.leading.calls) == 1
    attempt = _record(result.run_dir).attempts[0]
    assert attempt.source == "replay" and attempt.ok and attempt.diff == replay_card().replay_diff


@pytest.mark.parametrize("variant", VARIANTS)
def test_reject_in_process(variant: str, tmp_path: Path):
    module = flow(variant)
    paused = module.run_flow(make_package(tmp_path), models=escalate_models(), state_dir=tmp_path / "s")
    done = module.resume(paused.run_id, approve=False, state_dir=tmp_path / "s")
    assert done.status == "rejected" and done.verdicts == paused.verdicts
    assert Done.model_validate_json((done.run_dir / "done.json").read_text()).approved is False
    with pytest.raises(ValueError):
        module.resume(paused.run_id, approve=True, state_dir=tmp_path / "s")


@pytest.mark.parametrize("variant", VARIANTS)
def test_resume_after_process_exit_offline(variant: str, tmp_path: Path):
    started = time.perf_counter()
    run_id = _python("tests/contract_fixture.py", variant, str(tmp_path)).strip()
    out = _python("run.py", "resume", run_id, "--approve", "--state-dir", str(tmp_path / "state"))
    assert time.perf_counter() - started < OFFLINE_LIMIT_S
    result = json.loads(out)
    assert result["status"] == "approved" and result["verdicts"] == {"calc": "ready", "greet": "ready"}
    run_dir = tmp_path / "state" / run_id
    assert Done.model_validate_json((run_dir / "done.json").read_text()).approved is True
    assert json.loads((run_dir / "resume_metrics.json").read_text())["guard_blocked"] == []
