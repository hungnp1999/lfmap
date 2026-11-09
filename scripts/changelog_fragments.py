"""Collect changelog fragments from changelog.d/ into CHANGELOG.md at release time.

Usage:
    python scripts/changelog_fragments.py check
    python scripts/changelog_fragments.py release X.Y.Z [--date YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import datetime
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATEGORIES = ("added", "changed", "fixed", "removed", "security")
NAME_RE = re.compile(r"^(?P<slug>[a-z0-9][a-z0-9-]*)\.(?P<category>[a-z]+)\.md$")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
UNRELEASED = "## [Unreleased]"


def read_fragments(directory: Path) -> tuple[dict[str, list[tuple[Path, str]]], list[str]]:
    """Return fragments grouped by category and a list of problems."""
    groups: dict[str, list[tuple[Path, str]]] = {c: [] for c in CATEGORIES}
    problems: list[str] = []
    for path in sorted(directory.glob("*.md")):
        if path.name == "README.md":
            continue
        match = NAME_RE.match(path.name)
        if not match or match["category"] not in CATEGORIES:
            problems.append(f"{path.name}: name must be <slug>.<{'|'.join(CATEGORIES)}>.md")
            continue
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            problems.append(f"{path.name}: empty")
        elif text.startswith(("- ", "#")):
            problems.append(f"{path.name}: write the entry text only, without '- ' or a heading")
        else:
            groups[match["category"]].append((path, text))
    return groups, problems


def render_section(version: str, date: str, groups: dict[str, list[tuple[Path, str]]], legacy: str) -> str:
    lines = [f"## [{version}] - {date}", ""]
    for category in CATEGORIES:
        if groups[category]:
            lines += [f"### {category.capitalize()}", ""]
            lines += [f"- {' '.join(text.split())}" for _, text in groups[category]]
            lines.append("")
    if legacy.strip():
        lines += ["### Earlier entries (written before changelog fragments)", "", legacy.strip(), ""]
    return "\n".join(lines)


def split_changelog(text: str) -> tuple[str, str, str]:
    """Return (head, unreleased body, rest) around the [Unreleased] section."""
    start = text.index(UNRELEASED)
    body_start = start + len(UNRELEASED)
    nxt = re.search(r"^## ", text[body_start:], re.MULTILINE)
    end = body_start + nxt.start() if nxt else len(text)
    return text[:start], text[body_start:end], text[end:]


def release(root: Path, version: str, date: str) -> list[Path]:
    if not VERSION_RE.match(version):
        raise SystemExit(f"version must look like 1.2.3, got {version!r}")
    groups, problems = read_fragments(root / "changelog.d")
    if problems:
        raise SystemExit("\n".join(problems))
    changelog = root / "CHANGELOG.md"
    head, legacy, rest = split_changelog(changelog.read_text(encoding="utf-8"))
    section = render_section(version, date, groups, legacy)
    changelog.write_text(f"{head}{UNRELEASED}\n\n{section}\n{rest}".rstrip() + "\n", encoding="utf-8")
    used = [path for entries in groups.values() for path, _ in entries]
    for path in used:
        path.unlink()
    return used


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="validate fragment names and content")
    rel = sub.add_parser("release", help="write fragments into CHANGELOG.md and delete them")
    rel.add_argument("version")
    rel.add_argument("--date", default=datetime.date.today().isoformat())
    args = parser.parse_args(argv)
    if args.command == "check":
        groups, problems = read_fragments(ROOT / "changelog.d")
        for problem in problems:
            print(problem, file=sys.stderr)
        print(f"{sum(len(v) for v in groups.values())} fragment(s), {len(problems)} problem(s)")
        return 1 if problems else 0
    used = release(ROOT, args.version, args.date)
    print(f"released {args.version} with {len(used)} fragment(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
