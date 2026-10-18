from pathlib import Path

import pytest

from lfmap_core import ToolError
from lfmap_core.manifest import load_manifest, parse_manifest

FIXTURE = Path(__file__).parent / "fixtures" / "echo.lfmap.toml"


def test_load_valid():
    manifest = load_manifest(FIXTURE)
    assert manifest.plugin.id == "echo"
    assert manifest.plugin.entrypoint.class_ == "EchoTool"
    assert manifest.operation("say").side_effects == "none"
    assert manifest.permissions.network is False
    assert manifest.dependencies.licenses.allowed == ["MIT", "Apache-2.0"]


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ('id = "echo"', 'id = "Echo_1"'),
        ('version = "0.1.0"', 'version = "1.0"'),
        ('side_effects = "none"', 'side_effects = "maybe"'),
        ("[permissions]", "[permissions]\nnetwrok = true"),
    ],
)
def test_invalid_schema(old, new):
    text = FIXTURE.read_text(encoding="utf-8").replace(old, new)
    with pytest.raises(ToolError) as caught:
        parse_manifest(text)
    assert caught.value.code == "invalid_input"


def test_invalid_toml():
    with pytest.raises(ToolError) as caught:
        parse_manifest("[plugin")
    assert caught.value.code == "invalid_input"


def test_missing_file(tmp_path):
    with pytest.raises(ToolError) as caught:
        load_manifest(tmp_path / "lfmap.toml")
    assert caught.value.code == "not_found"
