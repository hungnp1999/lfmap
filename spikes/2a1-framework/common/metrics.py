"""Measurements: a trace of model calls (E7, S4) and the code line count for S1/S3."""

import io
import time
import tokenize
from dataclasses import dataclass, field
from pathlib import Path

from common.models import ChatModel, Models


@dataclass
class Call:
    """One model call as seen by the trace."""

    model: str
    started: float
    seconds: float
    prompt_chars: int
    reply_chars: int


@dataclass
class Trace:
    """Model calls of one process, in order."""

    calls: list[Call] = field(default_factory=list)

    def model_seconds(self) -> float:
        """Time spent inside model calls (S4 subtracts it from the wall time)."""
        return sum(c.seconds for c in self.calls)

    def sequence(self) -> list[str]:
        """Model names in call order with repeats collapsed: one entry per model load (E7)."""
        seq: list[str] = []
        for call in self.calls:
            if not seq or seq[-1] != call.model:
                seq.append(call.model)
        return seq

    def swaps(self) -> int:
        """Number of model changes between consecutive calls."""
        return max(len(self.sequence()) - 1, 0)


@dataclass
class TracedModel:
    """ChatModel wrapper that records every call into a Trace."""

    inner: ChatModel
    trace: Trace

    @property
    def name(self) -> str:
        """Name of the wrapped model."""
        return self.inner.name

    def chat(self, system: str, user: str, schema: dict | None = None) -> str:
        """Forward the call and record its duration and sizes."""
        started = time.perf_counter()
        reply = self.inner.chat(system, user, schema)
        seconds = time.perf_counter() - started
        self.trace.calls.append(Call(self.name, started, seconds, len(system) + len(user), len(reply)))
        return reply


def traced(models: Models, trace: Trace) -> Models:
    """Both models wrapped so their calls land in trace."""
    return Models(leading=TracedModel(models.leading, trace), working=TracedModel(models.working, trace))


def code_lines(path: Path) -> int:
    """Non-blank, non-comment, non-docstring lines of one Python file (S1, S3)."""
    source = path.read_text(encoding="utf-8")
    skip: set[int] = set()
    previous = tokenize.INDENT
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type == tokenize.STRING and previous in (tokenize.INDENT, tokenize.NEWLINE, tokenize.DEDENT):
            skip.update(range(tok.start[0], tok.end[0] + 1))
        if tok.type not in (tokenize.NL, tokenize.COMMENT):
            previous = tok.type
    lines = enumerate(source.splitlines(), 1)
    return sum(1 for no, line in lines if line.strip() and not line.lstrip().startswith("#") and no not in skip)


def folder_lines(folder: Path) -> int:
    """code_lines summed over every .py file under folder."""
    return sum(code_lines(p) for p in sorted(folder.rglob("*.py")))
