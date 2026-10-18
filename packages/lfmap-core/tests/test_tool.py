import pytest
from pydantic import BaseModel

from lfmap_core import Tool, ToolContext, ToolError, invoke, operation


class SayInput(BaseModel):
    text: str


class SayOutput(BaseModel):
    text: str


class EchoTool(Tool):
    @operation("say")
    def say(self, inp: SayInput) -> SayOutput:
        """Repeat the text.

        Longer description.
        """
        return SayOutput(text=inp.text)

    def helper(self) -> None:
        pass


def make() -> EchoTool:
    return EchoTool(ToolContext(plugin_id="echo"))


def test_operations():
    specs = EchoTool.operations()
    assert list(specs) == ["say"]
    assert specs["say"].input_model is SayInput
    assert specs["say"].output_model is SayOutput
    assert specs["say"].description == "Repeat the text."


def test_invoke():
    assert invoke(make(), "say", {"text": "hi"}) == SayOutput(text="hi")


def test_invoke_invalid_payload():
    with pytest.raises(ToolError) as caught:
        invoke(make(), "say", {"wrong": 1})
    assert caught.value.code == "invalid_input"
    assert caught.value.details["errors"]


def test_invoke_unknown_operation():
    with pytest.raises(ToolError) as caught:
        invoke(make(), "shout", {})
    assert caught.value.code == "not_found"


def test_bad_signature():
    class Bad(Tool):
        @operation("bad")
        def bad(self, text: str) -> SayOutput:
            return SayOutput(text=text)

    with pytest.raises(TypeError, match="bad"):
        Bad.operations()


def test_duplicate_operation():
    class Dup(Tool):
        @operation("say")
        def one(self, inp: SayInput) -> SayOutput:
            return SayOutput(text="1")

        @operation("say")
        def two(self, inp: SayInput) -> SayOutput:
            return SayOutput(text="2")

    with pytest.raises(TypeError, match="Duplicate"):
        Dup.operations()


def test_health_default():
    assert make().health() == {"ok": True}
