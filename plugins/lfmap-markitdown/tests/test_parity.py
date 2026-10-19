"""TC-M8: classification must match MarkitdownTool on the shared fixtures.

expected.json is recorded once on Windows with fixtures/parity/Get-Expected.ps1.
"""

import json
import os
from pathlib import Path

import pytest

from lfmap_core import ToolContext
from lfmap_core.permissions import PermissionManager
from lfmap_markitdown.schemas import ClassifyInput
from lfmap_markitdown.tool import MarkitdownTool

FIXTURES = Path(__file__).parent / "fixtures" / "parity"
EXPECTED = FIXTURES / "expected.json"


def _expected() -> list[dict]:
    if not EXPECTED.exists():
        return []
    return json.loads(EXPECTED.read_text(encoding="utf-8"))["files"]


@pytest.mark.skipif(not EXPECTED.exists(), reason="expected.json not recorded yet (Get-Expected.ps1)")
@pytest.mark.parametrize("expected", _expected(), ids=lambda item: item["name"])
def test_matches_markitdowntool(expected: dict) -> None:
    root = os.path.realpath(FIXTURES)
    tool = MarkitdownTool(ToolContext(plugin_id="markitdown", permissions=PermissionManager([root], [])))
    result = tool.classify(ClassifyInput(path=str(FIXTURES / expected["name"])))
    assert (result.supported, result.needs_ocr, result.markdown_eligible, result.reason_code) == (
        expected["supported"],
        expected["needs_ocr"],
        expected["markdown_eligible"],
        expected["reason_code"],
    )
    assert result.low_quality_pages == expected["low_quality_pages"]
    if expected["text_quality"] is None:
        assert result.text_quality is None
    else:
        assert result.text_quality == pytest.approx(expected["text_quality"], abs=0.001)


def test_fixtures_are_small() -> None:
    assert sum(path.stat().st_size for path in FIXTURES.iterdir()) < 2 * 1024 * 1024
