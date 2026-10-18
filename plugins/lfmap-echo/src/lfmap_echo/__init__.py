"""Sample LFMAP plugin. SDK: `from lfmap_echo import say, SayInput`."""

from lfmap_core.runtime import default_context
from lfmap_echo.schemas import SayInput, SayOutput
from lfmap_echo.tool import EchoTool


def say(inp: SayInput) -> SayOutput:
    return EchoTool(default_context("echo")).say(inp)


__all__ = ["EchoTool", "SayInput", "SayOutput", "say"]
