"""FakeModel for offline contract tests (E5): scripted replies chosen by a marker in the user message."""

import json
from dataclasses import dataclass, field


@dataclass
class FakeModel:
    """ChatModel with scripted replies: the first rule whose marker is in the user message answers.

    Each rule holds a queue of replies; the last one repeats. No rule matching is an AssertionError,
    so a test notices calls it did not expect.
    """

    name: str
    rules: list[tuple[str, list[str]]] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)

    def on(self, marker: str, *replies: str) -> "FakeModel":
        """Add a rule; returns self for chaining."""
        self.rules.append((marker, list(replies)))
        return self

    def chat(self, system: str, user: str, schema: dict | None = None) -> str:
        """Next scripted reply of the first rule whose marker occurs in user."""
        self.calls.append(user)
        for marker, replies in self.rules:
            if marker in user:
                return replies.pop(0) if len(replies) > 1 else replies[0]
        raise AssertionError(f"FakeModel {self.name}: no rule for message starting {user[:80]!r}")


def work_reply(path: str, code: str) -> str:
    """A Working reply in the card format: FILE line and one python block."""
    return f"FILE: {path}\n```python\n{code}```\n"


def review_reply(verdict: str, findings: list[dict] | None = None, notes: str = "") -> str:
    """A Leading review reply as JSON."""
    return json.dumps({"verdict": verdict, "findings": findings or [], "notes": notes})


def plan_reply(cards: list[dict]) -> str:
    """A Leading plan reply as JSON."""
    return json.dumps({"cards": cards})
