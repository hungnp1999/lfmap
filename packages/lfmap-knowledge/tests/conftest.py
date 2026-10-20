import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from lfmap_core.permissions import PermissionManager


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "data"
    folder.mkdir()
    return Path(os.path.realpath(folder))


@pytest.fixture
def root(tmp_path: Path) -> Path:
    folder = tmp_path / "docs"
    folder.mkdir()
    return Path(os.path.realpath(folder))


@pytest.fixture
def perms(root: Path, data_dir: Path) -> PermissionManager:
    return PermissionManager([str(root)], [str(data_dir)])


@pytest.fixture
def db(data_dir: Path) -> Iterator:
    from lfmap_knowledge.store import connect, migrate

    conn = connect(data_dir / "catalog.db")
    migrate(conn)
    yield conn
    conn.close()
