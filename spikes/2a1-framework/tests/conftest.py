import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from common.guard import SocketGuard

sys.path.insert(0, str(Path(__file__).resolve().parent))


@pytest.fixture(autouse=True)
def guard() -> Iterator[SocketGuard]:
    with SocketGuard() as active:
        yield active
    assert active.blocked == [], f"non-loopback connections: {active.blocked}"
