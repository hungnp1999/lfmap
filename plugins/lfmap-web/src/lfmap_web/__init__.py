"""LFMAP plugin `web`. SDK: `from lfmap_web import fetch, FetchInput`."""

from lfmap_core.registry import load_entry
from lfmap_core.runtime import build_tool
from lfmap_web.schemas import FetchInput, FetchOutput
from lfmap_web.tool import WebTool


def fetch(inp: FetchInput) -> FetchOutput:
    tool = build_tool(load_entry(WebTool))
    assert isinstance(tool, WebTool)
    return tool.fetch(inp)


__all__ = ["FetchInput", "FetchOutput", "WebTool", "fetch"]
