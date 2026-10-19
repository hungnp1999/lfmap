from lfmap_core import Tool, ToolError, operation
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


class MarkitdownTool(Tool):
    @operation("classify")
    def classify(self, inp: ClassifyInput) -> ClassifyOutput:
        """Check whether a local file can be converted to Markdown, and whether it needs OCR."""
        raise ToolError("internal", "not implemented")

    @operation("convert")
    def convert(self, inp: ConvertInput) -> ConvertOutput:
        """Convert one local file to Markdown and return the text; nothing is written to disk."""
        raise ToolError("internal", "not implemented")

    @operation("export")
    def export(self, inp: ExportInput) -> ExportOutput:
        """Convert a file or folder and write <name>.md files into an export folder."""
        raise ToolError("internal", "not implemented")

    @operation("info")
    def info(self, inp: InfoInput) -> InfoOutput:
        """Report the plugin and MarkItDown versions, supported formats and OCR availability."""
        raise ToolError("internal", "not implemented")
