"""SqliteBus.prune_watchers: stale `request-*` watcher subscriptions (#124)."""

import sqlite3
import time

import pytest

from lfmap_core import ToolError
from lfmap_core.events_sqlite import SqliteBus

DAY = 86400


class Clock:
    def __init__(self) -> None:
        self.now = time.time()

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def path(tmp_path):
    return tmp_path / "events.db"


@pytest.fixture
def bus(path, clock):
    bus = SqliteBus(path, clock=clock)
    yield bus
    bus.close()


def names(path) -> list[str]:
    with sqlite3.connect(path) as db:
        return [row[0] for row in db.execute("SELECT name FROM subscriptions ORDER BY name")]


def delivery_count(path) -> int:
    with sqlite3.connect(path) as db:
        return db.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0]


def add(bus, name):
    bus.subscribe(name, "jobs.>", lambda event: None)


def test_old_request_subscription_is_removed_with_its_deliveries(bus, clock, path):
    add(bus, "request-abc")
    for _ in range(3):
        bus.publish("jobs.one", {}, source="core")
    with sqlite3.connect(path) as db:
        db.execute("UPDATE deliveries SET state = 'leased' WHERE rowid = 1")
        db.execute("UPDATE deliveries SET state = 'dead' WHERE rowid = 2")
        states = {row[0] for row in db.execute("SELECT state FROM deliveries")}
    assert states == {"ready", "leased", "dead"}
    clock.now += DAY + 1
    assert bus.prune_watchers(older_than=DAY) == 1
    assert names(path) == []
    assert delivery_count(path) == 0


def test_young_request_subscription_stays(bus, clock, path):
    add(bus, "request-abc")
    bus.publish("jobs.one", {}, source="core")
    clock.now += DAY - 1
    assert bus.prune_watchers(older_than=DAY) == 0
    assert names(path) == ["request-abc"]
    assert delivery_count(path) == 1


def test_other_names_stay(bus, clock, path):
    for name in ("adapter-echo", "requestx", "myrequest-1"):
        add(bus, name)
    add(bus, "request-old")
    bus.publish("jobs.one", {}, source="core")
    clock.now += 2 * DAY
    assert bus.prune_watchers(older_than=DAY) == 1
    assert names(path) == ["adapter-echo", "myrequest-1", "requestx"]
    assert delivery_count(path) == 3


@pytest.mark.parametrize("value", [-1, float("nan"), "1"])
def test_invalid_older_than_is_refused(bus, value):
    with pytest.raises(ToolError) as error:
        bus.prune_watchers(older_than=value)
    assert error.value.code == "invalid_input"


def test_prune_is_unchanged_when_watchers_exist(bus, clock, path):
    add(bus, "request-abc")
    bus.publish("jobs.one", {}, source="core")
    with sqlite3.connect(path) as db:
        db.execute("UPDATE deliveries SET state = 'done'")
    bus.publish("jobs.two", {}, source="core")
    clock.now += 2 * DAY
    assert bus.prune(older_than=DAY) == 1
    assert bus.prune_watchers(older_than=DAY) == 1
