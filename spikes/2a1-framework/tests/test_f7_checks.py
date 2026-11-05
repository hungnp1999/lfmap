"""Frozen tests of task F7: deterministic checks for the gate-invisible seeds (handoff 2026-11-05-f7).

Copy unchanged to spikes/2a1-framework/tests/. They run offline on Linux and Windows without the lfmap
workspace at 018ffdf: ruff runs on the case modules in a temp folder, the probe gate runs with a fake pytest.
"""

import os
import sys
from pathlib import Path

import pytest

from common.cases import case_package, load_card
from common.checks import CHECK_GATES, PROBES_DIR, probes_for, run_checks
from common.gates import files_from_patch, gate_verdict, replay_attempt, run_gates, snapshot
from common.models import Attempt, Card, GateResult, Package
from run import split_cmd
from score import checks_caught

SPIKE = Path(__file__).resolve().parent.parent
CASES = SPIKE / "cases"
EXTRACT = "packages/lfmap-knowledge/src/lfmap_knowledge/extract.py"
EMBED = "packages/lfmap-knowledge/src/lfmap_knowledge/embed.py"
OK_PYTEST = [sys.executable, "-c", "pass"]
RED_PYTEST = [sys.executable, "-c", "raise SystemExit(1)"]


def _workdir(tmp_path: Path, case: str) -> tuple[Path, Card]:
    """tmp workdir holding only the case's target module; the card without frozen tests (no probe run)."""
    card = load_card(CASES / case)
    for rel, text in files_from_patch(card.replay_diff or "").items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tmp_path, card.model_copy(update={"tests": []})


def _gate(gates: list[GateResult], name: str) -> GateResult:
    return next(g for g in gates if g.name == name)


# --- ruff_extra: S110 (typed exceptions too), S112, S608 ----------------------------------------------------


@pytest.mark.parametrize(
    ("case", "ok"),
    [
        ("K4-clean", True),
        ("K6-clean", True),
        ("K7-clean", True),
        ("K4-clean-seed-swallow", False),
        ("K6-seed-sql", False),
        ("K7-real", False),
        ("K4-clean-seed-exists", True),
        ("K7-clean-seed-count", True),
    ],
)
def test_ruff_extra(tmp_path: Path, case: str, ok: bool):
    workdir, card = _workdir(tmp_path, case)
    gate = _gate(run_checks(Package(id="p", workdir=workdir), card), "ruff_extra")
    assert gate.ok is ok, gate.output


def test_ruff_extra_names_the_rule(tmp_path: Path):
    workdir, card = _workdir(tmp_path, "K6-seed-sql")
    assert "S608" in _gate(run_checks(Package(id="p", workdir=workdir), card), "ruff_extra").output


# --- probes ------------------------------------------------------------------------------------------------


def test_probes_for_known_targets():
    assert probes_for(EXTRACT) == [PROBES_DIR / "test_probe_extract.py"]
    assert probes_for(EMBED) == [PROBES_DIR / "test_probe_embed.py"]
    assert probes_for("calc.py") == []
    assert all(p.is_file() for p in probes_for(EXTRACT) + probes_for(EMBED))


def _with_tests(tmp_path: Path, case: str) -> tuple[Path, Card]:
    workdir, card = _workdir(tmp_path, case)
    test = workdir / "packages/lfmap-knowledge/tests/test_extract.py"
    test.parent.mkdir(parents=True, exist_ok=True)
    test.write_text("def test_x():\n    pass\n", encoding="utf-8")
    return workdir, card.model_copy(update={"tests": ["packages/lfmap-knowledge/tests/test_extract.py"]})


def test_probe_gate_runs_next_to_the_frozen_tests_and_cleans_up(tmp_path: Path):
    workdir, card = _with_tests(tmp_path, "K4-clean")
    before = snapshot(workdir)
    gates = run_checks(Package(id="p", workdir=workdir, pytest_cmd=OK_PYTEST), card)
    probe = _gate(gates, "probes")
    assert probe.ok, probe.output
    assert "test_probe_extract.py" in probe.output
    assert snapshot(workdir) == before


def test_probe_gate_red_when_pytest_fails(tmp_path: Path):
    workdir, card = _with_tests(tmp_path, "K4-clean")
    gates = run_checks(Package(id="p", workdir=workdir, pytest_cmd=RED_PYTEST), card)
    assert _gate(gates, "probes").ok is False
    assert not list((workdir / "packages/lfmap-knowledge/tests").glob("test_probe_*.py"))


def test_no_probe_gate_without_probes_or_frozen_tests(tmp_path: Path):
    workdir, card = _workdir(tmp_path, "K4-clean")
    assert "probes" not in {g.name for g in run_checks(Package(id="p", workdir=workdir), card)}
    other = card.model_copy(update={"target": "calc.py", "scope": ["calc.py"], "tests": ["tests/test_calc.py"]})
    (workdir / "calc.py").write_text("X = 1\n", encoding="utf-8")
    assert "probes" not in {g.name for g in run_checks(Package(id="p", workdir=workdir), other)}


def test_no_checks_without_workdir():
    card = load_card(CASES / "K4-clean")
    assert run_checks(Package(id="p"), card) == []


# --- wiring into the gates, verdict and score ---------------------------------------------------------------


def test_run_gates_appends_the_checks(tmp_path: Path):
    workdir, card = _workdir(tmp_path, "K6-seed-sql")
    names = [g.name for g in run_gates(Package(id="p", workdir=workdir), card, snapshot(workdir))]
    assert names[:4] == ["scope", "tests_unchanged", "ruff_check", "ruff_format"]
    assert "ruff_extra" in names


def test_checks_can_be_switched_off(tmp_path: Path):
    workdir, card = _workdir(tmp_path, "K6-seed-sql")
    package = Package(id="p", workdir=workdir, checks=False)
    assert not {g.name for g in run_gates(package, card, snapshot(workdir))} & CHECK_GATES


def test_red_check_means_rework():
    gates = [GateResult(name="pytest", ok=True), GateResult(name="probes", ok=False, output="1 failed")]
    attempt = Attempt(card_id="c", round=1, source="replay", diff="x", gates=gates)
    assert gate_verdict(attempt) == "rework"
    assert checks_caught(attempt) is True


def test_checks_caught_ignores_the_old_gates():
    gates = [GateResult(name="pytest", ok=False), GateResult(name="ruff_extra", ok=True)]
    assert checks_caught(Attempt(card_id="c", round=1, source="replay", diff="x", gates=gates)) is False
    assert checks_caught(Attempt(card_id="c", round=1, source="replay", diff="x", gates=[])) is False


# --- all 19 cases on the real workspace (run where LFMAP_F7_WORKDIR is set) -------------------------------

WORKDIR = os.environ.get("LFMAP_F7_WORKDIR")  # clean git worktree of lfmap at 018ffdf, `uv sync` done
WORKSPACE_PYTEST = os.environ.get("LFMAP_F7_PYTEST", "")  # e.g. "<worktree>/.venv/Scripts/python -m pytest -q"
CAUGHT = {
    "K4-clean-seed-exists",
    "K4-clean-seed-swallow",
    "K4-clean-seed-order",
    "K4-clean-seed-unlink",
    "K6-seed-sql",
    "K7-clean-seed-count",
    "K4-real",
    "K7-real",
}
ALL_CASES = sorted(p.name for p in CASES.iterdir() if (p / "expected.json").is_file())


@pytest.mark.skipif(not WORKDIR, reason="LFMAP_F7_WORKDIR not set")
@pytest.mark.parametrize("case", ALL_CASES)
def test_checks_on_the_workspace(case: str):
    card = load_card(CASES / case)
    package = case_package(CASES / case, Path(WORKDIR))
    package.pytest_cmd = split_cmd(WORKSPACE_PYTEST)
    try:
        attempt = replay_attempt(package, card)
    finally:
        (Path(WORKDIR) / card.target).unlink(missing_ok=True)
    assert checks_caught(attempt) is (case in CAUGHT), attempt.gate_log()
