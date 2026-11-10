"""LFMAP plugin `llm`. SDK: `from lfmap_llm import summarise, SummariseInput`."""

from lfmap_core.registry import load_entry
from lfmap_core.runtime import build_tool
from lfmap_llm.schemas import (
    ClassifyInput,
    ClassifyOutput,
    ExtractInput,
    ExtractOutput,
    SummariseInput,
    SummariseOutput,
)
from lfmap_llm.tool import LlmTool


def _tool() -> LlmTool:
    tool = build_tool(load_entry(LlmTool))
    assert isinstance(tool, LlmTool)
    return tool


def summarise(inp: SummariseInput) -> SummariseOutput:
    return _tool().summarise(inp)


def extract(inp: ExtractInput) -> ExtractOutput:
    return _tool().extract(inp)


def classify(inp: ClassifyInput) -> ClassifyOutput:
    return _tool().classify(inp)


__all__ = [
    "ClassifyInput",
    "ClassifyOutput",
    "ExtractInput",
    "ExtractOutput",
    "LlmTool",
    "SummariseInput",
    "SummariseOutput",
    "classify",
    "extract",
    "summarise",
]
