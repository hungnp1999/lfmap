"""Quote check and seed scoring, ported from `docs/handoff/prep/2026-10-24-framework-spike/bench_b0.py`."""

import re

from common.models import Finding, Report

SEED_WINDOW = 3


def norm(text: str) -> str:
    """Collapse whitespace so quotes match regardless of indentation and line breaks."""
    return re.sub(r"\s+", " ", text).strip()


def _strip_marker(line: str) -> str:
    return line[1:] if line[:1] in "+- " else line


def diff_text(diff: str) -> str:
    """Normalised diff content without the +/-/space markers."""
    return norm("\n".join(_strip_marker(ln) for ln in diff.splitlines()))


def line_index(diff: str) -> list[str]:
    """Normalised diff lines without markers, in order."""
    return [norm(_strip_marker(ln)) for ln in diff.splitlines()]


def position(lines: list[str], text: str) -> int:
    """Index of the line equal to text, or containing it when text is longer than 12 characters; -1 if none."""
    text = norm(text)
    for i, line in enumerate(lines):
        if text and (text == line or (len(text) > 12 and text in line)):
            return i
    return -1


def is_quoted(finding: Finding, diff: str) -> bool:
    """True when the finding's quote occurs in the diff."""
    quote = norm(finding.quote)
    return bool(quote) and quote in diff_text(diff)


def check_quotes(report: Report, diff: str) -> Report:
    """Copy of report with unquoted findings moved to `dropped` (counted as hallucinated)."""
    kept = [f for f in report.findings if is_quoted(f, diff)]
    dropped = [f for f in report.findings if not is_quoted(f, diff)]
    return report.model_copy(update={"findings": kept, "dropped": report.dropped + dropped})


def caught_seed(seed: str, keywords: list[str], lines: list[str], findings: list[Finding]) -> bool:
    """A seed counts as caught by a finding quoted within SEED_WINDOW lines of it or naming a keyword."""
    seed_at = position(lines, seed)
    for finding in findings:
        at = position(lines, finding.quote)
        if seed_at >= 0 and at >= 0 and abs(at - seed_at) <= SEED_WINDOW:
            return True
        if any(k.lower() in finding.problem.lower() for k in keywords):
            return True
    return False


def seeds_caught(expected: dict, diff: str, findings: list[Finding]) -> list[str]:
    """Seeded lines of a case (`expected.json`) caught by the kept findings."""
    lines = line_index(diff)
    keywords = expected.get("keywords", [])
    return [s for s in expected.get("seeded", []) if caught_seed(s, keywords, lines, findings)]
