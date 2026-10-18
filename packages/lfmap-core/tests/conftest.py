import pytest
from pydantic import BaseModel, Field

from lfmap_core import Tool, ToolError, operation
from lfmap_core.manifest import parse_manifest
from lfmap_core.registry import PluginEntry, Registry


class GreetInput(BaseModel):
    name: str = Field(description="Who to greet.")
    times: int = 1
    shout: bool = False


class GreetOutput(BaseModel):
    message: str


class NestedInput(BaseModel):
    names: list[str]


class FakeTool(Tool):
    @operation("greet")
    def greet(self, inp: GreetInput) -> GreetOutput:
        """Greet someone."""
        if inp.name == "error":
            raise ToolError("not_found", "No such person", {"name": inp.name})
        message = " ".join([f"Hello {inp.name}"] * inp.times)
        return GreetOutput(message=message.upper() if inp.shout else message)

    @operation("write")
    def write(self, inp: NestedInput) -> GreetOutput:
        """Pretend to write something."""
        return GreetOutput(message=",".join(inp.names))


MANIFEST = """
[plugin]
id = "fake-plugin"
name = "Fake"
version = "1.2.3"
description = "Test plugin."
license = "Apache-2.0"
[plugin.entrypoint]
module = "tests"
class = "FakeTool"
[[operations]]
name = "greet"
input = "x:GreetInput"
output = "x:GreetOutput"
[[operations]]
name = "write"
input = "x:NestedInput"
output = "x:GreetOutput"
side_effects = "local_write"
"""


@pytest.fixture
def registry() -> Registry:
    reg = Registry()
    reg.register(PluginEntry("fake-plugin", FakeTool, parse_manifest(MANIFEST)))
    return reg
