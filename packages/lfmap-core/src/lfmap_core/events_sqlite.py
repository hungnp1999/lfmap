"""Durable EventBus on SQLite: several processes on one machine, leases, redelivery and dead letters."""

import math
import sqlite3
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lfmap_core.errors import ToolError
from lfmap_core.events import (
    DeadLetter,
    Event,
    Handler,
    check_max_attempts,
    check_max_events,
    check_subscription,
    new_event,
)
from lfmap_core.events_payload import decode_payload
from lfmap_core.events_retry import after_failure, backoff_seconds, describe_error
from lfmap_core.topics import topic_matches

SCHEMA_VERSION = 1
STATES = ("ready", "leased", "done", "dead")
SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL UNIQUE,
    topic TEXT NOT NULL,
    source TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at REAL NOT NULL,
    correlation_id TEXT NOT NULL,
    causation_id TEXT
);
CREATE TABLE IF NOT EXISTS subscriptions (
    name TEXT PRIMARY KEY,
    pattern TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS deliveries (
    event_seq INTEGER NOT NULL REFERENCES events(seq) ON DELETE CASCADE,
    subscription TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('ready', 'leased', 'done', 'dead')),
    attempts INTEGER NOT NULL DEFAULT 0,
    available_at REAL NOT NULL,
    lease_until REAL,
    lease_token TEXT,
    last_error TEXT,
    PRIMARY KEY (event_seq, subscription)
);
CREATE INDEX IF NOT EXISTS deliveries_next ON deliveries (subscription, state, available_at, event_seq);
"""

_EVENT_COLUMNS = "e.id, e.topic, e.source, e.payload, e.created_at, e.correlation_id, e.causation_id"


def _event(row: tuple, attempt: int = 1) -> Event:
    event_id, topic, source, payload, created_at, correlation_id, causation_id = row
    return Event(
        id=event_id,
        topic=topic,
        source=source,
        payload=decode_payload(payload),
        created_at=datetime.fromtimestamp(created_at, UTC),
        correlation_id=correlation_id,
        causation_id=causation_id,
        attempt=attempt,
    )


class SqliteBus:
    def __init__(
        self,
        path: Path,
        *,
        clock: Callable[[], float] = time.time,
        max_attempts: int = 5,
        lease_seconds: float = 60.0,
    ) -> None:
        if type(lease_seconds) not in (int, float) or not math.isfinite(lease_seconds) or lease_seconds <= 0:
            raise ToolError("invalid_input", "lease_seconds must be positive", {"lease_seconds": repr(lease_seconds)})
        check_max_attempts(max_attempts)
        self._clock = clock
        self._max_attempts = max_attempts
        self._lease = float(lease_seconds)
        self._handlers: dict[str, Handler] = {}
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db: sqlite3.Connection | None = sqlite3.connect(path, isolation_level=None, timeout=30)
        try:
            version = self._db.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise ToolError("backend_unavailable", "events.db was written by a newer lfmap", {"version": version})
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA foreign_keys=ON")
            self._db.executescript(SCHEMA)
            self._db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        except BaseException:
            self._db.close()
            raise

    def _conn(self) -> sqlite3.Connection:
        if self._db is None:
            raise ToolError("backend_unavailable", "The event bus is closed")
        return self._db

    def publish(
        self, topic: str, payload: dict[str, Any] | None = None, *, source: str, causation: Event | None = None
    ) -> Event:
        db = self._conn()
        now = self._clock()
        event, text = new_event(topic, payload, source, causation, now)
        db.execute("BEGIN IMMEDIATE")
        try:
            seq = db.execute(
                "INSERT INTO events (id, topic, source, payload, created_at, correlation_id, causation_id)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (event.id, topic, source, text, now, event.correlation_id, event.causation_id),
            ).lastrowid
            for name, pattern in db.execute("SELECT name, pattern FROM subscriptions").fetchall():
                if topic_matches(pattern, topic):
                    db.execute(
                        "INSERT INTO deliveries (event_seq, subscription, state, available_at)"
                        " VALUES (?, ?, 'ready', ?)",
                        (seq, name, now),
                    )
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise
        return event

    def subscribe(self, name: str, pattern: str, handler: Handler) -> None:
        db = self._conn()
        check_subscription(name, pattern)
        db.execute("BEGIN IMMEDIATE")
        try:
            row = db.execute("SELECT pattern FROM subscriptions WHERE name = ?", (name,)).fetchone()
            if row and row[0] != pattern:
                raise ToolError("invalid_input", "Subscription exists with another pattern", {"name": name})
            if row is None:
                db.execute(
                    "INSERT INTO subscriptions (name, pattern, created_at) VALUES (?, ?, ?)",
                    (name, pattern, self._clock()),
                )
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise
        self._handlers[name] = handler

    def unsubscribe(self, name: str) -> None:
        db = self._conn()
        db.execute("BEGIN IMMEDIATE")
        try:
            deleted = db.execute("DELETE FROM subscriptions WHERE name = ?", (name,)).rowcount
            db.execute("DELETE FROM deliveries WHERE subscription = ?", (name,))
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise
        self._handlers.pop(name, None)
        if not deleted:
            raise ToolError("not_found", "Unknown subscription", {"name": name})

    def _claim(self) -> tuple[int, str, str, Event] | None:
        db = self._conn()
        if not self._handlers:
            return None
        now = self._clock()
        names = list(self._handlers)
        marks = ",".join("?" * len(names))
        db.execute("BEGIN IMMEDIATE")
        try:
            row = db.execute(
                f"SELECT d.event_seq, d.subscription, d.attempts, {_EVENT_COLUMNS}"
                " FROM deliveries d JOIN events e ON e.seq = d.event_seq"
                f" WHERE d.subscription IN ({marks})"
                " AND ((d.state = 'ready' AND d.available_at <= ?) OR (d.state = 'leased' AND d.lease_until <= ?))"
                " ORDER BY d.event_seq, d.subscription LIMIT 1",
                (*names, now, now),
            ).fetchone()
            if row is None:
                db.execute("COMMIT")
                return None
            seq, name, attempts = row[:3]
            token = uuid.uuid4().hex
            db.execute(
                "UPDATE deliveries SET state = 'leased', attempts = ?, lease_until = ?, lease_token = ?"
                " WHERE event_seq = ? AND subscription = ?",
                (attempts + 1, now + self._lease, token, seq, name),
            )
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise
        return seq, name, token, _event(row[3:], attempts + 1)

    def _settle(self, seq: int, name: str, token: str, sets: str, values: tuple) -> None:
        self._conn().execute(
            f"UPDATE deliveries SET {sets}, lease_until = NULL, lease_token = NULL"
            " WHERE event_seq = ? AND subscription = ? AND lease_token = ? AND state = 'leased'",
            (*values, seq, name, token),
        )

    def drain(self, *, max_events: int = 1000) -> int:
        self._conn()
        check_max_events(max_events)
        count = 0
        while count < max_events and (claimed := self._claim()) is not None:
            seq, name, token, event = claimed
            count += 1
            handler = self._handlers.get(name)
            try:
                if handler is None:
                    raise ToolError("not_found", "Subscription has no handler here")
                handler(event)
            except Exception as error:  # noqa: BLE001 - a handler failure never stops the drain
                if after_failure(error, event.attempt, self._max_attempts) == "dead":
                    self._settle(seq, name, token, "state = 'dead', last_error = ?", (describe_error(error),))
                else:
                    available = self._clock() + backoff_seconds(event.attempt)
                    self._settle(seq, name, token, "state = 'ready', available_at = ?", (available,))
                continue
            self._settle(seq, name, token, "state = 'done'", ())
        return count

    def dead_letters(self, subscription: str | None = None) -> list[DeadLetter]:
        rows = (
            self._conn()
            .execute(
                f"SELECT d.subscription, d.attempts, d.last_error, {_EVENT_COLUMNS}"
                " FROM deliveries d JOIN events e ON e.seq = d.event_seq"
                " WHERE d.state = 'dead' AND (? IS NULL OR d.subscription = ?) ORDER BY d.event_seq, d.subscription",
                (subscription, subscription),
            )
            .fetchall()
        )
        return [
            DeadLetter(event=_event(row[3:]), subscription=row[0], attempts=row[1], error=row[2] or "") for row in rows
        ]

    def retry(self, event_id: str, subscription: str) -> None:
        changed = (
            self._conn()
            .execute(
                "UPDATE deliveries SET state = 'ready', attempts = 0, available_at = ?, last_error = NULL"
                " WHERE subscription = ? AND state = 'dead' AND event_seq = (SELECT seq FROM events WHERE id = ?)",
                (self._clock(), subscription, event_id),
            )
            .rowcount
        )
        if not changed:
            raise ToolError("not_found", "No such dead letter", {"event": event_id, "subscription": subscription})

    def counts(self) -> dict[str, dict[str, int]]:
        """Deliveries per subscription and state, every durable subscription included."""
        rows = (
            self._conn()
            .execute(
                "SELECT s.name, d.state, COUNT(d.state) FROM subscriptions s"
                " LEFT JOIN deliveries d ON d.subscription = s.name GROUP BY s.name, d.state ORDER BY s.name"
            )
            .fetchall()
        )
        result: dict[str, dict[str, int]] = {}
        for name, state, count in rows:
            states = result.setdefault(name, dict.fromkeys(STATES, 0))
            if state is not None:
                states[state] = count
        return result

    def prune(self, *, older_than: float) -> int:
        """Delete events older than `older_than` seconds whose deliveries are all done; dead letters stay."""
        if type(older_than) not in (int, float) or not math.isfinite(older_than) or older_than < 0:
            raise ToolError("invalid_input", "older_than must be >= 0", {"older_than": repr(older_than)})
        return (
            self._conn()
            .execute(
                "DELETE FROM events WHERE created_at < ?"
                " AND NOT EXISTS (SELECT 1 FROM deliveries d WHERE d.event_seq = seq AND d.state != 'done')",
                (self._clock() - older_than,),
            )
            .rowcount
        )

    def close(self) -> None:
        if self._db is not None:
            self._db.close()
            self._db = None
