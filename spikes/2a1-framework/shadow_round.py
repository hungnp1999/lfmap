"""Leading shadow round on the real Flows cases (#207): `prepare`, `preflight`, `run` (also `run --dry-run`).

    uv run python shadow_round.py preflight          # checks only, changes nothing
    uv run python shadow_round.py run --dry-run      # whole loop with a fake runner, no Ollama, no git
    uv run python shadow_round.py run                # the real round (use Run-Shadow207.ps1)

The round runs 15 cases one after another (4 real, 11 seeded copies), one Leading review each, and writes
`results/<date>-shadow207/`. Rerunnable: a case with a `run_metrics.json` is skipped. Per-case state is the gate
worktree (own copies `lfmap-s207-*` made by `prepare`): the target module is removed before each case and again
afterwards, and checked out from the commit when the round ends (also on a crash). Any other change in a worktree
stops the round (it is not ours to clean up).
"""

import argparse
import datetime as dt
import getpass
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEV = Path(os.environ.get("LFMAP_DEV_DIR", r"D:\Development"))
MODULE_DIR = Path("packages/lfmap-core/src/lfmap_core")
OLLAMA = "http://127.0.0.1:11434"
LEADING = "qwen3.8:27b"
AGENT_USER = "lfmap-agent"
ENV = {"LFMAP_NUM_CTX": "20480", "LFMAP_NUM_PREDICT": "14000"}  # as the 09-10/11 re-run
CASE_TIMEOUT = 4200  # seconds; the longest earlier review was 2014 s
STOP_HOUR = 5.0  # no new case after 05:00 local time (round ends before 06:00)


@dataclass(frozen=True)
class Gate:
    """A gate worktree: detached at a PR merge commit with one target module removed."""

    name: str
    folder: str
    commit: str
    target: str


GATES = {
    "FL1": Gate("FL1", "lfmap-s207-fl1", "45a1039", "flows.py"),
    "FL1b": Gate("FL1b", "lfmap-s207-fl1b", "45a1039", "flows_refs.py"),
    "FL2": Gate("FL2", "lfmap-s207-fl2", "ac7ef50", "flows_run.py"),
    "FL3": Gate("FL3", "lfmap-s207-fl3", "a3fe9b7", "flows_triggers.py"),
}
# Real cases first (compare with the 4/4 of 08/11), then the seeds nobody saw, then the rest.
CASES = [
    "FL1-real", "FL1b-real", "FL2-real", "FL3-real",
    "FL2-seed-wrongprop", "FL2-seed-bytes", "FL1-seed-boundary", "FL3-seed-loop",
    "FL2-seed-exists", "FL2-seed-swallow", "FL1-seed-default", "FL1b-seed-truthy",
    "FL1b-seed-embed", "FL3-seed-idem", "FL3-seed-swallow",
]  # fmt: skip


def gate_of(case: str) -> Gate:
    """FL1-real -> GATES['FL1']; FL1b-seed-embed -> GATES['FL1b']."""
    return GATES[case.split("-")[0]]


def worktree(gate: Gate, dev: Path = DEV) -> Path:
    return dev / gate.folder


def target_path(gate: Gate, dev: Path = DEV) -> Path:
    return worktree(gate, dev) / MODULE_DIR / gate.target


def git(folder: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(folder), *args], capture_output=True, text=True, check=False)
    return done.stdout.strip() if done.returncode == 0 else f"ERROR {done.stderr.strip()}"


def unexpected_changes(folder: Path, gate: Gate) -> list[str]:
    """`git status` lines that are not ours: anything but the target module, which may be clean or deleted."""
    rel = (MODULE_DIR / gate.target).as_posix()
    lines = git(folder, "status", "--porcelain", "--untracked-files=no").splitlines()
    return [x for x in lines if x.strip() and not (x.endswith(rel) and x[:2].strip() in ("", "D"))]


def prepare(dev: Path = DEV) -> None:
    """Create the four gate worktrees as this user (idempotent): detached at the PR merge commit, `uv sync` once."""
    clone = dev / "lfmap"
    git(clone, "fetch", "origin")
    for gate in GATES.values():
        folder = worktree(gate, dev)
        if not folder.is_dir():
            print(f"worktree {gate.name}: creating {folder} at {gate.commit}")
            subprocess.run(
                ["git", "-C", str(clone), "worktree", "add", "--detach", str(folder), gate.commit], check=True
            )
        if not (folder / ".venv").is_dir():
            print(f"worktree {gate.name}: uv sync")
            subprocess.run(["uv", "sync"], cwd=folder, check=True)


def restore_targets(dev: Path = DEV) -> None:
    """Put each target module back to the commit's version (the round removes it before every case)."""
    for gate in GATES.values():
        git(worktree(gate, dev), "checkout", "--", (MODULE_DIR / gate.target).as_posix())


def http_json(path: str) -> dict:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(OLLAMA + path, timeout=15) as reply:
        return json.load(reply)


def check_gpu_idle(samples: int = 5, limit: int = 30) -> str | None:
    """Median GPU utilisation over `samples` readings 2 s apart; desktop noise (about 10 %) passes, a running job does not."""
    readings: list[int] = []
    for n in range(samples):
        try:
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, check=True, timeout=30,
            ).stdout.split()[0]  # fmt: skip
            readings.append(int(out))
        except (OSError, subprocess.SubprocessError, IndexError, ValueError) as error:
            return f"nvidia-smi failed: {error}"
        if n < samples - 1:
            time.sleep(2)
    median = sorted(readings)[len(readings) // 2]
    return f"GPU busy (median {median} % of {readings})" if median > limit else None


def preflight(dev: Path = DEV) -> list[tuple[str, bool, str]]:
    """(check, ok, detail) rows. Reads only."""
    rows: list[tuple[str, bool, str]] = []

    def add(name: str, problem: str | None, ok_detail: str = "ok") -> None:
        rows.append((name, problem is None, problem or ok_detail))

    add("user", None if getpass.getuser() == AGENT_USER else f"signed in as {getpass.getuser()}, need {AGENT_USER}")
    try:
        add("ollama", None, f"version {http_json('/api/version').get('version')}")
        loaded = [m["name"] for m in http_json("/api/ps").get("models", [])]
        add("ollama idle", f"models loaded: {loaded}" if loaded else None)
        tags = [m["name"] for m in http_json("/api/tags").get("models", [])]
        add(f"model {LEADING}", None if LEADING in tags else f"not in `ollama list`: {tags}")
    except (OSError, ValueError) as error:
        add("ollama", f"not answering on {OLLAMA} (tray app running?): {error}")
    add("gpu idle", check_gpu_idle())
    add("uv", None if shutil.which("uv") else "uv not on PATH")
    add("disk", None if shutil.disk_usage(HERE).free > 5 * 2**30 else "less than 5 GB free")
    missing = [c for c in CASES if not (HERE / "cases" / c / "expected.json").exists()]
    add("cases", f"missing in this checkout: {missing}" if missing else None, f"{len(CASES)} cases present")
    for gate in GATES.values():
        folder = worktree(gate, dev)
        if not folder.is_dir():
            add(f"worktree {gate.name}", f"{folder} not found")
            continue
        head = git(folder, "rev-parse", "HEAD")
        problems = []
        if not head.startswith(gate.commit):
            problems.append(f"HEAD {head[:9]}, expected {gate.commit}")
        if other := unexpected_changes(folder, gate):
            problems.append(f"changes that are not ours: {other}")
        ruff = subprocess.run(
            ["uv", "run", "--no-sync", "--directory", str(folder), "ruff", "--version"],
            capture_output=True, text=True, check=False,
        )  # fmt: skip
        if ruff.returncode:
            problems.append("`uv run --no-sync ruff --version` fails (uv sync in that worktree)")
        add(f"worktree {gate.name}", "; ".join(problems) or None, f"{folder} @ {head[:9]}, clean")
    return rows


def finished(res: Path, case: str) -> bool:
    for f in res.glob("*/run_metrics.json"):
        try:
            found = json.loads(f.read_text(encoding="utf-8")).get("case") == case
        except (OSError, ValueError):
            found = False  # unreadable metrics: the case is run again
        if found:
            return True
    return False


Runner = Callable[[list[str], dict[str, str], Path, int], int]


def real_runner(cmd: list[str], env: dict[str, str], log: Path, timeout: int) -> int:
    with log.open("ab") as out:
        try:
            return subprocess.run(
                cmd, cwd=HERE, env={**os.environ, **env}, stdout=out, stderr=out, timeout=timeout, check=False
            ).returncode
        except subprocess.TimeoutExpired:
            out.write(f"\nTIMEOUT after {timeout} s\n".encode())
            return 124


def case_command(case: str, res: Path, dev: Path) -> list[str]:
    wt = worktree(gate_of(case), dev)
    return [
        "uv", "run", "python", "run.py", "run", "--variant", "plain", "--case", case, "--workdir", str(wt),
        "--pytest-cmd", f"uv run --no-sync --directory {wt} pytest -q",
        "--ruff-cmd", f"uv run --no-sync --directory {wt} ruff",
        "--think", "true", "--verdict-mode", "gates", "--state-dir", str(res),
    ]  # fmt: skip


def run_round(
    res: Path, dev: Path, runner: Runner, cases: list[str], now: Callable[[], float], stop_hour: float = STOP_HOUR
) -> list[dict]:
    """Run the cases serially; returns one row per case. The target module is removed again after each case."""
    (res / "logs").mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    for n, case in enumerate(cases, 1):
        gate = gate_of(case)
        target = target_path(gate, dev)
        if finished(res, case):
            print(f"[{n}/{len(cases)}] skip {case} (finished)")
            rows.append({"case": case, "status": "skipped"})
            continue
        local = dt.datetime.fromtimestamp(now())
        if stop_hour <= local.hour + local.minute / 60 < 12:
            print(f"[{n}/{len(cases)}] stop: after {stop_hour:g}:00, {case} and the rest left for a rerun")
            rows.extend({"case": c, "status": "not_started"} for c in cases[n - 1 :] if not finished(res, c))
            break
        if other := unexpected_changes(worktree(gate, dev), gate):
            raise SystemExit(f"stop on surprise before {case}: {other}")
        target.unlink(missing_ok=True)  # the harness adds it back with git apply; restored from the commit at the end
        print(f"[{n}/{len(cases)}] {case} {local:%H:%M}")
        started = time.monotonic()
        try:
            code = runner(case_command(case, res, dev), ENV, res / "logs" / f"{case}.log", CASE_TIMEOUT)
        finally:
            target.unlink(missing_ok=True)  # ours: the case wrote it
        seconds = int(time.monotonic() - started)
        rows.append({"case": case, "status": "ok" if code == 0 else f"exit {code}", "seconds": seconds})
        if code:
            print(f"  exit {code}, continuing (see logs/{case}.log)")
    return rows


def resume_and_score(res: Path, runner: Runner) -> tuple[int, int]:
    """Approve every paused run (the review is already stored), then write score.txt."""
    ok = bad = 0
    for d in sorted(res.iterdir()) if res.is_dir() else []:
        if (d / "awaiting_approval.json").exists() and not (d / "done.json").exists():
            cmd = ["uv", "run", "python", "run.py", "resume", d.name, "--approve", "--state-dir", str(res)]
            code = runner(cmd, {}, res / "logs" / f"resume-{d.name}.log", 600)
            ok, bad = (ok + 1, bad) if code == 0 else (ok, bad + 1)
    runner(["uv", "run", "python", "score.py", str(res)], {}, res / "score.txt", 600)  # the log is the table
    return ok, bad


def fake_runner_factory(dev: Path) -> Runner:
    """Dry-run runner: 'writes' the target like the harness and a run folder; fails the 3rd case, times out the 5th."""
    calls = {"n": 0}

    def fake(cmd: list[str], env: dict[str, str], log: Path, timeout: int) -> int:
        log.write_text("fake\n", encoding="utf-8")
        if "resume" in cmd or "score.py" in cmd:
            return 0
        calls["n"] += 1
        case = cmd[cmd.index("--case") + 1]
        target_path(gate_of(case), dev).write_text("# fake module\n", encoding="utf-8")
        if calls["n"] == 5:
            return 124
        if calls["n"] == 3:
            return 1
        res = Path(cmd[cmd.index("--state-dir") + 1])
        (res / f"plain-{case}-fake").mkdir(parents=True)
        (res / f"plain-{case}-fake" / "run_metrics.json").write_text(json.dumps({"case": case}), encoding="utf-8")
        return 0

    return fake


def dry_run() -> int:
    """Two loops over the whole list in a temp tree; the second must skip finished cases and redo the failed."""
    with tempfile.TemporaryDirectory() as tmp:
        dev = Path(tmp) / "dev"
        for gate in GATES.values():
            folder = worktree(gate, dev)
            (folder / MODULE_DIR).mkdir(parents=True)
            target_path(gate, dev).write_text("# committed module\n", encoding="utf-8")
            for step in (
                ["init", "-q"],
                ["add", "."],
                ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x"],
            ):
                subprocess.run(["git", "-C", str(folder), *step], check=True)
        res = Path(tmp) / "res"
        noon_minus = dt.datetime(2026, 11, 10, 23, 30).timestamp()
        runner = fake_runner_factory(dev)
        for loop in (1, 2):
            rows = run_round(res, dev, runner, CASES, lambda: noon_minus)
            print(f"loop {loop}:", {r["status"] for r in rows})
            left = [t for g in GATES.values() if (t := target_path(g, dev)).exists()]
            assert not left, f"targets left behind: {left}"
        restore_targets(dev)
        assert all(target_path(g, dev).read_text(encoding="utf-8") == "# committed module\n" for g in GATES.values())
        late = run_round(Path(tmp) / "late", dev, runner, CASES, lambda: dt.datetime(2026, 11, 11, 5, 10).timestamp())
        assert all(r["status"] == "not_started" for r in late), late
        target_path(GATES["FL3"], dev).write_text("edited by someone", encoding="utf-8")
        try:
            run_round(Path(tmp) / "dirty", dev, runner, ["FL3-real"], lambda: noon_minus)
        except SystemExit as stop:
            print("stop on surprise ok:", stop)
        else:
            raise AssertionError("dirty worktree did not stop the round")
    print("DRY RUN OK (fake runner, no Ollama, no git)")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("preflight")
    sub.add_parser("prepare", help="create the gate worktrees as this user (idempotent)")
    run = sub.add_parser("run")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--date", default=dt.date.today().isoformat())
    args = ap.parse_args(argv)
    if args.command == "preflight":
        rows = preflight()
        for name, ok, detail in rows:
            print(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}")
        bad = [r for r in rows if not r[1]]
        print("PREFLIGHT " + ("FAILED: skip tonight" if bad else "PASSED"))
        return 1 if bad else 0
    if args.command == "prepare":
        prepare()
        return 0
    if args.dry_run:
        return dry_run()
    rows = preflight()
    if bad := [r for r in rows if not r[1]]:
        print("\n".join(f"FAIL {n}: {d}" for n, _, d in bad))
        return 1
    res = HERE / "results" / f"{args.date}-shadow207"
    try:
        rows = run_round(res, DEV, real_runner, CASES, time.time)
    finally:
        restore_targets(DEV)
    ok, bad_resume = resume_and_score(res, real_runner)
    (res / "summary.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"results: {res}\ncases: {len(rows)}, resumed ok: {ok}, resume failed: {bad_resume}")
    for row in rows:
        print(f"  {row['case']}: {row['status']} {row.get('seconds', '')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
