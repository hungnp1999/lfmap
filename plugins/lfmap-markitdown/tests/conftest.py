import os
from pathlib import Path

import pytest

from lfmap_core import ToolContext
from lfmap_core.permissions import PermissionManager
from lfmap_markitdown.tool import MarkitdownTool


@pytest.fixture
def root(tmp_path: Path) -> Path:
    folder = tmp_path / "docs"
    folder.mkdir()
    return Path(os.path.realpath(folder))


@pytest.fixture
def tool(root: Path) -> MarkitdownTool:
    permissions = PermissionManager([str(root)], [str(root)])
    return MarkitdownTool(ToolContext(plugin_id="markitdown", permissions=permissions, temp_dir=root / "tmp"))
