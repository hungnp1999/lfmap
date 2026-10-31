"""Load replay cases (`cases/<id>/`) and work packages (`package.toml` + `standard.md`)."""

import json
import re
import tomllib
from pathlib import Path

from common.models import Card, Package
from common.prompts import STANDARD

_TESTS_RE = re.compile(r"TESTS \(already written, ([^;)\s]+)")
_TARGET_RE = re.compile(r"^\+\+\+ b/(\S+)$", re.MULTILINE)


def case_dirs(root: Path) -> list[Path]:
    """Every case folder under root (a folder holding card.md and diff.patch), sorted by name."""
    return sorted(p for p in root.iterdir() if (p / "card.md").is_file() and (p / "diff.patch").is_file())


def load_card(case: Path) -> Card:
    """Replay card of one case: id = folder name, target from the diff, frozen tests from the card text."""
    prompt = (case / "card.md").read_text(encoding="utf-8")
    diff = (case / "diff.patch").read_text(encoding="utf-8")
    log = case / "test.log"
    target = _TARGET_RE.search(diff)
    if target is None:
        raise ValueError(f"{case.name}: diff.patch names no file")
    return Card(
        id=case.name,
        title=f"replay {case.name}",
        target=target.group(1),
        scope=[target.group(1)],
        tests=_TESTS_RE.findall(prompt),
        prompt=prompt,
        replay_diff=diff,
        replay_log=log.read_text(encoding="utf-8") if log.is_file() else None,
    )


def load_expected(case: Path) -> dict:
    """`expected.json` of one case."""
    return json.loads((case / "expected.json").read_text(encoding="utf-8"))


def case_package(case: Path, workdir: Path | None = None) -> Package:
    """One-card package that replays a case."""
    return Package(id=case.name, goal=f"Replay case {case.name}.", standard=STANDARD, workdir=workdir)


def load_package(folder: Path, workdir: Path | None = None) -> Package:
    """Package from folder/package.toml (`id`, `goal`) and folder/standard.md (default: the review standard)."""
    data = tomllib.loads((folder / "package.toml").read_text(encoding="utf-8"))
    standard = folder / "standard.md"
    text = standard.read_text(encoding="utf-8") if standard.is_file() else STANDARD
    return Package(id=data["id"], goal=data["goal"], standard=text, workdir=workdir)
