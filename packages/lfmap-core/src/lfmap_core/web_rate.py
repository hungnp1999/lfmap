"""Per-host rolling window for `web.fetch`, shared across processes in `web_rate.db` (web-plugin spec section 6).

Never sleeps; at the limit the call fails with `retry_after_s`. If the file cannot be used the call fails closed.
The file is derived state: safe to delete, not backed up.
"""

import contextlib
import math
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path

from lfmap_core.errors import ToolError

WINDOW_S = 60.0


def _state_error() -> ToolError:
    return ToolError("backend_unavailable", "The web rate state could not be used", {"reason": "rate_state"})


class RateLimiter:
    def __init__(self, path: Path, limit: int, clock: Callable[[], float] = time.time) -> None:
        self._path = path
        self._limit = limit
        self._clock = clock

    def acquire(self, host: str) -> None:
        """Record one request to `host`, or raise `rate_limited` when the last 60 s already hold `limit`."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            db = sqlite3.connect(self._path, timeout=5.0, isolation_level=None)
        except (OSError, sqlite3.Error):
            raise _state_error() from None
        try:
            retry = self._acquire(db, host)
        except sqlite3.Error:
            raise _state_error() from None
        finally:
            with contextlib.suppress(sqlite3.Error):
                db.close()
        if retry is not None:
            raise ToolError(
                "backend_unavailable",
                f"Rate limit for {host} reached; try again later",
                {"reason": "rate_limited", "retry_after_s": retry},
            )

    def _acquire(self, db: sqlite3.Connection, host: str) -> int | None:
        now = self._clock()
        db.execute("CREATE TABLE IF NOT EXISTS hits (host TEXT NOT NULL, at REAL NOT NULL)")
        db.execute("BEGIN IMMEDIATE")
        try:
            db.execute("DELETE FROM hits WHERE at <= ?", (now - WINDOW_S,))
            count, oldest = db.execute("SELECT COUNT(*), MIN(at) FROM hits WHERE host = ?", (host,)).fetchone()
            if count >= self._limit:
                db.execute("COMMIT")
                return max(1, math.ceil(oldest + WINDOW_S - now))
            db.execute("INSERT INTO hits (host, at) VALUES (?, ?)", (host, now))
            db.execute("COMMIT")
        except BaseException:
            with contextlib.suppress(sqlite3.Error):
                db.execute("ROLLBACK")
            raise
        return None
