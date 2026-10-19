"""LFMAP markitdown plugin. SDK: `from lfmap_markitdown import convert, ConvertInput`."""

from lfmap_core.runtime import default_context
from lfmap_markitdown.schemas import (
    ClassifyInput,
    ClassifyOutput,
    ConvertInput,
    ConvertOutput,
    ExportInput,
    ExportOutput,
    InfoInput,
    InfoOutput,
)
from lfmap_markitdown.tool import MarkitdownTool


def _tool() -> MarkitdownTool:
    return MarkitdownTool(default_context("markitdown"))


def classify(inp: ClassifyInput) -> ClassifyOutput:
    return _tool().classify(inp)


def convert(inp: ConvertInput) -> ConvertOutput:
    return _tool().convert(inp)


def export(inp: ExportInput) -> ExportOutput:
    return _tool().export(inp)


def info(inp: InfoInput | None = None) -> InfoOutput:
    return _tool().info(inp or InfoInput())


__all__ = [
    "ClassifyInput",
    "ClassifyOutput",
    "ConvertInput",
    "ConvertOutput",
    "ExportInput",
    "ExportOutput",
    "InfoInput",
    "InfoOutput",
    "MarkitdownTool",
    "classify",
    "convert",
    "export",
    "info",
]
