from lfmap_core import Tool, ToolError, operation
from lfmap_frozen_note.schemas import MissingInput, SaveInput, SaveOutput, ShoutInput, ShoutOutput


class FrozenNoteTool(Tool):
    @operation("shout")
    def shout(self, inp: ShoutInput) -> ShoutOutput:
        """Upper-case the text."""
        return ShoutOutput(text=inp.text.upper())

    @operation("save")
    def save(self, inp: SaveInput) -> SaveOutput:
        """Write the text to a file."""
        target = self.ctx.permissions.require_write(inp.path)
        target.write_text(inp.text, encoding="utf-8")
        return SaveOutput(path=str(target), bytes=len(inp.text.encode("utf-8")))

    @operation("missing")
    def missing(self, inp: MissingInput) -> ShoutOutput:
        """Always fail with not_found."""
        raise ToolError("not_found", "No such note", {})
