"""Heavy work off the event loop (Master §15, §26, §56; I-96).

Backups, restores, exports, storage migration, scans and large-file checksums can take minutes. Run on the
event loop they freeze every request, the Reader included, for as long as they run. Here each such job runs in
a worker thread with its **own** SQLite connection to the same database file: WAL lets readers proceed, short
write transactions and the busy timeout serialise writers, and the event loop stays free to answer.

A service object is cloned for the worker with its connection (and any collaborator that holds one, such as
notifications) rebound, so nothing the worker touches shares a connection with the loop.
"""
from __future__ import annotations

import asyncio
import copy
import sqlite3
from collections.abc import Callable
from typing import TypeVar

from oneshelf.db.connection import open_database

T = TypeVar("T")
_COLLABORATORS = ("backups", "notifications")


def database_path(conn: sqlite3.Connection) -> str | None:
    """The file behind a connection, or None for an in-memory database."""
    for row in conn.execute("PRAGMA database_list"):
        if row[1] == "main":
            return row[2] or None
    return None


def rebound(service: T, conn: sqlite3.Connection) -> T:
    """A shallow copy of `service` that uses `conn`, as do its connection-holding collaborators."""
    clone = copy.copy(service)
    clone.conn = conn
    for name in _COLLABORATORS:
        collaborator = getattr(clone, name, None)
        if collaborator is not None and hasattr(collaborator, "conn"):
            setattr(clone, name, rebound(collaborator, conn))
    return clone


async def in_worker(conn: sqlite3.Connection, work: Callable[[sqlite3.Connection], T]) -> T:
    """Run `work(worker_connection)` in a thread; the connection is opened and closed around it."""
    path = database_path(conn)
    if path is None:                      # an in-memory database cannot be shared with a second connection
        return work(conn)

    def run() -> T:
        with open_database(path) as worker:
            return work(worker)

    return await asyncio.to_thread(run)


async def off_loop(function: Callable[..., T], *args, **kwargs) -> T:
    """Run a pure CPU or file function (hashing, decoding, validation) in a thread. No database access."""
    return await asyncio.to_thread(function, *args, **kwargs)
