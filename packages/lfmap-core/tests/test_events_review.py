"""Checks added in the EB-1 review, beyond the frozen contract tests."""

import sqlite3
from pathlib import Path

import pytest

from lfmap_core.errors import ToolError
from lfmap_core.events import Event, InProcessBus
from lfmap_core.events_sqlite import SqliteBus


def _buses(tmp_path: Path) -> list:
    return [InProcessBus(), SqliteBus(tmp_path / "events.db")]


def test_keyboard_interrupt_stops_drain(tmp_path: Path) -> None:
    for bus in _buses(tmp_path):

        def stop(event: Event) -> None:
            raise KeyboardInterrupt

        bus.subscribe("sub", "a.b", stop)
        bus.publish("a.b", source="core")
        with pytest.raises(KeyboardInterrupt):
            bus.drain()
        bus.close()


@pytest.mark.parametrize("bad", [0, -1, 1.5, True, "5"])
def test_max_attempts_is_checked(tmp_path: Path, bad: object) -> None:
    with pytest.raises(ToolError) as error:
        InProcessBus(max_attempts=bad)  # type: ignore[arg-type]
    assert error.value.code == "invalid_input"
    with pytest.raises(ToolError) as error:
        SqliteBus(tmp_path / "events.db", max_attempts=bad)  # type: ignore[arg-type]
    assert error.value.code == "invalid_input"


def test_newer_schema_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "events.db"
    db = sqlite3.connect(path)
    db.execute("PRAGMA user_version=2")
    db.close()
    with pytest.raises(ToolError) as error:
        SqliteBus(path)
    assert error.value.code == "backend_unavailable"


def test_handler_may_unsubscribe_itself(tmp_path: Path) -> None:
    for bus in _buses(tmp_path):
        seen: list[str] = []

        def once(event: Event, bus=bus, seen=seen) -> None:
            seen.append(event.id)
            bus.unsubscribe("sub")

        bus.subscribe("sub", "a.>", once)
        bus.publish("a.b", source="core")
        bus.publish("a.c", source="core")
        assert bus.drain() == 1
        assert len(seen) == 1
        assert bus.drain() == 0
        bus.close()
