from lfmap_core import Tool, operation
from lfmap_echo.schemas import SayInput, SayOutput


class EchoTool(Tool):
    @operation("say")
    def say(self, inp: SayInput) -> SayOutput:
        """Repeat the given text, optionally in upper case."""
        text = inp.text.upper() if inp.upper else inp.text
        return SayOutput(text=text, length=len(text))
