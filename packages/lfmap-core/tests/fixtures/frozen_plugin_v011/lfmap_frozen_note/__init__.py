from lfmap_core.runtime import default_context
from lfmap_frozen_note.schemas import ShoutInput, ShoutOutput
from lfmap_frozen_note.tool import FrozenNoteTool


def shout(inp: ShoutInput) -> ShoutOutput:
    return FrozenNoteTool(default_context("frozen-note")).shout(inp)
