"""Prompts, JSON schemas and reply parsers shared by every variant (handoff D3: no per-variant prompts)."""

import json
import re

from pydantic import ValidationError

from common.models import Card, Finding, Package, Report

# Narrow advisory checklist (F6): the gates decide ready or rework, the model only reports what they cannot see.
STANDARD = """You are the Leading Agent, an ADVISORY code reviewer. The deterministic gates (scope, frozen tests,
ruff, pytest) decide whether the module passes; you do not. A small model wrote the diff below for the task
card. Look ONLY for these problems, which the gates cannot see:
S1 a caller-supplied path used in a file-system call (exists, is_file, open, stat, unlink) BEFORE the permission check;
S2 an exception caught and silently dropped where the card says to report or raise;
S3 SQL built from strings, or user text reaching SQL unquoted;
S4 a network call without the permission check, or proxy, userinfo or non-loopback handling the card forbids;
S5 a mutable default argument, a resource not closed, or a temp file left behind on error;
S6 a rule the card lists that the diff does not implement (a count check, an error code, an ordering, a field).
Rules: the TEST LOG and GATES section show what the gates already found; never repeat that and never report
what passing tests prove. Never report style, naming, docstrings, message wording or anything the card does not
require. Read CONTRACTS before claiming that a type raises or returns something. Every finding quotes ONE line
copied exactly from the diff and names the item (S1-S6). Verdict: "rework" if you list a finding, "ready" if
not, "escalate" only when the approach is wrong. Answer with JSON only, in this shape:
{"verdict": "ready|rework|escalate", "findings": [{"check": "S1", "file": "...", "quote": "...", "problem": "..."}],
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
14B coding model. Each card writes ONE file. Never change tests. EVERY card lists in "tests" the frozen test
files of its module, exactly as the package names them; a card without tests is refused. Import types only from
where the CONTRACTS section says they live. Answer with JSON only:
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
    text = f"WORK PACKAGE {package.id}\n{package.goal}"
    if package.contracts:
        text += f"\n\nCONTRACTS\n{package.contracts}"
    return text + f"\n\nSTANDARD\n{package.standard or STANDARD}"


def work_user(card: Card, feedback: str = "", contracts: str = "") -> str:
    """User message of a Work round; feedback is the gate log or the review findings of the last round."""
    text = f"CARD ID: {card.id}\n\n{card.prompt}"
    if contracts:
        text += f"\n\nCONTRACTS (real behaviour of the imported types)\n{contracts}"
    if feedback:
        text += f"\n\nYOUR LAST ATTEMPT WAS REJECTED. FIX THIS:\n{feedback}"
    return text


def review_user(card: Card, diff: str, test_log: str = "", contracts: str = "", gates: str = "") -> str:
    """User message of the Review phase (bench_b0.review layout plus the card id, contracts and gate summary)."""
    text = f"CARD ID: {card.id}\n\nTASK CARD\n{card.prompt}"
    if contracts:
        text += f"\n\nCONTRACTS (real behaviour of the imported types; they win over the card)\n{contracts}"
    text += f"\n\nDIFF\n{diff}"
    if gates:
        text += f"\n\nGATES\n{gates}"
    if test_log:
        text += f"\n\nTEST LOG (tail)\n{test_log[-4000:]}"
    return text


def rework_feedback(report: Report, gate_log: str = "") -> str:
    """Failed gate output (when given) and review findings as feedback for the next Work round."""
    lines = [f"- {f.check} `{f.quote}`: {f.problem}" for f in report.findings]
    text = "Reviewer findings:\n" + ("\n".join(lines) or report.notes or "(no detail)")
    return f"Failed gates:\n{gate_log}\n\n{text}" if gate_log else text


def parse_json(text: str) -> dict:
    """JSON object from a model reply; falls back to the outermost braces; {} when nothing parses."""
    for candidate in (text, text[text.find("{") : text.rfind("}") + 1]):
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:  # noqa: S112 - unparsable candidate; try the next one
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
        except ValidationError:  # noqa: S112 - invalid card entries are skipped (see docstring)
            continue
    return cards


def parse_file_reply(text: str) -> tuple[str | None, str | None]:
    """(path, code) from a Work reply: the FILE line and the first python block; None where missing."""
    path = _FILE_RE.search(text)
    block = _BLOCK_RE.search(text)
    return (path.group(1) if path else None, block.group(1) if block else None)
