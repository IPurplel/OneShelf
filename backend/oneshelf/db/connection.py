"""SQLite connection policy (Master §18): WAL, FULL sync, foreign keys, explicit transactions."""
from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

BUSY_TIMEOUT_MS = 5000


class Connection(sqlite3.Connection):
    """Closes on context exit (the stdlib connection only commits/rolls back)."""

    def __exit__(self, exc_type, exc, tb):  # type: ignore[override]
        self.close()
        return False


def open_database(path: str | Path) -> Connection:
    conn = sqlite3.connect(
        str(path),
        factory=Connection,
        isolation_level=None,  # autocommit; writes use explicit transaction()
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = FULL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn  # type: ignore[return-value]


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Short write transaction; takes the write lock up front to avoid upgrade deadlocks."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")
