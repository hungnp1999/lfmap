"""Deterministic gates and file writing for the Work phase (spec section 2); never a model."""

import difflib
import hashlib
import os
import subprocess
from pathlib import Path

from common.models import Attempt, Card, GateResult, Package
from common.prompts import parse_file_reply

SKIP_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache", "node_modules"}
GATE_TIMEOUT = 600
LOG_TAIL = 4000


def sha256(path: Path) -> str:
    """Hex SHA-256 of a file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(root: Path) -> dict[str, str]:
    """Relative POSIX path -> SHA-256 of every file under root, cache and VCS folders excluded."""
    found: dict[str, str] = {}
    for folder, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            path = Path(folder, name)
            found[path.relative_to(root).as_posix()] = sha256(path)
    return found


def changed(before: dict[str, str], after: dict[str, str]) -> set[str]:
    """Paths added, removed or modified between two snapshots."""
    return {p for p in before.keys() | after.keys() if before.get(p) != after.get(p)}


def files_from_patch(diff: str) -> dict[str, str]:
    """New-file contents of a patch that only adds files (every replay case); ValueError otherwise."""
    files: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            current = files.setdefault(line[4:].removeprefix("b/"), [])
        elif line.startswith("--- ") and line[4:] != "/dev/null":
            raise ValueError(f"only new-file patches are supported: {line}")
        elif current is not None and line.startswith("+"):
            current.append(line[1:])
    return {path: "\n".join(lines) + "\n" for path, lines in files.items()}


def make_diff(rel: str, old: str, new: str) -> str:
    """git-style unified diff of one file."""
    head = f"diff --git a/{rel} b/{rel}\n"
    lines = difflib.unified_diff(
        old.splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile=f"a/{rel}" if old else "/dev/null",
        tofile=f"b/{rel}",
    )
    return head + "".join(lines)


def write_in(workdir: Path, rel: str, text: str) -> str:
    """Write text to workdir/rel and return the previous content; refuses paths outside workdir."""
    if os.path.isabs(rel) or os.path.splitdrive(rel)[0] or rel.startswith(("\\\\", "//")):
        raise ValueError(f"path must be relative to the workdir: {rel}")
    root = os.path.realpath(workdir)
    full = os.path.realpath(os.path.join(root, rel))
    if not full.startswith(root + os.sep):
        raise ValueError(f"path outside the workdir: {rel}")
    old = Path(full).read_text(encoding="utf-8") if os.path.isfile(full) else ""
    Path(full).parent.mkdir(parents=True, exist_ok=True)
    Path(full).write_text(text, encoding="utf-8", newline="\n")
    return old


def _gate_env() -> dict[str, str]:
    """No .pyc files: a rewrite within the same second and size would otherwise import the stale bytecode."""
    return {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}


def _run(name: str, cmd: list[str], cwd: Path) -> GateResult:
    try:
        done = subprocess.run(
            cmd,
            cwd=cwd,
            env=_gate_env(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=GATE_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return GateResult(name=name, ok=False, output=f"{type(exc).__name__}: {exc}")
    return GateResult(name=name, ok=done.returncode == 0, output=(done.stdout + done.stderr)[-LOG_TAIL:])


def _scope_gate(card: Card, before: dict[str, str], after: dict[str, str]) -> GateResult:
    outside = sorted(changed(before, after) - card.allowed())
    return GateResult(name="scope", ok=not outside, output="\n".join(f"outside scope: {p}" for p in outside))


def _tests_gate(card: Card, before: dict[str, str], after: dict[str, str]) -> GateResult:
    bad = [t for t in card.tests if t not in after or before.get(t) != after[t]]
    output = "\n".join(f"test changed or missing: {t}" for t in bad)
    return GateResult(name="tests_unchanged", ok=not bad, output=output)


def run_gates(package: Package, card: Card, before: dict[str, str]) -> list[GateResult]:
    """Scope, frozen tests, ruff check, ruff format --check and pytest; [] when the package has no workdir."""
    if package.workdir is None:
        return []
    after = snapshot(package.workdir)
    gates = [_scope_gate(card, before, after), _tests_gate(card, before, after)]
    gates.append(_run("ruff_check", [*package.ruff_cmd, "check", card.target], package.workdir))
    gates.append(_run("ruff_format", [*package.ruff_cmd, "format", "--check", card.target], package.workdir))
    if card.tests:
        gates.append(_run("pytest", [*package.pytest_cmd, *card.tests], package.workdir))
    return gates


def _write_files(package: Package, files: dict[str, str]) -> str:
    diffs = []
    for rel, text in files.items():
        old = write_in(package.workdir, rel, text) if package.workdir else ""
        diffs.append(make_diff(rel, old, text))
    return "".join(diffs)


def replay_attempt(package: Package, card: Card) -> Attempt:
    """Round 1 from the card's known diff: files written, gates run, the diff kept verbatim for review."""
    before = snapshot(package.workdir) if package.workdir else {}
    files = files_from_patch(card.replay_diff or "")
    outside = sorted(set(files) - card.allowed())
    if outside:
        gate = GateResult(name="scope", ok=False, output=f"replay diff outside scope: {outside}")
        return Attempt(card_id=card.id, round=1, source="replay", diff=card.replay_diff or "", gates=[gate])
    _write_files(package, files)
    gates = run_gates(package, card, before)
    return Attempt(card_id=card.id, round=1, source="replay", diff=card.replay_diff or "", gates=gates)


def model_attempt(package: Package, card: Card, round_no: int, reply: str) -> Attempt:
    """A Work round from a model reply: only card.target is ever written, then the gates run."""
    path, code = parse_file_reply(reply)
    if code is None or path not in (None, card.target):
        output = "no python block in the reply" if code is None else f"FILE {path} is not the card target"
        gate = GateResult(name="reply", ok=False, output=f"{output} {card.target}")
        return Attempt(card_id=card.id, round=round_no, source="model", diff="", gates=[gate])
    before = snapshot(package.workdir) if package.workdir else {}
    diff = _write_files(package, {card.target: code})
    gates = run_gates(package, card, before)
    return Attempt(card_id=card.id, round=round_no, source="model", diff=diff, gates=gates)


def review_log(card: Card, attempt: Attempt) -> str:
    """Test log shown to the reviewer: failed gate output, or the case's recorded log when no gate ran."""
    if attempt.gates:
        return attempt.gate_log()
    return (card.replay_log or "") if attempt.source == "replay" else ""
