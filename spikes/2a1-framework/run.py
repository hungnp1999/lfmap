"""Spike runner: `run --variant X --case NAME|--package DIR` pauses for approval; `resume RUN_ID --approve|--reject`.

Every command runs under the socket guard (E2) and exits 3 if a non-loopback connection was attempted.
Results go to `results/<date>/` unless `--state-dir` is given; each run gets its own folder `<state-dir>/<run_id>/`.
"""

import argparse
import datetime as dt
import importlib
import json
import os
import shlex
import sys
import time
from pathlib import Path
from types import ModuleType

from common.cases import case_package, load_card, load_package
from common.guard import SocketGuard
from common.metrics import Trace, traced
from common.models import AwaitingApproval, Package, RunResult
from common.ollama import URL, default_models

HERE = Path(__file__).resolve().parent
VARIANTS = ("plain", "pydanticai", "langgraph")
GUARD_EXIT = 3


def load_variant(name: str) -> tuple[ModuleType, float]:
    """The variant's flow module and its cold import time in seconds (S4)."""
    started = time.perf_counter()
    module = importlib.import_module(f"variants.{name}.flow")
    return module, time.perf_counter() - started


def default_state_dir() -> Path:
    """results/<today>/"""
    return HERE / "results" / dt.date.today().isoformat()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Command line of run.py."""
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run one package or replay case until the approval pause")
    run.add_argument("--variant", choices=VARIANTS, required=True)
    source = run.add_mutually_exclusive_group(required=True)
    source.add_argument("--case", help="case folder name under --cases-dir (replay: no Plan phase)")
    source.add_argument("--package", type=Path, help="folder with package.toml and standard.md (Plan phase runs)")
    run.add_argument("--cases-dir", type=Path, default=HERE / "cases")
    run.add_argument("--workdir", type=Path, help="git worktree for the gates; without it no gate runs")
    run.add_argument("--state-dir", type=Path, default=None)
    run.add_argument("--pytest-cmd", default=None, help="command of the pytest gate; default: this Python's pytest -q")
    run.add_argument("--ruff-cmd", default=None, help="command of the ruff gate; default: this Python's ruff")
    run.add_argument("--ollama", default=URL)
    run.add_argument("--think", default=None, help="true, false, low, medium or high; default: model default")
    res = sub.add_parser("resume", help="finish a paused run in this new process")
    res.add_argument("run_id")
    decision = res.add_mutually_exclusive_group(required=True)
    decision.add_argument("--approve", action="store_true")
    decision.add_argument("--reject", action="store_true")
    res.add_argument("--state-dir", type=Path, default=None)
    return ap.parse_args(argv)


def _think(value: str | None) -> bool | str | None:
    return {"true": True, "false": False}.get(value, value) if value is not None else None


def split_cmd(text: str) -> list[str]:
    """Split a command string into argv; Windows paths keep their backslashes."""
    return shlex.split(text, posix=(os.name != "nt"))


def build_package(args: argparse.Namespace) -> tuple[Package, list | None]:
    """The package to run and the replay cards (None when the Plan phase runs), with gate commands applied."""
    if args.case:
        case = args.cases_dir / args.case
        package, replay = case_package(case, args.workdir), [load_card(case)]
    else:
        package, replay = load_package(args.package, args.workdir), None
    if args.pytest_cmd:
        package.pytest_cmd = split_cmd(args.pytest_cmd)
    if args.ruff_cmd:
        package.ruff_cmd = split_cmd(args.ruff_cmd)
    return package, replay


def command_run(args: argparse.Namespace, state_dir: Path) -> tuple[RunResult, dict]:
    """Run until the pause; returns the result and the metrics of this process."""
    module, import_s = load_variant(args.variant)
    package, replay = build_package(args)
    trace = Trace()
    models = traced(default_models(args.ollama, _think(args.think)), trace)
    started = time.perf_counter()
    result = module.run_flow(package, models=models, state_dir=state_dir, replay_cards=replay)
    wall = time.perf_counter() - started
    metrics = {
        "variant": args.variant,
        "case": args.case,
        "package": str(args.package) if args.package else None,
        "import_s": round(import_s, 3),
        "wall_s": round(wall, 3),
        "model_s": round(trace.model_seconds(), 3),
        "overhead_s": round(wall - trace.model_seconds(), 3),
        "calls": [vars(c) for c in trace.calls],
        "sequence": trace.sequence(),
        "swaps": trace.swaps(),
    }
    return result, metrics


def command_resume(args: argparse.Namespace, state_dir: Path) -> tuple[RunResult, dict]:
    """Load the paused run's variant from awaiting_approval.json and resume it."""
    awaiting = AwaitingApproval.model_validate_json(
        (state_dir / args.run_id / "awaiting_approval.json").read_text(encoding="utf-8")
    )
    module, import_s = load_variant(awaiting.variant)
    started = time.perf_counter()
    result = module.resume(args.run_id, approve=args.approve, state_dir=state_dir)
    return result, {"import_s": round(import_s, 3), "wall_s": round(time.perf_counter() - started, 3)}


def write_metrics(result: RunResult, name: str, metrics: dict, guard: SocketGuard) -> None:
    """metrics of this process into the run folder, with what the guard saw."""
    metrics.update({"guard_blocked": guard.blocked, "guard_allowed": len(guard.allowed)})
    (result.run_dir / f"{name}_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """Entry point; prints the RunResult as JSON."""
    args = parse_args(argv)
    state_dir = (args.state_dir or default_state_dir()).resolve()
    state_dir.mkdir(parents=True, exist_ok=True)
    command = command_run if args.command == "run" else command_resume
    with SocketGuard() as guard:
        try:
            result, metrics = command(args, state_dir)
        except Exception:
            if not guard.blocked:
                raise
            print(f"socket guard refused: {guard.blocked}", file=sys.stderr)
            return GUARD_EXIT
    write_metrics(result, args.command, metrics, guard)
    print(result.model_dump_json(indent=2))
    if result.status == "awaiting_approval":
        print(f"next: python run.py resume {result.run_id} --approve|--reject --state-dir {state_dir}", file=sys.stderr)
    return GUARD_EXIT if guard.blocked else 0


if __name__ == "__main__":
    sys.exit(main())
