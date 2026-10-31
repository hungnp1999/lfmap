"""Prompts, JSON schemas and reply parsers shared by every variant (handoff D3: no per-variant prompts)."""

import json
import re

from pydantic import ValidationError

from common.models import Card, Finding, Package, Report

# Review standard of B0/B0b (bench_b0.py STANDARD), extended with the optional "file" field.
STANDARD = """You are the Leading Agent: a strict first-pass code reviewer. A small model wrote the diff
below for the task card. Check it against the card and this checklist:
C1 behaviour matches the card's API and rules; C2 edge cases and error handling the card asks for;
C3 security (SQL built from strings, paths, network use without permission, proxies, credentials);
C4 tests would fail (see the test log if given).
Style (docstring length, comments, naming) is NOT a finding: put at most one style remark in "notes";
it never changes the verdict.
Report only real problems against C1-C4. Every finding must quote ONE line copied exactly from the diff.
Verdict: "ready" (no C1-C4 problem), "rework" (fixable C1-C4 problems), "escalate" (wrong approach
or beyond a small fix). Answer with JSON only, in this shape:
{"verdict": "ready|rework|escalate", "findings": [{"check": "C1", "file": "...", "quote": "...", "problem": "..."}],
 "notes": "..."}"""

REPORT_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["ready", "rework", "escalate"]},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "check": {"type": "string"},
                    "file": {"type": "string"},
                    "quote": {"type": "string"},
                    "problem": {"type": "string"},
                },
                "required": ["check", "quote", "problem"],
            },
        },
        "notes": {"type": "string"},
    },
    "required": ["verdict", "findings"],
}

PLAN_SYSTEM = """You are the Leading Agent. Split the work package into at most 4 small task cards for a
14B coding model. Each card writes ONE file. Never change tests. Answer with JSON only:
{"cards": [{"id": "...", "title": "...", "target": "path/to/file.py", "tests": ["path/to/test_x.py"],
 "prompt": "complete card text: API with signatures, rules, which frozen tests must pass"}]}"""

PLAN_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "cards": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "target": {"type": "string"},
                    "tests": {"type": "array", "items": {"type": "string"}},
                    "prompt": {"type": "string"},
                },
                "required": ["id", "target", "prompt"],
            },
        }
    },
    "required": ["cards"],
}

WORK_SYSTEM = """You are a careful Python 3.12 developer. Follow the task card exactly.
Reply with the line `FILE: <path>`, then ONE ```python block with the COMPLETE file."""

_FILE_RE = re.compile(r"^FILE:\s*`?([^`\s]+)`?\s*$", re.MULTILINE)
_BLOCK_RE = re.compile(r"```(?:python|py)?[ \t]*\n(.*?)```", re.DOTALL)


def plan_user(package: Package) -> str:
    """User message of the Plan phase: package goal and standard."""
    return f"WORK PACKAGE {package.id}\n{package.goal}\n\nSTANDARD\n{package.standard or STANDARD}"


def work_user(card: Card, feedback: str = "") -> str:
    """User message of a Work round; feedback is the gate log or the review findings of the last round."""
    text = f"CARD ID: {card.id}\n\n{card.prompt}"
    if feedback:
        text += f"\n\nYOUR LAST ATTEMPT WAS REJECTED. FIX THIS:\n{feedback}"
    return text


def review_user(card: Card, diff: str, test_log: str = "") -> str:
    """User message of the Review phase (bench_b0.review layout plus the card id)."""
    text = f"CARD ID: {card.id}\n\nTASK CARD\n{card.prompt}\n\nDIFF\n{diff}"
    if test_log:
        text += f"\n\nTEST LOG (tail)\n{test_log[-4000:]}"
    return text


def rework_feedback(report: Report) -> str:
    """Review findings as feedback for the next Work round."""
    lines = [f"- {f.check} `{f.quote}`: {f.problem}" for f in report.findings]
    return "Reviewer findings:\n" + ("\n".join(lines) or report.notes or "(no detail)")


def parse_json(text: str) -> dict:
    """JSON object from a model reply; falls back to the outermost braces; {} when nothing parses."""
    for candidate in (text, text[text.find("{") : text.rfind("}") + 1]):
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return {}


def parse_report(card_id: str, text: str) -> Report:
    """Report from a review reply; anything unparsable gives verdict "invalid_json" (counted, never fixed)."""
    data = parse_json(text)
    if data.get("verdict") not in ("ready", "rework", "escalate"):
        return Report(card_id=card_id, verdict="invalid_json", notes=text[:500])
    findings = [Finding.model_validate(f) for f in data.get("findings", []) if _is_finding(f)]
    notes = data.get("notes") if isinstance(data.get("notes"), str) else ""
    return Report(card_id=card_id, verdict=data["verdict"], findings=findings, notes=notes)


def _is_finding(item: object) -> bool:
    try:
        Finding.model_validate(item)
    except ValidationError:
        return False
    return True


def parse_cards(text: str) -> list[Card]:
    """Cards from a Plan reply; invalid entries are skipped."""
    cards: list[Card] = []
    for item in parse_json(text).get("cards", []):
        try:
            cards.append(Card.model_validate(item))
        except ValidationError:
            continue
    return cards


def parse_file_reply(text: str) -> tuple[str | None, str | None]:
    """(path, code) from a Work reply: the FILE line and the first python block; None where missing."""
    path = _FILE_RE.search(text)
    block = _BLOCK_RE.search(text)
    return (path.group(1) if path else None, block.group(1) if block else None)
