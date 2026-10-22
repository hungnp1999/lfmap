import pytest
from pydantic import BaseModel
from typer.testing import CliRunner

from lfmap_core import Tool, ToolError, operation
from lfmap_core.cli import build_app
from lfmap_core.manifest import parse_manifest
from lfmap_core.registry import PluginEntry, Registry
from lfmap_core.runtime import call_tier

MANIFEST = """
[plugin]
id = "tiered"
name = "Tiered"
version = "1.0.0"
description = "Test plugin."
license = "Apache-2.0"
[plugin.entrypoint]
module = "tests"
class = "TieredTool"
[[operations]]
name = "run"
input = "x:RunInput"
output = "x:RunOutput"
side_effects = "external"
min_tier = "T1"
[[operations]]
name = "plain"
input = "x:RunInput"
output = "x:RunOutput"
side_effects = "external"
"""


class RunInput(BaseModel):
    script: str


class RunOutput(BaseModel):
    ran: str


class TieredTool(Tool):
    @classmethod
    def call_tier(cls, operation: str, inp: BaseModel, settings: dict) -> str | None:
        if inp.script == "boom":
            raise RuntimeError("broken hook")
        return settings.get("tiers", {}).get(inp.script)

    @operation("run")
    def run(self, inp: RunInput) -> RunOutput:
        """Run something."""
        return RunOutput(ran=inp.script)

    @operation("plain")
    def plain(self, inp: RunInput) -> RunOutput:
        """Run something without min_tier."""
        return RunOutput(ran=inp.script)


@pytest.fixture
def entry() -> PluginEntry:
    return PluginEntry("tiered", TieredTool, parse_manifest(MANIFEST))


def _config(**tiers: str) -> dict:
    return {"plugins": {"tiered": {"settings": {"tiers": tiers}}}}


@pytest.mark.parametrize(
    ("script", "expected"),
    [
        ("low", "T1"),
        ("mid", "T2"),
        ("high", "T3"),
        ("zero", "T1"),  # below min_tier: clamped up
        ("unset", "T3"),  # hook returns None
        ("odd", "T3"),  # not a tier
        ("boom", "T3"),  # hook raises
    ],
)
def test_call_tier_is_clamped_between_min_tier_and_declared(entry, script, expected):
    config = _config(low="T1", mid="T2", high="T3", zero="T0", odd="T9")
    assert call_tier(entry, "run", {"script": script}, config) == expected


def test_operation_without_min_tier_ignores_the_hook(entry):
    assert call_tier(entry, "plain", {"script": "low"}, _config(low="T1")) == "T3"


def test_invalid_input_keeps_the_declared_tier(entry):
    assert call_tier(entry, "run", {"wrong": 1}, _config(low="T1")) == "T3"


def test_bad_settings_keep_the_declared_tier(entry):
    assert call_tier(entry, "run", {"script": "low"}, {"plugins": {"tiered": {"settings": "x"}}}) == "T3"


def test_unknown_operation_is_not_found(entry):
    with pytest.raises(ToolError) as error:
        call_tier(entry, "nope", {}, {})
    assert error.value.code == "not_found"


@pytest.mark.parametrize(("side_effects", "min_tier"), [("none", "T0"), ("local_write", "T1"), ("external", "T3")])
def test_min_tier_must_be_below_the_declared_tier(side_effects, min_tier):
    text = MANIFEST.replace(
        'side_effects = "external"\nmin_tier = "T1"', f'side_effects = "{side_effects}"\nmin_tier = "{min_tier}"'
    )
    with pytest.raises(ToolError):
        parse_manifest(text)


def test_cli_runs_a_t1_call_without_asking_and_refuses_t3(entry, user_dirs):
    (user_dirs / "config.toml").write_text(
        '[plugins.tiered.settings.tiers]\nlow = "T1"\nhigh = "T3"\n', encoding="utf-8"
    )
    registry = Registry()
    registry.register(entry)
    app = build_app(registry)
    runner = CliRunner()
    low = runner.invoke(app, ["tiered", "run", "--script", "low", "--json"])
    assert low.exit_code == 0, low.output
    assert '"ran": "low"' in low.output
    high = runner.invoke(app, ["tiered", "run", "--script", "high", "--json"])
    assert isinstance(high.exception, ToolError)
    assert high.exception.details["tier"] == "T3"
