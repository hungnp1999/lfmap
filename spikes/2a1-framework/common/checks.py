"""Deterministic checks for seeds the standard gates cannot see (task F7); never a model."""

import os
import shutil
from pathlib import Path

from common import gates
from common.models import Card, GateResult, Package

PROBES_DIR = Path(__file__).resolve().parent.parent / "probes"
PROBES: dict[str, list[str]] = {
    "packages/lfmap-knowledge/src/lfmap_knowledge/extract.py": ["test_probe_extract.py"],
    "packages/lfmap-knowledge/src/lfmap_knowledge/embed.py": ["test_probe_embed.py"],
}
CHECK_GATES = {"ruff_extra", "probes"}
RUFF_EXTRA = ["--isolated", "--line-length", "120", "--select", "S110,S112,S608"]
RUFF_TYPED = ["--config", "lint.flake8-bandit.check-typed-exception = true"]


def probes_for(target: str) -> list[Path]:
    """Hidden probe files for a card target, [] when none were written."""
    return [PROBES_DIR / name for name in PROBES.get(target, [])]


def _ruff_extra(package: Package, card: Card, workdir: Path) -> GateResult:
    cmd = [*package.ruff_cmd, "check", *RUFF_EXTRA, *RUFF_TYPED, card.target]
    return gates._run("ruff_extra", cmd, workdir)


def _probe_dir(workdir: Path, card: Card) -> str:
    """Folder of the card's first frozen test, inside the workdir."""
    root = os.path.realpath(workdir)
    folder = os.path.realpath(os.path.join(root, os.path.dirname(card.tests[0])))
    if not folder.startswith(root + os.sep):
        raise ValueError(f"path outside the workdir: {card.tests[0]}")
    return folder


def _probes(package: Package, card: Card, workdir: Path, probes: list[Path]) -> GateResult:
    """Copy the probes next to the frozen tests, run them once, remove them again."""
    folder = _probe_dir(workdir, card)
    copied: list[Path] = []
    try:
        for probe in probes:
            target = Path(folder, probe.name)
            shutil.copyfile(probe, target)
            copied.append(target)
        rels = [p.relative_to(os.path.realpath(workdir)).as_posix() for p in copied]
        result = gates._run("probes", [*package.pytest_cmd, *rels], workdir)
    finally:
        for path in copied:
            path.unlink(missing_ok=True)
    return GateResult(name="probes", ok=result.ok, output=f"{', '.join(p.name for p in probes)}\n{result.output}")


def run_checks(package: Package, card: Card) -> list[GateResult]:
    """`ruff_extra` and, when the target has probes and the card has frozen tests, `probes`; [] without a workdir."""
    if package.workdir is None:
        return []
    results = [_ruff_extra(package, card, package.workdir)]
    probes = probes_for(card.target)
    if probes and card.tests:
        results.append(_probes(package, card, package.workdir, probes))
    return results
