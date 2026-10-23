"""Whether a unit's downloaded copy can be opened on this device now (UI-003).

The Reader opens a unit's oldest sound copy of a format; Downloads offers "Open" only when that copy is really
there, and a new download replaces a copy only when it is really gone. One answer, here, so they never disagree.
"""
from __future__ import annotations

import os
import sqlite3

from oneshelf.storage.paths import PathSafetyError, resolve_within
from oneshelf.storage.roots import RootError, check_availability, get_root

PRESENT, MISSING, UNREACHABLE = "present", "missing", "unreachable"


def local_copy(conn: sqlite3.Connection, unit_id: str, file_format: str | None = None) -> sqlite3.Row | None:
    """The copy the Reader opens: the unit's oldest sound record, of that format when one is asked for."""
    return conn.execute(
        "SELECT * FROM assets WHERE reading_unit_id = ? AND integrity = 'ok'"
        " AND (? IS NULL OR format = ?) ORDER BY created_at, id LIMIT 1",
        (unit_id, file_format, file_format)).fetchone()


def copy_state(conn: sqlite3.Connection, asset: sqlite3.Row, roots: dict | None = None) -> str:
    """`present`; `missing` when its location is connected and the file is not there; else `unreachable`.

    A location that is not connected, or is not the one OneShelf marked, says nothing about the file, and
    neither does a path OneShelf refuses to follow: unreachable, not missing. A read-only location still
    opens. `roots` remembers each location's answer for the length of one request.
    """
    roots = {} if roots is None else roots
    root_id = asset["storage_root_id"]
    if root_id not in roots:
        try:
            root = get_root(conn, root_id)
        except (ValueError, RootError):
            root = None
        else:
            availability = check_availability(root)
            if not (availability.available or availability.reason == "not_writable"):
                root = None
        roots[root_id] = root
    root = roots[root_id]
    if root is None:
        return UNREACHABLE
    try:
        path = resolve_within(root.path, asset["relative_path"])
    except PathSafetyError:
        return UNREACHABLE
    if path.is_file():
        return PRESENT
    return UNREACHABLE if os.path.lexists(path) else MISSING
