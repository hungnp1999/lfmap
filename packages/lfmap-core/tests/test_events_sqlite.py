"""SqliteBus beyond the shared contract: durability, leases and several processes (docs/specs/events.md section 5)."""

import sqlite3
import subprocess
import sys
import textwrap
import time

import pytest

from lfmap_core import ToolError
from lfmap_core.events_sqlite import SqliteBus


class Clock:
    def __init__(self) -> None:
        self.now = time.time()

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def path(tmp_path):
    return tmp_path / "events.db"


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def open_bus(path, clock):
    buses = []

    def make(**options):
        bus = SqliteBus(path, clock=options.pop("clock", clock), **options)
        buses.append(bus)
        return bus

    yield make
    for bus in buses:
        bus.close()


def test_creates_the_database_in_wal_mode(open_bus, path):
    open_bus()
    assert path.is_file()
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1


def test_payload_is_stored_as_json_text(open_bus, path):
    bus = open_bus()
    event = bus.publish("jobs.done", {"b": 1, "a": "Tài liệu"}, source="core")
    with sqlite3.connect(path) as db:
        row = db.execute("SELECT payload FROM events WHERE id = ?", (event.id,)).fetchone()
    assert row == ('{"a":"Tài liệu","b":1}',)


def test_events_survive_a_restart(open_bus):
    first = open_bus()
    first.subscribe("watch", "jobs.>", lambda event: None)
    event = first.publish("jobs.done", {"n": 1}, source="core")
    first.close()
    got = []
    second = open_bus()
    second.subscribe("watch", "jobs.>", got.append)
    assert second.drain() == 1
    assert [e.id for e in got] == [event.id]
    assert got[0].payload == {"n": 1}


def test_subscription_queues_while_no_process_handles_it(open_bus):
    consumer = open_bus()
    consumer.subscribe("watch", "jobs.>", lambda event: None)
    consumer.close()
    publisher = open_bus()
    publisher.publish("jobs.done", {}, source="core")
    assert publisher.drain() == 0
    got = []
    later = open_bus()
    later.subscribe("watch", "jobs.>", got.append)
    assert later.drain() == 1
    assert len(got) == 1


def test_drain_only_runs_subscriptions_with_a_handler_here(open_bus):
    one, two = open_bus(), open_bus()
    got_one, got_two = [], []
    one.subscribe("one", "jobs.>", got_one.append)
    two.subscribe("two", "jobs.>", got_two.append)
    one.publish("jobs.done", {}, source="core")
    assert one.drain() == 1
    assert (len(got_one), len(got_two)) == (1, 0)
    assert two.drain() == 1
    assert len(got_two) == 1


def test_pattern_conflict_across_instances(open_bus):
    open_bus().subscribe("watch", "jobs.>", lambda event: None)
    with pytest.raises(ToolError) as caught:
        open_bus().subscribe("watch", "flows.>", lambda event: None)
    assert caught.value.code == "invalid_input"


def test_unsubscribe_is_shared(open_bus):
    one, two = open_bus(), open_bus()
    got = []
    one.subscribe("watch", "jobs.>", got.append)
    one.publish("jobs.done", {}, source="core")
    two.unsubscribe("watch")
    assert one.drain() == 0
    assert got == []


def test_dead_letters_survive_a_restart(open_bus):
    def refuse(event):
        raise ToolError("invalid_input", "no")

    first = open_bus()
    first.subscribe("refuse", "jobs.>", refuse)
    event = first.publish("jobs.done", {}, source="core")
    first.drain()
    first.close()
    second = open_bus()
    [dead] = second.dead_letters()
    assert dead.event.id == event.id
    assert dead.error == "invalid_input: no"


def test_expired_lease_is_delivered_again_and_late_ack_is_ignored(open_bus, clock):
    first = open_bus(lease_seconds=60.0)
    second = open_bus(lease_seconds=60.0)
    seen = []

    def slow(event):
        seen.append(("first", event.attempt))
        assert second.drain() == 0
        clock.advance(61)
        assert second.drain() == 1

    first.subscribe("work", "jobs.>", slow)
    second.subscribe("work", "jobs.>", lambda event: seen.append(("second", event.attempt)))
    first.publish("jobs.done", {}, source="core")
    assert first.drain() == 1
    assert seen == [("first", 1), ("second", 2)]
    clock.advance(600)
    assert first.drain() == 0
    assert second.drain() == 0
    assert first.dead_letters() == []


def test_lease_seconds_must_be_positive(path):
    with pytest.raises(ToolError) as caught:
        SqliteBus(path, lease_seconds=0)
    assert caught.value.code == "invalid_input"


def test_prune_removes_only_old_finished_events(open_bus, path, clock):
    bus = open_bus()
    bus.subscribe("ok", "done.>", lambda event: None)

    def refuse(event):
        raise ToolError("invalid_input", "no")

    bus.subscribe("refuse", "dead.>", refuse)

    def busy(event):
        raise RuntimeError("busy")

    bus.subscribe("busy", "waiting.>", busy)
    bus.publish("done.one", {}, source="core")
    bus.publish("dead.one", {}, source="core")
    bus.publish("waiting.one", {}, source="core")
    bus.publish("nobody.listens", {}, source="core")
    bus.drain()
    assert bus.prune(older_than=3600) == 0
    clock.advance(7200)
    assert bus.prune(older_than=3600) == 2
    with sqlite3.connect(path) as db:
        topics = sorted(row[0] for row in db.execute("SELECT topic FROM events"))
    assert topics == ["dead.one", "waiting.one"]
    assert len(bus.dead_letters()) == 1


WORKER = textwrap.dedent(
    """
    import sys, time
    from pathlib import Path
    from lfmap_core.events_sqlite import SqliteBus

    bus = SqliteBus(Path(sys.argv[1]))
    out = Path(sys.argv[2])

    def handle(event):
        time.sleep(0.005)
        with out.open("a", encoding="utf-8") as file:
            file.write(event.id + "\\n")

    bus.subscribe("work", "jobs.>", handle)
    idle = 0
    while idle < 3:
        idle = idle + 1 if bus.drain(max_events=5) == 0 else 0
        time.sleep(0.01)
    bus.close()
    """
)


def test_two_processes_share_the_work_without_duplicates(path, tmp_path):
    bus = SqliteBus(path)
    bus.subscribe("work", "jobs.>", lambda event: None)
    ids = {bus.publish("jobs.done", {"n": number}, source="core").id for number in range(60)}
    bus.close()
    script = tmp_path / "worker.py"
    script.write_text(WORKER, encoding="utf-8")
    outs = [tmp_path / f"out{number}.txt" for number in range(2)]
    workers = [subprocess.Popen([sys.executable, str(script), str(path), str(out)]) for out in outs]
    for worker in workers:
        assert worker.wait(timeout=120) == 0
    handled = [line for out in outs if out.exists() for line in out.read_text(encoding="utf-8").split()]
    assert sorted(handled) == sorted(ids)
